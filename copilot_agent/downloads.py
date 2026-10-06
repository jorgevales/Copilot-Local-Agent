"""Approved, event-backed downloads from the current Copilot assistant reply.

Signed URLs and element handles live only in opaque in-memory tickets. Preparing
a preview reads UI/settings only. No settings are changed and no files deleted.
"""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit

from .archives import ArchiveError, verify_file


class DownloadError(RuntimeError):
    def __init__(self, code, message, side_effects_uncertain=False):
        self.code = code
        self.side_effects_uncertain = side_effects_uncertain
        super().__init__(message)


def validate_download_args(args):
    if not isinstance(args, dict) or set(args) - {'expected_name', 'link_text', 'expected_sha256'}:
        raise DownloadError('invalid_arguments', 'Download accepts only expected_name, optional link_text and optional expected_sha256; direct URLs are forbidden.')
    name = args.get('expected_name')
    if (not isinstance(name, str) or not name or len(name) > 180 or name != name.strip()
            or name.endswith('.') or name in {'.', '..'}
            or any(ord(char) < 32 or char in '/\\:*?"<>|' for char in name)
            or re.match(r'^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', name, re.I)):
        raise DownloadError('unsafe_filename', 'expected_name must be one plain safe filename, without paths, devices, alternate streams or control characters.')
    result = {'expected_name': name}
    text = args.get('link_text')
    if text is not None:
        if not isinstance(text, str) or not text.strip() or len(text) > 300 or any(ord(c) < 32 for c in text):
            raise DownloadError('invalid_arguments', 'link_text must be a nonempty short exact visible label.')
        result['link_text'] = text.strip()
    digest = args.get('expected_sha256')
    if digest is not None:
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
            raise DownloadError('invalid_arguments', 'expected_sha256 must be a complete SHA-256 hexadecimal digest.')
        result['expected_sha256'] = digest.lower()
    return result


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


_SETTINGS = r"""() => {
  const elements=[], texts=[];
  const walk=root=>{
    for(const child of root.childNodes||[]){
      if(child.nodeType===Node.TEXT_NODE){const value=(child.nodeValue||'').trim();if(value)texts.push(value);}
      if(child.nodeType===Node.ELEMENT_NODE){elements.push(child);walk(child);if(child.shadowRoot)walk(child.shadowRoot);}
    }
  };
  walk(document);
  const paths=[...new Set(texts.filter(t=>/^(?:[a-z]:\\|\\\\)[^\r\n]+$/i.test(t)))];
  const toggles=elements.filter(n=>n.tagName==='SETTINGS-TOGGLE-BUTTON').map(n=>({
    label:String(n.label||n.getAttribute('aria-label')||n.innerText||n.shadowRoot?.textContent||'').replace(/\s+/g,' ').trim().slice(0,350),
    pref_key:typeof n.pref?.key==='string'?n.pref.key:'',
    checked:typeof n.checked==='boolean'?n.checked:(typeof n.pref?.value==='boolean'?n.pref.value:null)
  }));
  return {paths,toggles};
}"""

_ANCHORS = r"""params => {
  const state=window.__copilotLocalAgentNodes||(window.__copilotLocalAgentNodes={ids:new WeakMap(),next:1});
  const id=n=>{if(!state.ids.has(n))state.ids.set(n,state.next++);return state.ids.get(n);};
  const userSelector='[data-testid="chatQuestion"],.fai-UserMessage,[aria-labelledby^="user-message-"],[data-testid*="userChatMessage" i],[data-testid*="user-message" i],[role="article"][data-author="user"]';
  const assistantSelector='[data-testid="markdown-reply"],.fai-CopilotMessage__content,[data-testid="copilot-message-reply-div"],[data-testid="copilot-message-div"],[data-testid="lastChatMessage"],[data-author="assistant"],[data-message-author-role="assistant"]';
  let nodes=[...document.querySelectorAll(userSelector+','+assistantSelector)].filter(n=>!n.closest('[contenteditable="true"],textarea')&&n.getAttribute('data-message-type')!=='Progress');
  nodes=nodes.filter(n=>!nodes.some(other=>other!==n&&n.contains(other)));
  nodes.sort((a,b)=>(a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING)?-1:1);
  const users=nodes.filter(n=>n.matches(userSelector)||n.closest(userSelector));
  const matching=users.filter(n=>(n.innerText||n.textContent||'').includes(params.request_id));
  if(matching.length!==1||users[users.length-1]!==matching[0])return {error:'source_anchor_unavailable'};
  const user=matching[0], userIndex=nodes.indexOf(user);
  let replies=nodes.filter((n,index)=>index>userIndex&&!(n.matches(userSelector)||n.closest(userSelector)));
  if(params.assistant_key!=null)replies=replies.filter(n=>id(n)===params.assistant_key);
  else replies=replies.filter(n=>(n.innerText||n.textContent||'').includes(params.request_id));
  if(replies.length!==1)return {error:'assistant_anchor_unavailable'};
  const assistant=replies[0], all=[...document.querySelectorAll('a[href]')];
  const links=[...assistant.querySelectorAll('a[href]')].filter(n=>n.offsetWidth||n.offsetHeight||n.getClientRects().length).map(n=>({
    key:id(n), index:all.indexOf(n), href:n.href, raw_href:n.getAttribute('href'),
    label:(n.innerText||n.textContent||n.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim(),
    enabled:n.getAttribute('aria-disabled')!=='true', download:n.getAttribute('download')
  }));
  return {user_key:id(user),assistant_key:id(assistant),links};
}"""


@dataclass
class _Ticket:
    args: dict
    preview: dict
    raw_url: str
    handle: object
    page: object
    source: dict
    used: bool = False


class DownloadService:
    def __init__(self, browser, config, policy, session_dir):
        self.browser, self.config, self.policy = browser, config, policy
        self.session_dir = Path(session_dir)
        self._tickets = {}
        self.feedback = print

    def _config(self, key, default):
        return self.config.get(key, default) if isinstance(self.config, dict) else getattr(self.config, key, default)

    def _source(self, request_id):
        anchor = getattr(self.browser, '_exchange_anchor', None)
        trusted_exchange = isinstance(anchor, dict)
        anchor = anchor if trusted_exchange else getattr(self.browser, 'last_submission', None)
        if (not isinstance(anchor, dict) or anchor.get('request_id') != request_id
                or anchor.get('committed') is False
                or (not trusted_exchange and anchor.get('committed') is not True)):
            raise DownloadError('stale_source', 'The requested download is not bound to the current committed Copilot request.')
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise DownloadError('stale_source', 'A current source request identity is required.')
        return {'request_id': request_id, 'user_key':anchor.get('user_key'), 'assistant_key':anchor.get('assistant_key')}

    def _url(self, url, artifact=None, expected_name=None, bound_url=None):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise DownloadError('unsupported_link', 'The assistant link is not a valid supported HTTPS URL.') from exc
        hosts = self._config('copilot_download_hosts', ['eu-prod.asyncgw.teams.microsoft.com', 'm365.cloud.microsoft'])
        if parsed.scheme == 'blob':
            try:
                inner = urlsplit(parsed.path)
                page_origin = urlsplit(getattr(self.browser.page, 'url', ''))
                native = (inner.scheme == 'https' and inner.hostname == 'm365.cloud.microsoft'
                          and page_origin.scheme == 'https' and page_origin.hostname == inner.hostname
                          and page_origin.port in (None,443) and not page_origin.username and not page_origin.password
                          and inner.hostname in set(hosts) and inner.port in (None,443)
                          and not inner.username and not inner.password and not inner.query and not inner.fragment
                          and not parsed.query and not parsed.fragment
                          and re.fullmatch(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', inner.path, re.I)
                          and isinstance(artifact, dict) and artifact.get('download') == expected_name
                          and bool(expected_name) and (bound_url is None or url == bound_url))
            except (TypeError, ValueError):
                native = False
            if not native:
                raise DownloadError('unsupported_link', 'Native artifacts require a current Microsoft 365 HTTPS page, same-origin UUID blob and an exact matching download filename.')
            return inner
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.hostname.lower() not in set(hosts)
                or parsed.username or parsed.password or port not in (None,443)):
            raise DownloadError('unsupported_link', 'Only a real HTTPS assistant link on an explicitly supported download host is usable; sandbox links and plaintext paths are unavailable.')
        return parsed

    async def _notify(self, message, request_id):
        if callable(getattr(self.browser, '_feedback', None)):
            await self.browser._feedback({'type':'generation', 'request_id':request_id, 'message':message})
            return
        result = self.feedback('[System] ' + message)
        if inspect.isawaitable(result):
            await result

    async def _links(self, source):
        try:
            result = await asyncio.wait_for(self.browser.page.evaluate(_ANCHORS, source), 5)
        except Exception as exc:
            raise DownloadError('link_unavailable', 'Could not inspect the current assistant download link safely.') from exc
        if result.get('error'):
            raise DownloadError('link_unavailable', 'The current assistant reply cannot be uniquely correlated with its source request.')
        return result

    async def _settings(self):
        page = None
        try:
            page = await asyncio.wait_for(self.browser.context.new_page(), 5)
            await page.goto('edge://settings/downloads', wait_until='domcontentloaded', timeout=10000)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                data = await asyncio.wait_for(page.evaluate(_SETTINGS), min(3, deadline-time.monotonic()))
                if len(data.get('paths', [])) == 1:
                    prompt = [item for item in data.get('toggles', []) if
                              'prompt_for_download' in item.get('pref_key','') or
                              re.search(r'ask.*(?:where|what).*download|ask.*save|save.*before.*download', item.get('label',''), re.I)]
                    checked = prompt[0].get('checked') if len(prompt) == 1 else None
                    return {'source':'observed_edge_settings_ui', 'configured_directory':data['paths'][0],
                            'ask_before_download':checked, 'toggles':data.get('toggles', []),
                            'preferences_changed':False}
                await asyncio.sleep(.2)
            raise DownloadError('settings_unavailable', 'Edge download location was not uniquely readable from its actual settings UI.')
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError('settings_unavailable', 'Could not inspect Edge download settings; no preference was changed.') from exc
        finally:
            if page is not None:
                try:
                    await asyncio.wait_for(page.close(), 3)
                except Exception:
                    pass

    async def prepare(self, args, source_request_id):
        if len(self._tickets) >= 50:
            completed = next((key for key,value in self._tickets.items() if value.used), None)
            if completed:
                self._tickets.pop(completed)
            else:
                raise DownloadError('ticket_limit', 'Fifty unused approval previews are already pending; resolve an existing preview before preparing another.')
        args = validate_download_args(args)
        settings = await self._settings()
        await self._notify('Observed Edge download location: '+settings['configured_directory']+'. Preferences remain unchanged. Approved permanent delivery will be retained in the selected OneDrive storage.', source_request_id)
        source = self._source(source_request_id)
        observed = await self._links(source)
        links = [item for item in observed['links'] if item.get('enabled', True)]
        if 'link_text' in args:
            links = [item for item in links if item['label'] == args['link_text']]
        if len(links) != 1:
            raise DownloadError('link_unavailable', 'A unique real assistant download anchor is required. Supply an exact link_text when several links exist.')
        link = links[0]
        parsed = self._url(link['href'], link, args['expected_name'])
        raw = link.get('raw_href') or ''
        if not raw.strip() or raw.startswith('#') or raw.lower().startswith(('sandbox:', 'file:', 'javascript:', 'data:')):
            raise DownloadError('unsupported_link', 'The visible link is not a real supported HTTPS download.')
        roots = getattr(self.policy, 'roots', None)
        if not roots:
            raise DownloadError('destination_forbidden', 'A configured allowed workspace root is required for reviewed delivery.')
        ticket_id = uuid.uuid4().hex
        storage = self._config('storage_dir', None)
        destination = self.policy.resolve(Path(storage if storage else roots[0]) / 'deliveries' / ticket_id / args['expected_name'])
        locator = self.browser.page.locator('a[href]').nth(link['index'])
        handle = await locator.element_handle()
        if handle is None or await handle.evaluate('n => n.href') != link['href']:
            raise DownloadError('link_changed', 'The assistant link changed while preparing its approval preview.')
        preview = {'action':'copilot.download', 'ticket_id':ticket_id, 'source_request_id':source_request_id,
                   'href_sha256':hashlib.sha256(link['href'].encode()).hexdigest(),
                   'source_host':parsed.hostname, 'source_path':parsed.path[:500],
                   'source_scheme':urlsplit(link['href']).scheme,
                   'expected_name':args['expected_name'], 'expected_sha256':args.get('expected_sha256'),
                   'settings':settings, 'destination':str(destination),
                   'configured_default_destination':str(Path(settings['configured_directory']) / args['expected_name']),
                   'save_method':'Exclusive copy of completed browser artifact; event save_as only when native prompting is proven disabled and original path is unavailable',
                   'default_directory_save_proven':False,
                   'max_bytes':int(self._config('max_download_bytes',20*1024*1024)),
                   'timeout_seconds':float(self._config('download_timeout',90))}
        bound_source = {**source, 'assistant_key':observed['assistant_key'], 'user_key':observed['user_key'], 'link_key':link['key']}
        self._tickets[ticket_id] = _Ticket(copy.deepcopy(args), copy.deepcopy(preview), link['href'], handle, self.browser.page, bound_source)
        return copy.deepcopy(preview)

    async def download(self, args, binding):
        args = validate_download_args(args)
        if not isinstance(binding, dict):
            raise DownloadError('binding_invalid', 'An approved prepared download binding is required.')
        ticket = self._tickets.get(binding.get('ticket_id'))
        try:
            matches = ticket is not None and _canonical(binding) == _canonical(ticket.preview)
        except (TypeError, ValueError):
            matches = False
        if ticket is None or ticket.used or not matches or args != ticket.args:
            raise DownloadError('binding_invalid', 'Download approval does not match an unused immutable prepared ticket.')
        if self.browser.page is not ticket.page:
            raise DownloadError('stale_source', 'The prepared Copilot page was replaced; prepare a fresh preview.')
        self._source(ticket.source['request_id'])
        observed = await self._links(ticket.source)
        same = [item for item in observed['links'] if item['key']==ticket.source['link_key'] and item['href']==ticket.raw_url]
        if len(same) != 1 or await ticket.handle.evaluate('n => n.href') != ticket.raw_url:
            raise DownloadError('link_changed', 'The approved assistant link changed; no click was attempted.')
        self._url(same[0]['href'], same[0], args['expected_name'], ticket.raw_url)
        settings = await self._settings()
        if _canonical(settings) != _canonical(ticket.preview['settings']):
            raise DownloadError('settings_changed', 'Edge download settings changed after the preview; prepare and approve again.')
        if settings['ask_before_download'] is not False:
            message = ('Edge may ask you to choose Save or complete its native Save As window. Complete that browser UI yourself; download settings will not be changed. The approved OneDrive staging destination is: '+ticket.preview['destination'])
            await self._notify(message, ticket.source['request_id'])
        destination = self.policy.resolve(ticket.preview['destination'])
        if str(destination) != ticket.preview['destination'] or destination.exists() or destination.parent.exists():
            raise DownloadError('destination_changed', 'The reviewed unique staging destination already exists or changed; no overwrite is permitted.')
        destination.parent.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(exist_ok=False)
        if self.policy.resolve(destination) != destination:
            raise DownloadError('destination_changed', 'The staging path changed before the approved action.')
        ticket.used = True
        clicked = False
        try:
            timeout = ticket.preview['timeout_seconds']
            async with ticket.page.expect_download(timeout=int(timeout*1000)) as pending:
                clicked = True
                await ticket.handle.click(timeout=5000)
            item = await asyncio.wait_for(pending.value, timeout)
            if ticket.raw_url.startswith('blob:') and item.url != ticket.raw_url:
                raise DownloadError('event_source_mismatch', 'The actual native download event does not match the approved artifact control.', True)
            self._url(item.url, {'download':item.suggested_filename}, args['expected_name'], ticket.raw_url if ticket.raw_url.startswith('blob:') else None)
            if item.suggested_filename != args['expected_name']:
                raise DownloadError('filename_mismatch', 'The actual download filename differs from the approved expected_name.', True)
            original = None
            try:
                original = Path(await asyncio.wait_for(item.path(), timeout))
                if original.exists() and original.stat().st_size > ticket.preview['max_bytes']:
                    raise DownloadError('size_exceeded', 'The actual downloaded artifact exceeds the reviewed size limit; its original file was preserved.', True)
            except DownloadError:
                raise
            except asyncio.TimeoutError as exc:
                raise DownloadError('native_completion_required', 'The original browser download did not complete within the reviewed timeout. Check native Save As/download UI; no save_as bypass or automatic retry was attempted.', True) from exc
            except Exception as exc:
                if settings['ask_before_download'] is not False:
                    raise DownloadError('native_completion_required', 'Native download completion cannot be proven while Edge may prompt. Complete its native UI manually; no save_as bypass was attempted.', True) from exc
                original = None
            # Unique exclusively created directory; never save over a preexisting file.
            if destination.exists() or self.policy.resolve(destination) != destination:
                raise DownloadError('destination_changed', 'The destination changed before save_as; original artifact preserved.', True)
            if original and original.is_file():
                # Retain the native artifact and create the reviewed delivery exclusively.
                total = 0
                with original.open('rb') as source_handle, destination.open('xb') as output_handle:
                    while True:
                        chunk = source_handle.read(1024*1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > ticket.preview['max_bytes']:
                            raise DownloadError('size_exceeded', 'The artifact grew beyond the approved byte limit during exclusive copy; partial files were preserved.', True)
                        output_handle.write(chunk)
                save_method = 'exclusive copy of completed observed browser artifact to approved OneDrive staging'
            else:
                await asyncio.wait_for(item.save_as(str(destination)), timeout)
                save_method = 'Playwright download event save_as to approved staging destination'
            failure = await asyncio.wait_for(item.failure(), 5)
            if failure:
                raise DownloadError('download_failed', 'Edge reported that this download failed; partial artifacts were preserved.', True)
            size = destination.stat().st_size
            if size <= 0 or size > ticket.preview['max_bytes']:
                raise DownloadError('size_invalid', 'The saved artifact is empty or exceeds the reviewed limit; it was preserved for inspection.', True)
            digest = hashlib.sha256()
            with destination.open('rb') as handle:
                header = handle.read(4)
                digest.update(header)
                for chunk in iter(lambda:handle.read(1024*1024), b''):
                    digest.update(chunk)
            actual = digest.hexdigest()
            if args['expected_name'].lower().endswith('.zip') and header not in (b'PK\x03\x04',b'PK\x05\x06',b'PK\x07\x08'):
                raise DownloadError('archive_invalid', 'The saved ZIP lacks a ZIP signature; it was preserved and not extracted.', True)
            if args.get('expected_sha256') and args['expected_sha256'] != actual:
                raise DownloadError('hash_mismatch', 'The actual artifact SHA-256 differs from the approved expected hash; it was preserved.', True)
            try:
                self.policy.resolve(destination, must_exist=True)
                validation = verify_file(destination, {'max_file_bytes':min(ticket.preview['max_bytes'],20*1024*1024)})
            except (ArchiveError, ValueError, OSError) as exc:
                raise DownloadError('artifact_invalid', 'The saved artifact failed bounded static format/readability validation. It was preserved and no Python or Office content was executed.', True) from exc
            if validation['sha256'] != actual or validation['size'] != size:
                raise DownloadError('artifact_changed', 'The delivered artifact changed during verification; all observed artifacts were preserved.', True)
            default_match = bool(original and original.exists() and os.path.normcase(str(original.parent.resolve())) == os.path.normcase(str(Path(settings['configured_directory']).resolve())))
            return {'status':'verified' if args.get('expected_sha256') else 'downloaded',
                    'path':str(destination), 'size':size, 'sha256':actual,
                    'download_event_observed':True, 'source_request_id':ticket.source['request_id'],
                    'href_sha256':ticket.preview['href_sha256'], 'suggested_filename':item.suggested_filename,
                    'settings':settings, 'save_method':save_method,
                    'default_directory_save_proven':default_match,
                    'original_browser_artifact':{'path':str(original) if original else None, 'retained':bool(original and original.exists())},
                    'archive_signature_verified':args['expected_name'].lower().endswith('.zip'),
                    'artifact_validation':validation,
                    'expected_hash_verified':bool(args.get('expected_sha256')),
                    'side_effects_uncertain':False}
        except DownloadError as exc:
            if clicked:
                exc.side_effects_uncertain = True
            raise
        except Exception as exc:
            raise DownloadError('download_uncertain' if clicked else 'download_unavailable',
                                'Download did not complete through the observed browser event. Native prompts, missing events, or a failed transfer require user inspection; no files were deleted.', clicked) from exc
