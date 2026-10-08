"""Observed website document links, approved bounded downloads and upload staging.

Raw URLs remain in ephemeral tickets. Browser-native downloads run in owned,
isolated pages; this module never uses an HTTP client or reads browser cookies.
Limits bound retained files. A browser may receive temporary bytes before its
completion event exposes their size, which is explicitly reported.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import time
import unicodedata
import uuid
from urllib.parse import unquote, urlsplit, urlunsplit
import zipfile

from .archives import ArchiveError, verify_file
from .attachments import AttachmentQueue, MAX_USER_FILES
from .document_catalogue import CATALOGUE_SPECS, FILE_SPEC, build_catalogue, rank_records, export_catalogue, execute_catalogue, current_scope
from .policy import PolicyError, URLPolicy, config_value, reject_path_redirection


def _obj(properties, required=()):
    return {"type":"object", "properties":properties, "required":list(required), "additionalProperties":False}


_STRING = {"type":"string", "minLength":1, "maxLength":4096}
_HASH = {"type":"string", "minLength":64, "maxLength":64,"pattern":"^[0-9a-fA-F]{64}$"}
_DOC = _obj({"document_id":_STRING, "expected_sha256":_HASH,
             "expected_mime":{"type":"string", "maxLength":120}}, ("document_id",))
DOCUMENT_SPECS = {
    "browser.documents": (_obj({"selector":_STRING, "tab_id":_STRING,
                                 "max_items":{"type":"integer", "minimum":1, "maximum":100}}),
                          "read_only", "Discover up to 100 visible same-origin document links. Returns ephemeral IDs and query-free metadata; does not navigate or download."),
    "browser.download_batch": (_obj({
        "documents":{"type":"array", "minItems":1, "maxItems":30, "items":_DOC},
        "destination":_STRING, "concurrency":{"type":"integer", "minimum":1, "maximum":3},
        "rate_limit_ms":{"type":"integer", "minimum":100, "maximum":5000},
        "retries":{"type":"integer", "minimum":0, "maximum":2},
        "max_file_bytes":{"type":"integer", "minimum":1, "maximum":20971520},
        "max_total_bytes":{"type":"integer", "minimum":1, "maximum":104857600},
        "timeout_seconds":{"type":"integer", "minimum":1, "maximum":120},
        "resume_manifest":_STRING,"resume_manifest_sha256":_HASH}, ("documents", "destination")),
        "user_approval", "Download only previously observed same-origin documents in bounded owned tabs; preserve failures and return a SHA-256 manifest. Resume skips only exactly reverified prior outputs."),
    "files.transfer_to_copilot": (_obj({"files":{"type":"array", "minItems":1,
        "maxItems":1000, "items":_obj(FILE_SPEC['properties'], ("path", "sha256"))},
        "query":{"type":"string","maxLength":1000},
        "requested_paths":{"type":"array","maxItems":100,"items":_STRING},
        "active_paths":{"type":"array","maxItems":100,"items":_STRING}}, ("files",)),
        "user_approval", "Rank up to 1000 reviewed file references, deduplicate exact content, and queue only the remaining message capacity (at most 10 document slots). Retain deferred catalogue references and an index; queued is not proof of UI upload."),
}
DOCUMENT_SPECS.update(CATALOGUE_SPECS)
_EXAMPLE_TEXT_HASH=hashlib.sha256(b'reviewed report\n').hexdigest()
DOCUMENT_EXAMPLES={
    'browser.documents':{'selector':'main','max_items':50},
    'browser.download_batch':{'documents':[{'document_id':'0123456789abcdef0123456789abcdef'}],
        'destination':'deliveries/reviewed-documents','concurrency':2,'max_file_bytes':20971520,'max_total_bytes':104857600},
    'files.transfer_to_copilot':{'files':[{'path':'deliveries/reviewed-report.txt','sha256':_EXAMPLE_TEXT_HASH,
        'label':'Reviewed report'}],'query':'report'},
    'documents.catalogue':{'files':[{'path':'deliveries/reviewed-report.txt','sha256':_EXAMPLE_TEXT_HASH}]},
    'documents.find':{'catalogue_id':'0123456789abcdef0123456789abcdef','query':'annual report','limit':10},
    'documents.retrieve':{'catalogue_id':'0123456789abcdef0123456789abcdef','references':['doc-0123456789abcdef01234567']},
}

_EXTENSIONS = {'.pdf','.docx','.xlsx','.pptx','.doc','.xls','.ppt','.zip','.txt','.csv',
               '.json','.md','.png','.jpg','.jpeg','.webp','.bmp','.xml','.rtf'}
_DISCOVER = r"""params => {
 const state=window.__agentWebDocuments||(window.__agentWebDocuments={ids:new WeakMap(),next:1});
 const key=n=>{if(!state.ids.has(n))state.ids.set(n,state.next++);return state.ids.get(n);};
 const root=params.selector?document.querySelector(params.selector):document;
 if(!root)return {error:'container_missing'};
 if(params.selector&&document.querySelectorAll(params.selector).length!==1)return {error:'container_ambiguous'};
 const links=[];let scanned=0;const walk=r=>{
   const walker=document.createTreeWalker(r,NodeFilter.SHOW_ELEMENT);let n;
   while((n=walker.nextNode())&&scanned<5000){scanned++;
     if(n.matches('a[href]')&&n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden'&&n.getAttribute('aria-disabled')!=='true')
       links.push({key:key(n),href:n.href,download:n.getAttribute('download'),
         label:String(n.innerText||n.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim().slice(0,160)});
     if(n.shadowRoot)walk(n.shadowRoot);
   }
 };walk(root);
 return {links,scanned,truncated:scanned>=5000};
}"""
_RECHECK = r"""params => {
 const state=window.__agentWebDocuments;if(!state)return false;
 let scanned=0;const walk=r=>{const walker=document.createTreeWalker(r,NodeFilter.SHOW_ELEMENT);let n;
 while((n=walker.nextNode())&&scanned<5000){scanned++;
   if(n.matches('a[href]')&&params.keys.includes(state.ids.get(n))&&n.href===params.href&&n.getClientRects().length&&n.getAttribute('aria-disabled')!=='true')return true;
   if(n.shadowRoot&&walk(n.shadowRoot))return true;
 }return false;};return walk(document);
}"""


def _safe_url(value):
    parsed=urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))[:500]


def _origin(value):
    parsed=urlsplit(value)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80)


def _hash(path, cap):
    digest=hashlib.sha256(); count=0
    with Path(path).open('rb') as source:
        while block:=source.read(65536):
            count+=len(block)
            if count>cap: raise PolicyError('File exceeds the configured document limit')
            digest.update(block)
    return digest.hexdigest(), count


def _name(raw, url):
    """Names are deterministic, portable, non-executable, and never raw paths."""
    suggested=raw or unquote(urlsplit(url).path.rsplit('/',1)[-1]) or 'document'
    suggested=unicodedata.normalize('NFKC', suggested)
    suggested=''.join('_' if unicodedata.category(char).startswith('C') else char for char in suggested)
    suggested=re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', '_', suggested).strip(' .')[:120]
    suffix=Path(suggested).suffix.lower()
    if suffix not in _EXTENSIONS: suffix=Path(urlsplit(url).path).suffix.lower()
    if suffix not in _EXTENSIONS: raise PolicyError('Document has no supported safe extension')
    stem=(Path(suggested).stem if Path(suggested).suffix else suggested).strip(' .') or 'document'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',stem,re.I): stem='document_'+stem
    return stem[:90]+'-'+hashlib.sha256(url.encode()).hexdigest()[:16]+suffix


def _validate_shape(value, schema):
    kind=schema.get('type')
    if kind=='object':
        if not isinstance(value,dict) or set(value)-set(schema['properties']) or set(schema['required'])-set(value):
            raise ValueError('Missing or unsupported document arguments')
        for key,item in value.items(): _validate_shape(item,schema['properties'][key])
    elif kind=='array':
        if not isinstance(value,list) or not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',100): raise ValueError('Invalid document array length')
        for item in value: _validate_shape(item,schema['items'])
    elif kind=='string':
        if not isinstance(value,str) or not value.strip() or not schema.get('minLength',1)<=len(value)<=schema.get('maxLength',4096): raise ValueError('Invalid document string')
        if schema.get('pattern') and not re.search(schema['pattern'],value): raise ValueError('Invalid document string pattern')
    elif kind=='integer':
        if type(value) is not int or not schema['minimum']<=value<=schema['maximum']: raise ValueError('Invalid document limit')


def validate_documents(name, args, context=None, policy=None):
    if name not in DOCUMENT_SPECS: raise ValueError('Unknown document capability')
    _validate_shape(args,DOCUMENT_SPECS[name][0])
    items=args.get('documents',args.get('files',[]))
    for item in items:
        digest=item.get('expected_sha256',item.get('sha256'))
        if digest is not None and not re.fullmatch('[0-9a-fA-F]{64}',digest): raise ValueError('Expected a complete SHA-256 digest')
        mime=item.get('expected_mime')
        if mime is not None and not re.fullmatch(r'[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+',mime): raise ValueError('Expected one plain MIME type')
    if args.get('resume_manifest'):
        digest=args.get('resume_manifest_sha256')
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-fA-F]{64}',digest): raise ValueError('Resume requires its exact reviewed manifest SHA-256')
    if context is not None and policy is not None:
        if name=='browser.download_batch':
            destination=policy.resolve(args['destination'])
            storage=config_value(context.get('config',{}),'storage_dir')
            if storage is None: raise PolicyError('Select approved OneDrive storage before downloading website documents')
            if not destination.is_relative_to(Path(storage).resolve()): raise PolicyError('Website downloads must stay inside the selected storage')
            if destination.exists() and not destination.is_dir(): raise PolicyError('Document destination must be a directory')
            if not destination.exists() and not destination.parent.is_dir(): raise PolicyError('Document destination parent must already exist')
            if 'resume_manifest' in args: policy.resolve(args['resume_manifest'],True)
        if name=='files.transfer_to_copilot':
            for item in args['files']: policy.resolve(item['path'],True)
    return {'valid':True}


def _page(context, tab_id=None):
    browser=context.get('browser')
    if browser is None: raise PolicyError('An owned isolated browser is required')
    if tab_id:
        state=getattr(browser,'_navigation_state',{}) or {}
        record=state.get('tabs',{}).get(tab_id)
        if record is None: raise PolicyError('Unknown or closed document tab')
        for field in ('task_id','customer_key'):
            if context.get(field) is not None and record.get(field)!=context[field]: raise PolicyError('Document tab belongs to another task or customer')
        page=record['page']
    else: page=context.get('web_page') or getattr(browser,'tool_page',None)
    if page is None or callable(getattr(page,'is_closed',None)) and page.is_closed(): raise PolicyError('Owned document page is unavailable')
    if (getattr(page,'context',None) is not getattr(browser,'tool_context',None)
            or page not in getattr(browser,'_tool_pages',[page])): raise PolicyError('Document tools require an owned website tab')
    return browser,page


def _urls(context, browser):
    domains=set(getattr(browser,'tool_domains',set())) & set(context.get('approved_domains',getattr(browser,'tool_domains',set())))
    if not domains: raise PolicyError('The current website needs explicit domain approval')
    return URLPolicy(domains)


def _scope(context, browser, page):
    """Inherit a planning tab's scope without widening the caller's authority."""
    tabs=(getattr(browser,'_navigation_state',{}) or {}).get('tabs',{})
    record=next((value for value in tabs.values() if value.get('page') is page),None)
    if record is not None and record.get('customer_key') is not None and context.get('customer_key')!=record['customer_key']:
        raise PolicyError('Explicit current customer context is required for this document page')
    result={}
    for field in ('task_id','customer_key','tenant_id','site_namespace_id'):
        requested=context.get(field)
        bound=record.get(field) if record is not None and field in record else requested
        if requested is not None and bound!=requested: raise PolicyError('Document page belongs to another task or customer')
        result[field]=bound
    return result


async def _discover(args, context):
    browser,page=_page(context,args.get('tab_id'))
    urls=_urls(context,browser); urls.resolve(page.url)
    scope=_scope(context,browser,page)
    observed=await page.evaluate(_DISCOVER,{'selector':args.get('selector')})
    if observed.get('error'): raise ValueError('Document scope must identify one visible container')
    tickets=context.setdefault('web_document_tickets',{})
    # Tickets never cross a session/context and expire after ten minutes.
    now=time.monotonic()
    for key,value in list(tickets.items()):
        if now-value['created']>600: tickets.pop(key,None)
    grouped={}
    for link in observed.get('links',[]):
        raw=link.get('href','')
        try:
            urls.resolve(raw)
            if _origin(raw)!=_origin(page.url): continue
            extension=Path(urlsplit(raw).path).suffix.lower()
            if extension not in _EXTENSIONS and link.get('download') is None: continue
            filename=_name(link.get('download'),raw)
        except (ValueError,PolicyError): continue
        grouped.setdefault(raw,{'link':link,'keys':[],'filename':filename})['keys'].append(link['key'])
    documents=[]; limit=args.get('max_items',50)
    for raw,value in list(grouped.items())[:limit]:
        if len(tickets)>=500: raise PolicyError('Document ticket limit reached; finish the current batch before rediscovery')
        document_id=uuid.uuid4().hex
        tickets[document_id]={'url':raw,'page':page,'source_url':page.url,'context':browser.tool_context,
            'created':now,'keys':value['keys'],'filename':value['filename'],
            **scope}
        documents.append({'document_id':document_id,'label':value['link'].get('label','')[:160],
            'url':_safe_url(raw),'href_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'filename':value['filename'],'extension':Path(value['filename']).suffix,
            'duplicate_count':len(value['keys'])-1})
    return {'documents':documents,'count':len(documents),'truncated':len(grouped)>limit or bool(observed.get('truncated')),
            'source_url':_safe_url(page.url),'scope':'visible same-origin observed links; ephemeral ten-minute IDs'}


async def _bound(item, context, browser):
    ticket=context.get('web_document_tickets',{}).get(item['document_id'])
    if ticket is None or ticket['context'] is not browser.tool_context or time.monotonic()-ticket['created']>600:
        raise PolicyError('Document identity is stale or belongs to another browser session; rediscover it')
    page=ticket['page']
    current_scope=_scope(context,browser,page)
    for field in ('task_id','customer_key','tenant_id','site_namespace_id'):
        if ticket.get(field)!=current_scope[field]: raise PolicyError('Document identity belongs to another task or customer')
    if callable(getattr(page,'is_closed',None)) and page.is_closed() or page.url!=ticket['source_url']:
        raise PolicyError('Document source page changed; rediscover before downloading')
    _urls(context,browser).resolve(ticket['url'])
    if _origin(ticket['url'])!=_origin(page.url): raise PolicyError('Document source is no longer same-origin')
    valid=await page.evaluate(_RECHECK,{'keys':ticket['keys'],'href':ticket['url']})
    if valid is not True: raise PolicyError('Observed document anchor changed or disappeared; rediscover it')
    return ticket


def _integrity(path, expected_mime=None, observed_mime=None):
    extension=path.suffix.lower()
    with path.open('rb') as source:
        header=source.read(32); source.seek(max(0,path.stat().st_size-2048)); tail=source.read()
    if not header: raise PolicyError('Empty or incomplete document')
    signatures={'.pdf':header.startswith(b'%PDF-') and b'%%EOF' in tail,
        '.png':header.startswith(b'\x89PNG\r\n\x1a\n') and tail.endswith(b'IEND\xaeB`\x82'),
        '.jpg':header.startswith(b'\xff\xd8\xff') and tail.rstrip().endswith(b'\xff\xd9'),
        '.jpeg':header.startswith(b'\xff\xd8\xff') and tail.rstrip().endswith(b'\xff\xd9'),
        '.webp':header.startswith(b'RIFF') and header[8:12]==b'WEBP',
        '.bmp':header.startswith(b'BM'), '.rtf':header.startswith(b'{\\rtf')}
    if extension in signatures and not signatures[extension]: raise PolicyError('Document signature or completion marker does not match its extension')
    if extension in {'.doc','.xls','.ppt'} and not header.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        raise PolicyError('Legacy Office signature does not match its extension')
    if extension in {'.zip','.docx','.xlsx','.pptx'}:
        if not zipfile.is_zipfile(path): raise PolicyError('Document ZIP/Office package is incomplete or corrupt')
        try:
            with zipfile.ZipFile(path) as archive:
                if len(archive.infolist())>2000 or sum(info.file_size for info in archive.infolist())>100*1024*1024:
                    raise PolicyError('Document container exceeds verification limits')
                if any(info.flag_bits&1 or info.file_size>20*1024*1024 or info.file_size/max(1,info.compress_size)>200 for info in archive.infolist()):
                    raise PolicyError('Encrypted or excessive document container is unsupported')
                if archive.testzip() is not None: raise PolicyError('Document container CRC failed')
        except (zipfile.BadZipFile,RuntimeError,NotImplementedError) as error: raise PolicyError('Document container is not readable') from error
    guessed=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    observed=(observed_mime or '').split(';',1)[0].strip().lower()
    if observed in {'text/html','application/xhtml+xml'} and extension not in {'.html','.htm'}:
        raise PolicyError('Website returned an HTML error/authentication page instead of the document')
    if expected_mime and observed and observed!=expected_mime.lower(): raise PolicyError('Observed document MIME does not match the approved expectation')
    if expected_mime and not observed and guessed!=expected_mime.lower(): raise PolicyError('Document extension MIME does not match the approved expectation')
    aliases={'.csv':{'text/csv','application/csv','text/plain','application/vnd.ms-excel'},
             '.txt':{'text/plain'},'.md':{'text/markdown','text/plain'},
             '.json':{'application/json','text/json','text/plain'},
             '.xml':{'application/xml','text/xml','text/plain'},
             '.zip':{'application/zip','application/x-zip-compressed'},
             '.jpg':{'image/jpeg','image/jpg','image/pjpeg'},
             '.jpeg':{'image/jpeg','image/jpg','image/pjpeg'},
             '.bmp':{'image/bmp','image/x-ms-bmp'}}
    allowed=aliases.get(extension,{guessed})|{'application/octet-stream','binary/octet-stream'}
    if observed and observed not in allowed: raise PolicyError('Response MIME conflicts with the document extension')
    # Reuse the existing independent static Office/text/container verifier.
    try: evidence=verify_file(path)
    except ArchiveError as error: raise PolicyError(str(error)) from error
    return {'mime':observed or guessed,'mime_source':'response_header' if observed else 'extension_and_signature',
            'signature_checked':extension in signatures or extension in {'.zip','.docx','.xlsx','.pptx','.doc','.xls','.ppt'},
            'static_verification':evidence}


async def _download_batch(args, context, policy):
    browser,_=_page(context)
    config=context.get('config',{})
    batch_scope=None
    for item in args['documents']:
        ticket=context.get('web_document_tickets',{}).get(item['document_id'])
        if ticket is None: continue
        scope={field:ticket.get(field) for field in ('task_id','customer_key','tenant_id','site_namespace_id')}
        parsed=urlsplit(ticket['source_url']); scope['origin']=parsed.scheme+'://'+(parsed.hostname or '')
        if batch_scope is not None and scope!=batch_scope: raise PolicyError('One download batch cannot combine different tasks, customers, tenants or website namespaces')
        batch_scope=scope
    if batch_scope is None: batch_scope=current_scope(context)
    per_file=min(args.get('max_file_bytes',20971520),config_value(config,'max_download_bytes',20971520))
    aggregate=args.get('max_total_bytes',104857600)
    destination=policy.resolve(args['destination'])
    if not destination.exists(): destination.mkdir(exist_ok=False)
    manifest_path=policy.resolve(destination/('download-manifest-'+uuid.uuid4().hex+'.json'))
    previous={}
    if args.get('resume_manifest'):
        source=policy.resolve(args['resume_manifest'],True)
        if source.stat().st_size>1048576: raise PolicyError('Resume manifest exceeds one MB')
        digest,_=_hash(source,1048576)
        if (digest!=args['resume_manifest_sha256'].lower()
                or context.get('download_manifest_hashes',{}).get(str(source))!=digest):
            raise PolicyError('Resume manifest is not an unchanged verified artifact from this session')
        prior=json.loads(source.read_text(encoding='utf-8'))
        if prior.get('schema_version')!='1.0' or prior.get('destination')!=str(destination) or prior.get('scope')!=batch_scope:
            raise PolicyError('Resume manifest destination, schema or task/customer scope differs')
        previous={entry.get('href_sha256'):entry for entry in prior.get('files',[]) if entry.get('status') in {'success','skipped'} and entry.get('sha256')}
    slots=asyncio.Semaphore(args.get('concurrency',2)); rate_lock=asyncio.Lock(); accounting=asyncio.Lock(); page_lock=asyncio.Lock()
    next_start=0.0; retained=0; seen={}; output=[None]*len(args['documents']); uncertain=False
    stop=context.get('cancel_event')
    async def pace():
        nonlocal next_start
        async with rate_lock:
            delay=max(0,next_start-time.monotonic())
            if delay: await asyncio.sleep(delay)
            next_start=time.monotonic()+args.get('rate_limit_ms',250)/1000
    async def one(index,item):
        nonlocal retained, uncertain
        record={'document_id':item['document_id'],'status':'failure','attempts':0}
        page=None; download=None; target=None; navigation_started=False; native_accounted=False
        try:
            if stop is not None and stop.is_set(): raise PolicyError('Document batch cancelled before starting this file')
            ticket=await _bound(item,context,browser)
            raw=ticket['url']; href_hash=hashlib.sha256(raw.encode()).hexdigest()
            record.update({'href_sha256':href_hash,'source_origin':urlsplit(raw).scheme+'://'+urlsplit(raw).hostname,'filename':ticket['filename']})
            if href_hash in seen:
                record.update({'status':'skipped','reason':'duplicate_link','duplicate_of':seen[href_hash]}); return
            seen[href_hash]=index
            target=policy.resolve(destination/ticket['filename']); record['path']=str(target)
            prior=previous.get(href_hash)
            if target.exists():
                if prior and prior.get('path')==str(target):
                    checked=policy.resolve(target,True); digest,size=_hash(checked,per_file)
                    if digest!=prior.get('sha256') or item.get('expected_sha256',digest).lower()!=digest:
                        raise PolicyError('Resume output differs from its exact reviewed checksum; partial file preserved')
                    evidence=_integrity(target,item.get('expected_mime'))
                    async with accounting:
                        if retained+size>aggregate: raise PolicyError('Resume outputs exceed aggregate size limit')
                        retained+=size
                    record.update({'status':'skipped','reason':'verified_resume','sha256':digest,'size':size,**evidence}); return
                raise PolicyError('Destination already exists; no overwrite or partial-file reuse is permitted')
            async with slots:
                async with page_lock:
                    cap=config_value(config,'max_tool_tabs',6)
                    existing=sum(not p.is_closed() for p in getattr(browser,'_tool_pages',[]) if callable(getattr(p,'is_closed',None)))
                    if existing>=cap: raise PolicyError('Owned tab limit reached; close an independent tab first')
                    page=await browser.new_tool_page()
                responses={}; metadata_tasks=[]
                async def response_metadata(response):
                    if response.url!=raw: return
                    try:
                        headers=await response.all_headers()
                        responses.update({'mime':headers.get('content-type'),'status':response.status})
                        if headers.get('content-encoding','identity')=='identity' and headers.get('content-length','').isdigit(): responses['length']=int(headers['content-length'])
                    except Exception: pass
                def observe_response(response):
                    task=asyncio.create_task(response_metadata(response)); metadata_tasks.append(task)
                page.on('response',observe_response)
                async def strict_origin(route):
                    try:
                        _urls(context,browser).resolve(route.request.url)
                        if _origin(route.request.url)!=_origin(raw): raise PolicyError('Cross-origin document redirect is forbidden')
                    except (PolicyError,ValueError): await route.abort('blockedbyclient')
                    else: await route.fallback()
                await page.route('**/*',strict_origin)
                timeout=args.get('timeout_seconds',60)
                for attempt in range(args.get('retries',1)+1):
                    record['attempts']=attempt+1
                    responses.clear(); metadata_tasks.clear()
                    if stop is not None and stop.is_set(): raise PolicyError('Document batch cancelled')
                    await _bound(item,context,browser); await pace()
                    grants=getattr(browser,'_approved_web_downloads',None)
                    if grants is None: browser._approved_web_downloads={}; grants=browser._approved_web_downloads
                    grants[page]={raw}
                    try:
                        async with page.expect_download(timeout=timeout*1000) as pending:
                            navigation_started=True
                            try: await page.goto(raw,wait_until='domcontentloaded',timeout=timeout*1000)
                            except Exception as error:
                                if not any(marker in str(error) for marker in ('Download is starting','net::ERR_ABORTED')): raise
                        download=await pending.value
                        if download.url!=raw: raise PolicyError('Download event is not the exact observed source; no redirected URL is accepted')
                        if metadata_tasks: await asyncio.gather(*metadata_tasks)
                        if responses.get('status') in {401,403,429} or responses.get('status',200)>=500:
                            raise PolicyError('Document response requires authentication, permission or service recovery; stop and inspect')
                        if responses.get('length',0)>per_file: raise PolicyError('Response Content-Length exceeds the per-file limit')
                        failure=await asyncio.wait_for(download.failure(),timeout)
                        if failure:
                            native_accounted=True
                            if attempt<args.get('retries',1) and any(code in failure for code in ('ERR_CONNECTION_RESET','ERR_CONNECTION_CLOSED','ERR_NETWORK_CHANGED')):
                                await download.cancel(); download=None; navigation_started=False; continue
                            raise PolicyError('Browser reports an incomplete document download')
                        native=await asyncio.wait_for(download.path(),timeout)
                        if native is None: raise PolicyError('Browser did not expose a completed native artifact')
                        native_accounted=True
                        native=Path(native); reject_path_redirection(native)
                        if not native.is_file() or native.stat().st_nlink>1: raise PolicyError('Native browser artifact is not one regular unaliased file')
                        digest,size=_hash(native,per_file)
                        if responses.get('length') is not None and responses['length']!=size: raise PolicyError('Completed bytes do not match response Content-Length')
                        if item.get('expected_sha256',digest).lower()!=digest: raise PolicyError('Document checksum does not match approved expectation')
                        async with accounting:
                            if retained+size>aggregate: raise PolicyError('Document batch aggregate size limit exceeded')
                            retained+=size
                        policy.resolve(target)
                        copied=hashlib.sha256(); count=0
                        with native.open('rb') as source,target.open('xb') as outgoing:
                            while block:=source.read(65536):
                                count+=len(block)
                                if count>size or count>per_file: raise PolicyError('Native download grew during exclusive copying')
                                outgoing.write(block); copied.update(block)
                        policy.resolve(target,True)
                        if count!=size or copied.hexdigest()!=digest: raise PolicyError('Retained document changed while copying')
                        evidence=_integrity(target,item.get('expected_mime'),responses.get('mime'))
                        record.update({'status':'success','sha256':digest,'size':size,**evidence}); break
                    finally:
                        grants.pop(page,None)
        except asyncio.CancelledError:
            record['error']={'code':'cancelled','message':'Batch cancelled; retained files must be inspected before resuming'}
            raise
        except Exception as error:
            record['error']={'code':'policy_denied' if isinstance(error,PolicyError) else 'download_failed',
                'message':str(error) if isinstance(error,(PolicyError,ValueError)) else 'Browser document operation failed; no automatic uncertain retry'}
            if target is not None and target.exists(): record['partial_path']=str(target)
        finally:
            output[index]=record
            if download is not None and record['status']=='failure':
                try:
                    await download.cancel(); native_accounted=True
                except Exception: uncertain=True
            if page is not None:
                getattr(browser,'_approved_web_downloads',{}).pop(page,None)
                try: await page.close()
                except Exception: uncertain=True
            if navigation_started and not native_accounted: uncertain=True
    jobs=[asyncio.create_task(one(index,item)) for index,item in enumerate(args['documents'])]
    cancelled=False
    try: await asyncio.gather(*jobs)
    except asyncio.CancelledError:
        cancelled=True
        for job in jobs: job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
    # Keep canonical duplicate references deterministic in input order. Originals
    # and duplicate copies are retained; this capability never deletes files.
    hashes={}
    for record in output:
        if record is None: continue
        digest=record.get('sha256')
        if digest and digest in hashes and record['status']=='success':
            record.update({'status':'skipped','reason':'duplicate_content_preserved','duplicate_of_path':hashes[digest]})
        elif digest: hashes[digest]=record['path']
    failures=sum(record is None or record['status']=='failure' for record in output)
    report={'schema_version':'1.0','status':'cancelled' if cancelled else 'partial' if failures and failures<len(output) else 'failed' if failures else 'verified',
        'destination':str(destination),'scope':batch_scope,'files':[record for record in output if record is not None],
        'side_effects_uncertain':uncertain,
        'summary':{'success':sum(r is not None and r['status']=='success' for r in output),
                   'failure':failures,'skipped':sum(r is not None and r['status']=='skipped' for r in output),'retained_bytes':retained},
        'limits':{'per_file_bytes':per_file,'aggregate_bytes':aggregate,'concurrency':args.get('concurrency',2)},
        'limitations':['Quotas bound retained files. Browser temporary bytes may arrive before size is available.',
                        'Static signatures and checksums do not prove full document rendering or malware safety.'],
        'manifest_path':str(manifest_path)}
    with manifest_path.open('x',encoding='utf-8') as stream: json.dump(report,stream,ensure_ascii=False,indent=2)
    report['manifest_sha256']=_hash(manifest_path,1048576)[0]
    context.setdefault('download_manifest_hashes',{})[str(manifest_path)]=report['manifest_sha256']
    return report


def _transfer(args, context, policy):
    queued=context.get('pending_file_attachments'); approved=context.get('approved_attachment_hashes')
    if not isinstance(queued,list) or not isinstance(approved,dict): raise PolicyError('The orchestrator file-transfer queue is unavailable')
    config=context.get('config',{})
    catalogue=build_catalogue(args['files'],context,policy)
    requested=[str(policy.resolve(path,True)) for path in args.get('requested_paths',[])]
    active=[str(policy.resolve(path,True)) for path in args.get('active_paths',[])]
    ranked=rank_records(catalogue['records'],args.get('query',''),requested,active)
    current={str(Path(path)).casefold() for path in queued}
    confirmed=context.get('transferred_attachment_hashes',{})
    queue=AttachmentQueue(config); existing=queue.add(queued) if queued else []
    capacity=max(0,min(MAX_USER_FILES,context.get('remaining_attachment_capacity',MAX_USER_FILES))-len(existing))
    eligible=[]; omitted=[]; chosen_hashes={record['sha256'] for record in existing}
    for record in ranked:
        reason=None
        if record['path'].casefold() in current: reason='already_queued'
        elif record['sha256'] in chosen_hashes: reason='duplicate_content'
        elif record['sha256'] in confirmed and record['path'] not in requested: reason='already_transferred'
        else:
            try: queue._record(record['path'])
            except PolicyError: reason='unsupported_or_unavailable_for_upload'
        if reason: omitted.append({'reference':record['reference'],'name':record['name'],'reason':reason})
        else: eligible.append(record); chosen_hashes.add(record['sha256'])
    deferred=len(eligible)>capacity or (len(catalogue['records'])>capacity
        and any(record['reason'] not in {'already_transferred','already_queued'} for record in omitted))
    index=None
    # Reserve one available slot for a searchable index when actual files defer.
    selected=eligible[:max(0,capacity-1 if deferred and capacity else capacity)]
    omitted.extend({'reference':record['reference'],'name':record['name'],'reason':'deferred_capacity'}
        for record in eligible[len(selected):])
    if deferred:
        index=export_catalogue(catalogue,context,policy)
        if capacity: selected.append(index)
    records=queue.add([record['path'] for record in selected]) if selected else existing
    expected={record['path']:record['sha256'] for record in [*catalogue['records'],*([index] if index else [])]}
    for record in records:
        if record['path'] in expected and record['sha256']!=expected[record['path']]: raise PolicyError('Transfer file changed from its approved SHA-256')
        if record['path'] not in expected and approved.get(record['path'])!=record['sha256']: raise PolicyError('Previously queued file changed; renew its transfer approval')
    # Commit queue and hashes only after every selected file passes validation.
    approved.update({record['path']:record['sha256'] for record in records})
    queued[:]=[Path(record['path']) for record in records]
    return {'status':'queued' if records else 'deferred','files':[{'path':record['path'],'upload_name':record['upload_name'],
             'sha256':record['sha256'],'size':record['size']} for record in records],
            'count':len(records),'delivery_verified':False,'catalogue_id':catalogue['catalogue_id'],
            'available_count':len(catalogue['records']),'omitted_count':len(omitted),'omitted':omitted[:50],
            'omitted_truncated':len(omitted)>50,'warnings':catalogue['warnings'][:20],
            'index':index,'remaining_capacity':capacity-len(selected),
            'next_action':'documents.find/retrieve resolves deferred originals; next Copilot message verifies only the selected attachments'}


async def execute_documents(name, args, context, policy):
    validate_documents(name,args,context,policy)
    if DOCUMENT_SPECS[name][1]!='read_only' and context.get('approved') is not True:
        raise PolicyError('Explicit local approval is required for document download or transfer')
    if name=='browser.documents': return await _discover(args,context)
    if name=='browser.download_batch': return await _download_batch(args,context,policy)
    if name.startswith('documents.'): return execute_catalogue(name,args,context,policy)
    return _transfer(args,context,policy)
