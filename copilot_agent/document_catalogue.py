"""Session-scoped file references and bounded, on-demand attachment selection.

Indexes describe authorised local files, never file contents. Explicit manifest
imports recheck scope, paths and every digest; an index is not permission to read
outside PathPolicy or reuse another customer's evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit

from .policy import PolicyError, config_value
from .logging_utils import SENSITIVE


def _obj(properties,required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}


_S={'type':'string','minLength':1,'maxLength':4096}
_HASH={'type':'string','minLength':64,'maxLength':64,'pattern':'^[0-9a-fA-F]{64}$'}
FILE_SPEC=_obj({'path':_S,'sha256':_HASH,'label':{'type':'string','maxLength':160},
    'tags':{'type':'array','maxItems':20,'items':{'type':'string','maxLength':80}},
    'priority':{'type':'integer','minimum':0,'maximum':100}},('path',))
CATALOGUE_SPECS={
    'documents.catalogue':(_obj({'files':{'type':'array','minItems':1,'maxItems':1000,'items':FILE_SPEC},
        'manifest_path':_S,'manifest_sha256':_HASH}), 'read_only',
        'Register explicitly selected local file references or import an explicitly reviewed SHA-bound catalogue manifest. Read bounded metadata/hashes, retain task-scoped references, and report exact duplicates and filename-similarity warnings without uploading.'),
    'documents.find':(_obj({'catalogue_id':_S,'query':{'type':'string','maxLength':1000},
        'references':{'type':'array','maxItems':100,'items':_S},
        'limit':{'type':'integer','minimum':1,'maximum':100}},('catalogue_id',)), 'read_only',
        'Search authorised session document metadata. Rank explicitly requested references and query matches; return concise IDs for on-demand retrieval.'),
    'documents.retrieve':(_obj({'catalogue_id':_S,
        'references':{'type':'array','minItems':1,'maxItems':20,'items':_S}},('catalogue_id','references')), 'read_only',
        'Resolve specific catalogue references and reverify current SHA-256 and path authority. Returns files for a separately approved transfer; never silently uploads.'),
}


def current_scope(context):
    browser=context.get('browser'); page=getattr(browser,'tool_page',None)
    tabs=(getattr(browser,'_navigation_state',{}) or {}).get('tabs',{}) if browser is not None else {}
    tab=next((record for record in tabs.values() if record.get('page') is page),{})
    if tab.get('customer_key') is not None and context.get('customer_key')!=tab['customer_key']:
        raise PolicyError('Explicit current customer context is required for this catalogue')
    scope={}
    for field in ('task_id','customer_key','tenant_id','site_namespace_id'):
        scope[field]=context.get(field) if context.get(field) is not None else tab.get(field)
        if field in tab and context.get(field) is not None and tab.get(field)!=context[field]:
            raise PolicyError('Document catalogue belongs to another task or customer')
    origin=urlsplit(getattr(page,'url',''))
    scope['origin']=origin.scheme+'://'+(origin.hostname or '') if origin.hostname else None
    return scope


def bounded_hash(path,cap):
    digest=hashlib.sha256(); count=0
    before=path.stat()
    if not path.is_file() or before.st_nlink>1 or before.st_size>cap: raise PolicyError('Catalogue file must be a bounded regular unaliased file')
    with path.open('rb') as source:
        while block:=source.read(65536):
            count+=len(block)
            if count>cap: raise PolicyError('Catalogue file grew beyond its byte limit')
            digest.update(block)
    after=path.stat()
    if count!=before.st_size or (after.st_mtime_ns,after.st_size)!=(before.st_mtime_ns,before.st_size):
        raise PolicyError('Catalogue file changed while being hashed')
    return digest.hexdigest(),count


def build_catalogue(files,context,policy):
    """Preflight all entries before inserting any catalogue state."""
    if not isinstance(files,list) or not 1<=len(files)<=1000: raise ValueError('Select between one and 1000 authorised file references')
    if len(context.get('document_catalogues',{}))>=100: raise PolicyError('Session catalogue limit reached; reuse existing catalogue references')
    cap=min(20971520,config_value(context.get('config',{}),'max_attachment_bytes',20971520))
    records=[]; paths=set(); hashes={}; names={}; warnings=[]
    for item in files:
        path=policy.resolve(item['path'],True); key=str(path).casefold()
        if key in paths: continue
        paths.add(key); digest,size=bounded_hash(path,cap)
        expected=item.get('sha256')
        if expected is not None and (not isinstance(expected,str) or not re.fullmatch('[0-9a-fA-F]{64}',expected) or expected.lower()!=digest):
            raise PolicyError('Catalogue file differs from its reviewed SHA-256')
        reference='doc-'+hashlib.sha256((str(path)+'\0'+digest).encode()).hexdigest()[:24]
        record={'reference':reference,'path':str(path),'name':path.name,'size':size,'sha256':digest,
            'label':item.get('label',path.name)[:160],'tags':list(item.get('tags',[]))[:20],
            'priority':item.get('priority',0),'extension':path.suffix.casefold()}
        if SENSITIVE.search(' '.join([record['label'],*record['tags']])): raise PolicyError('Credential-like catalogue metadata is forbidden')
        if digest in hashes: record['duplicate_of']=hashes[digest]
        else: hashes[digest]=reference
        # A filename resemblance is evidence to review, never content identity.
        name=re.sub(r'\b(?:v\d+|rev\d+|copy|duplicate|final)\b|[\W_\d]+',' ',path.stem.casefold()).strip()
        if name and name in names and names[name]['sha256']!=digest:
            warnings.append({'reference':reference,'similar_to':names[name]['reference'],
                'reason':'similar_filename_different_sha256','content_identity_proven':False})
        elif name: names[name]=record
        records.append(record)
    catalogue={'schema_version':'document_catalogue/1.0','catalogue_id':uuid.uuid4().hex,
        'scope':current_scope(context),'created_unix':int(time.time()),'records':records,
        'warnings':warnings[:100],'content_retained':False}
    context.setdefault('document_catalogues',{})[catalogue['catalogue_id']]=catalogue
    return catalogue


def _catalogue(context,catalogue_id):
    value=context.get('document_catalogues',{}).get(catalogue_id)
    if value is None: raise PolicyError('Unknown catalogue; explicitly import a reviewed local manifest for a new session')
    if value['scope']!=current_scope(context): raise PolicyError('Catalogue scope changed; do not reuse another task, customer, tenant or website')
    return value


def rank_records(records,query='',requested_paths=(),active_paths=(),references=()):
    terms=set(re.findall(r'[\w-]+',query.casefold()))
    requested={str(Path(path)).casefold() for path in requested_paths}
    active={str(Path(path)).casefold() for path in active_paths}; exact=set(references)
    ranked=[]
    for record in records:
        text=(' '.join([record['name'],record['label'],*record.get('tags',[])])).casefold()
        score=(100000 if record['reference'] in exact or record['path'].casefold() in requested else 0)
        score+=10000 if record['path'].casefold() in active else 0
        score+=100*sum(term in text for term in terms)+record.get('priority',0)
        ranked.append({**record,'relevance_score':score})
    return sorted(ranked,key=lambda record:(-record['relevance_score'],record['name'].casefold(),record['reference']))


def _compact(record):
    return {key:value for key,value in record.items() if key in {
        'reference','name','size','sha256','label','extension','duplicate_of','relevance_score'}}


def export_catalogue(catalogue,context,policy):
    storage=config_value(context.get('config',{}),'storage_dir')
    if storage is None: raise PolicyError('Selected approved storage is required for a deferred document index')
    root=policy.resolve(storage,True)
    path=policy.resolve(root/('document-index-'+catalogue['catalogue_id']+'.json'))
    with path.open('x',encoding='utf-8') as stream: json.dump(catalogue,stream,ensure_ascii=False,indent=2)
    digest,size=bounded_hash(path,2*1024*1024)
    return {'path':str(path),'sha256':digest,'size':size,'name':path.name,
            'reference':'index-'+catalogue['catalogue_id'],'extension':'.json','label':'Deferred document index','priority':100}


def execute_catalogue(name,args,context,policy):
    if name=='documents.catalogue':
        if bool(args.get('files'))==bool(args.get('manifest_path')): raise ValueError('Choose files or one reviewed manifest, not both')
        if args.get('manifest_path'):
            expected=args.get('manifest_sha256')
            if not isinstance(expected,str) or not re.fullmatch('[0-9a-fA-F]{64}',expected): raise ValueError('Manifest import requires its reviewed SHA-256')
            path=policy.resolve(args['manifest_path'],True); digest,_=bounded_hash(path,2*1024*1024)
            if digest!=expected.lower(): raise PolicyError('Catalogue manifest differs from its reviewed hash')
            imported=json.loads(path.read_text(encoding='utf-8'))
            if imported.get('schema_version')!='document_catalogue/1.0': raise ValueError('Unsupported document catalogue manifest schema')
            scope=current_scope(context)
            for field in ('origin','customer_key','tenant_id','site_namespace_id'):
                if imported.get('scope',{}).get(field)!=scope[field]: raise PolicyError('Imported catalogue belongs to another website, tenant or customer')
            files=[{key:record[key] for key in ('path','sha256','label','tags','priority') if key in record}
                for record in imported.get('records',[])]
        else: files=args['files']
        catalogue=build_catalogue(files,context,policy)
        return {'catalogue_id':catalogue['catalogue_id'],'count':len(catalogue['records']),
            'duplicates':sum('duplicate_of' in record for record in catalogue['records']),
            'records':[_compact(record) for record in catalogue['records'][:20]],
            'warnings':catalogue['warnings'][:20],'truncated':len(catalogue['records'])>20,
            'next_action':'documents.find selects metadata; documents.retrieve verifies specific references before approved transfer'}
    catalogue=_catalogue(context,args['catalogue_id'])
    references=args.get('references',[])
    known={record['reference']:record for record in catalogue['records']}
    if set(references)-set(known): raise ValueError('A requested document reference is absent from this catalogue')
    if name=='documents.find':
        ranked=rank_records(catalogue['records'],args.get('query',''),references=references)
        limit=args.get('limit',20)
        return {'catalogue_id':catalogue['catalogue_id'],'count':len(ranked),
            'records':[_compact(record) for record in ranked[:limit]],'truncated':len(ranked)>limit}
    if name!='documents.retrieve': raise ValueError('Unknown catalogue capability')
    selected=[]; cap=min(20971520,config_value(context.get('config',{}),'max_attachment_bytes',20971520))
    for reference in dict.fromkeys(references):
        record=known[reference]; path=policy.resolve(record['path'],True); digest,size=bounded_hash(path,cap)
        if digest!=record['sha256'] or size!=record['size']: raise PolicyError('Referenced document changed; register and review it again')
        selected.append({'reference':reference,'path':str(path),'sha256':digest,'size':size,'name':record['name']})
    return {'catalogue_id':catalogue['catalogue_id'],'files':selected,'status':'verified_references',
            'delivery_verified':False,'next_action':'Request files.transfer_to_copilot for only the necessary files'}
