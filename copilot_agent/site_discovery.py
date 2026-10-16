"""Resumable, evidence-first discovery on the existing owned website page."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from io import BytesIO
from PIL import Image
from urllib.parse import urlsplit

from .browser_inspection import SNAPSHOT
from .local_crawler import knowledge_root, saved_html
from .persistence import io_path, write_json
from .screenshot_evidence import _pdf, MASK, METRICS
from .policy import PolicyError, config_value
from .web_navigation import get_navigation_page, _install_origin_guard, safe_url
from .knowledge_views import evidence_folder, website_storage_root

UNSAFE_CONTROL = re.compile(
    r'delete|remove|destroy|sign.?out|log.?out|submit|save|purchase|confirm|'
    r'eliminar|borrar|guardar|enviar|confirmar|cerrar[\s_/-]*sesi[oó]n|'
    r'(?:cambiar|change).{0,20}(?:correo|email|contrase[nñ]a|password)', re.I)

SPEC = ({'type': 'object', 'properties': {
    'title': {'type': 'string', 'minLength': 1, 'maxLength': 120},
    'tab_id': {'type': 'string'},
    'max_states': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'max_seconds': {'type': 'integer', 'minimum': 5, 'maximum': 1800},
    'explore': {'type': 'boolean'},
    'resume': {'type': 'boolean'},
}, 'required': ['title'], 'additionalProperties': False}, 'user_approval',
    'Discover an owned signed-in website in one resumable local campaign. Capture HTML, DOM, accessibility, frames, delivered scripts, images, network and labeled screenshot PDF; explore navigation controls automatically. Save indexed shared knowledge and attach evidence within the whole-message file budget. Partial captures and unresolved transitions are explicit. Login remains manual; delete/sign-out/submit controls are not exploration candidates.')

INVENTORY = r'''() => ({scripts:[...document.scripts].map(s=>({url:s.src,type:s.type,source:s.src?null:s.textContent})),images:[...document.images].map(n=>({url:n.currentSrc||n.src,alt:n.alt,width:n.naturalWidth,height:n.naturalHeight})),styles:[...document.styleSheets].map(s=>({url:s.href})),controls:[...document.querySelectorAll('a[href],nav button,[role=navigation] button,[role=tab],[aria-expanded],summary')].map(n=>({label:(n.getAttribute('aria-label')||n.innerText||'').slice(0,200),role:n.getAttribute('role'),href:n.href||null,expanded:n.getAttribute('aria-expanded'),tag:n.tagName,type:n.getAttribute('type')}))})'''

SOURCES = r'''async () => {
 const urls=[...new Set([...document.scripts].map(n=>n.src).concat([...document.styleSheets].map(n=>n.href)).filter(Boolean))];
 const results=[];
 for(let i=0;i<Math.min(urls.length,24);i+=4){
  results.push(...await Promise.all(urls.slice(i,i+4).map(async url=>{
   try {const response=await fetch(url,{signal:AbortSignal.timeout(2500)});if(!response.ok)return {url,status:response.status};
    const reader=response.body.getReader(), decoder=new TextDecoder();let source='',bytes=0;
    while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>1048576){await reader.cancel();return {url,status:'size_limit',bytes};}source+=decoder.decode(value,{stream:true});}
    return {url,status:'captured',source:source+decoder.decode(),bytes};
   }catch(error){return {url,status:'unavailable',error:String(error).slice(0,200)};}
  })));
 }
 return {resources:results,total:urls.length,limit:24,limited:urls.length>24};
}'''


async def settle(page, deadline, events):
    """Observe transient errors instead of treating their first appearance as final."""
    previous = None
    stable = 0
    while time.monotonic() < deadline:
        try:
            state = await page.evaluate("() => ({url:location.href,ready:document.readyState,text:(document.body?.innerText||'').slice(0,2000)})")
            fingerprint = json.dumps(state, sort_keys=True)
            stable = stable + 1 if fingerprint == previous else 0
            previous = fingerprint
            error = bool(re.search(r'internal server error|bad gateway|service unavailable', state['text'], re.I))
            events.append({'at': time.time(), 'url': state['url'], 'error_page': error})
            if stable >= 3 and state['ready'] != 'loading' and not error:
                return {'outcome': 'stable', 'url': state['url']}
        except Exception as exc:
            events.append({'at': time.time(), 'observation_error': type(exc).__name__})
        await asyncio.sleep(.4)
    return {'outcome': 'unresolved', 'url': page.url}


def attachment_slots(pending):
    # Reserve room for the orchestrator's result envelope as well as UI headroom.
    return max(0, 18 - len(pending))


async def discover(args, context):
    from .automatic_visuals import paired_browser_action
    if not context.get('approved'):
        raise PolicyError('Current session authorization is required for discovery.')
    page = get_navigation_page(context, args.get('tab_id'))
    compact = config_value(context.get('config', {}), 'compact_navigation', False) is True
    await _install_origin_guard(page, context, page.url)
    start_url = page.url
    folder = evidence_folder(context, start_url, 'browser',
                             root=website_storage_root(knowledge_root(context['config'])))
    io_path(folder).mkdir(parents=True, exist_ok=True)
    checkpoint = folder / 'checkpoint.json'
    data = {'states': [], 'actions': [], 'network': [], 'gaps': [], 'attempted': [],
            'evidence_kind': 'raw_task_evidence_not_reusable_knowledge'}
    if args.get('resume', True) and io_path(checkpoint).exists():
        data = json.loads(io_path(checkpoint).read_text(encoding='utf-8'))
    data.setdefault('frontier', [])
    deadline = time.monotonic() + args.get('max_seconds', 90)
    pending_bodies = set()
    pictures = []
    pixels = None
    resource_bytes = 0
    async def response_body(response, record):
        nonlocal resource_bytes
        if response.request.resource_type not in {'script', 'stylesheet', 'xhr', 'fetch'}:
            return
        try:
            size = int(response.headers.get('content-length', '0'))
            if size > 1024 * 1024 or resource_bytes >= 8 * 1024 * 1024:
                record['body_status'] = 'budget_exceeded'
                return
            body = await response.body()
            resource_bytes += len(body)
            if len(body) <= 1024 * 1024 and resource_bytes <= 8 * 1024 * 1024:
                record['body'] = body.decode('utf-8', errors='replace')
                record['body_status'] = 'captured'
            else:
                record['body_status'] = 'budget_exceeded'
        except Exception as exc:
            record['body_status'] = type(exc).__name__
    def on_response(response):
        if len(data['network']) >= 1000:
            return
        record = {'url': response.url, 'status': response.status,
                  'method': response.request.method, 'state': len(data['states']), 'body_status': 'not_requested'}
        data['network'].append(record)
        task = asyncio.create_task(response_body(response, record))
        pending_bodies.add(task)
        task.add_done_callback(pending_bodies.discard)
    page.on('response', on_response)
    try:
        for iteration in range(args.get('max_states', 12)):
            if time.monotonic() >= deadline or context.get('cancel_event') and context['cancel_event'].is_set():
                break
            timeline = []
            outcome = await settle(page, min(deadline, time.monotonic() + 12), timeline)
            state = {'id': len(data['states']), 'url': page.url, 'frames': [], 'timeline': timeline, 'settling': outcome}
            pixels = asyncio.create_task(page.screenshot(type='png', scale='css', timeout=10000, mask=[page.locator(MASK)]))
            for frame in list(page.frames):
                async def collect(frame=frame):
                    values = await asyncio.gather(frame.content(), frame.evaluate(SNAPSHOT, {'maxNodes': 2000}),
                        frame.evaluate(INVENTORY), frame.locator('body').aria_snapshot(),
                        frame.evaluate('() => ({mode:"compact", limitation:"Additional script/CSS fetches deferred; observed network bodies retained separately."})')
                        if compact else frame.evaluate(SOURCES), return_exceptions=True)
                    result = {'url': frame.url}
                    for name, value in zip(('html', 'dom', 'resources', 'accessibility', 'delivered_sources'), values):
                        if isinstance(value, BaseException):
                            result[name + '_error'] = type(value).__name__
                            data['gaps'].append({'state': state['id'], 'frame': frame.url, 'collector': name})
                        else:
                            result[name] = saved_html(value) if name == 'html' else value
                    return result
                try:
                    state['frames'].append(await asyncio.wait_for(collect(), max(.1, min(15, deadline-time.monotonic()))))
                except Exception as exc:
                    data['gaps'].append({'state': state['id'], 'frame': frame.url, 'error': type(exc).__name__})
            try:
                raw = await pixels
                metrics = await page.evaluate(METRICS)
                if page.url == state['url']:
                    viewport = folder / ('state-' + str(state['id']) + '-' + uuid.uuid4().hex + '-viewport.png')
                    with io_path(viewport).open('xb') as handle:
                        handle.write(raw)
                    state['viewport'] = {'path': str(viewport), 'bytes': len(raw),
                                         'sha256': hashlib.sha256(raw).hexdigest()}
                    with Image.open(BytesIO(raw)) as source:
                        image = source.convert('RGB')
                    if len(pictures) < 12:
                        pictures.append(({'number': len(pictures)+1, 'requested_total': 0,
                            'label': 'State '+str(state['id']), 'url': page.url,
                            'scroll': {'x': metrics['x'], 'y': metrics['y']}, 'kind': 'viewport'}, image))
                    else:
                        image.close()
                        data['gaps'].append({'state': state['id'], 'collector': 'visual_packet',
                            'error': 'Twelve-picture PDF sample limit; full viewport retained locally',
                            'viewport': str(viewport)})
                    if state['id'] == 0 and len(pictures) <= 10:
                        for caption, box in [('upper navigation and controls closeup', (0, 0, image.width, max(1, image.height//2))),
                                             ('lower content and controls closeup', (0, image.height//2, image.width, image.height))]:
                            pictures.append(({'number': len(pictures)+1, 'requested_total': 0,
                                'label': 'State 0 '+caption, 'url': page.url,
                                'scroll': {'x': metrics['x'], 'y': metrics['y']}, 'kind': 'closeup'}, image.crop(box)))
                else:
                    data['gaps'].append({'state': state['id'], 'collector': 'visual_consistency', 'error': 'Page changed during paired capture'})
            except Exception as exc:
                data['gaps'].append({'state': state['id'], 'collector': 'screenshots', 'error': type(exc).__name__})
            finally:
                if not pixels.done():
                    pixels.cancel()
                    await asyncio.gather(pixels, return_exceptions=True)
            # Reveal lazy/virtualized content and preserve each sampled DOM, not just the final scroll.
            if len(pictures) < 12 and time.monotonic() < deadline:
                original = await page.evaluate(METRICS)
                state['scroll_samples'] = []
                try:
                    for y in sorted({round(original['maxY']/2), original['maxY']} - {original['y']}):
                        if len(pictures) >= 12 or time.monotonic() >= deadline or page.url != state['url']:
                            break
                        await paired_browser_action(page, context, 'browser.discover scroll sample',
                            lambda: page.evaluate('(y)=>window.scrollTo({top:y,behavior:"instant"})', y))
                        await asyncio.sleep(.15)
                        raw, dom = await asyncio.gather(page.screenshot(type='png', scale='css', timeout=5000, mask=[page.locator(MASK)]), page.evaluate(SNAPSHOT, {'maxNodes': 2000}))
                        state['scroll_samples'].append({'y': y, 'dom': dom})
                        with Image.open(BytesIO(raw)) as source:
                            pictures.append(({'number': len(pictures)+1, 'requested_total': 0, 'label': 'State '+str(state['id'])+' scroll sample', 'url': page.url, 'scroll': {'x': original['x'], 'y': y}, 'kind': 'viewport'}, source.convert('RGB')))
                except Exception as exc:
                    data['gaps'].append({'state': state['id'], 'collector': 'scroll_samples', 'error': type(exc).__name__})
                finally:
                    if page.url == state['url']:
                        await paired_browser_action(page, context, 'browser.discover restore scroll',
                            lambda: page.evaluate('(p)=>window.scrollTo(p.x,p.y)', original))
            data['states'].append(state)
            for frame_state in state['frames']:
                for node in frame_state.get('resources', {}).get('controls', []):
                    href = node.get('href')
                    if (str(node.get('tag', '')).lower() == 'a' and href and href not in data['frontier']
                            and not UNSAFE_CONTROL.search(str(node.get('label', '')) + ' ' + href)):
                        data['frontier'].append(href)
            if data['actions'] and data['actions'][-1]['status'] in {'clicked_not_yet_verified', 'click_failed_observe'}:
                data['actions'][-1].update(to_state=state['id'], observed_outcome=outcome)
            write_json(checkpoint, data)
            if (not args.get('explore', True) or outcome['outcome'] != 'stable' or not state.get('viewport')
                    or iteration + 1 >= args.get('max_states', 12) or deadline-time.monotonic() < 5):
                break
            acted = False
            for frame in list(page.frames):
                controls = frame.locator('nav a,nav button,[role=navigation] a,[role=navigation] button,[role=tab],[aria-expanded],summary')
                for index in range(min(await controls.count(), 200)):
                    control = controls.nth(index)
                    try:
                        label = (await control.inner_text(timeout=700))[:200]
                        label = label or (await control.get_attribute('aria-label', timeout=700) or '')[:200]
                        href = await control.get_attribute('href', timeout=700)
                        kind = await control.get_attribute('type', timeout=700)
                        signature = json.dumps([page.url, frame.url, index, label, href])
                        if signature in data['attempted']:
                            continue
                        data['attempted'].append(signature)
                        if kind == 'submit' or UNSAFE_CONTROL.search(label+' '+(href or '')):
                            continue
                        if not await control.is_visible() or not await control.is_enabled():
                            continue
                        data['actions'].append({'from_state': state['id'], 'frame': frame.url, 'index': index, 'label': label, 'href': href, 'status': 'started'})
                        write_json(checkpoint, data)
                        await _install_origin_guard(page, context, page.url)
                        await paired_browser_action(page, context, 'browser.discover navigation click',
                            lambda: control.click(timeout=3000))
                        data['actions'][-1]['status'] = 'clicked_not_yet_verified'
                        acted = True
                        break
                    except Exception as exc:
                        if data['actions'] and data['actions'][-1]['status'] == 'started':
                            data['actions'][-1]['status'] = 'click_failed_observe'
                        data['gaps'].append({'state': state['id'], 'control': index, 'error': type(exc).__name__, 'retry': 'observe before retry'})
                        # A failed click can have effects: return to observation first.
                        acted = True
                        break
                if acted:
                    break
            if not acted:
                visited = {item['url'] for item in data['states']}
                while data['frontier'] and data['frontier'][0] in visited:
                    data['frontier'].pop(0)
                if not data['frontier']:
                    break
                destination = data['frontier'].pop(0)
                data['actions'].append({'from_state': state['id'], 'href': destination, 'status': 'started', 'kind': 'frontier_navigation'})
                write_json(checkpoint, data)
                try:
                    from .session_mode import website_policy
                    website_policy(context['config'], context.get('approved_domains', [])).resolve(destination)
                    await paired_browser_action(page, context, 'browser.discover navigate',
                        lambda: page.goto(destination, wait_until='domcontentloaded', timeout=10000))
                    data['actions'][-1]['status'] = 'clicked_not_yet_verified'
                except Exception as exc:
                    data['actions'][-1]['status'] = 'click_failed_observe'
                    data['gaps'].append({'url': destination, 'collector': 'frontier_navigation', 'error': type(exc).__name__})
        if pending_bodies:
            done, outstanding = await asyncio.wait(pending_bodies, timeout=2)
            for task in outstanding:
                task.cancel()
            await asyncio.gather(*outstanding, return_exceptions=True)
        data['gaps'].append({'limitation': 'Only revealed states and open shadow roots captured; resource bodies observed during this run only. Routes require independent replay before tool generation.'})
        write_json(checkpoint, data)
        files = []
        sections = {'01-COVERAGE': {'gaps': data['gaps'], 'states': len(data['states']), 'actions': data['actions']},
                    '02-PAGE-EVIDENCE': data['states'], '03-NETWORK-AND-SOURCES': data['network']}
        for name, value in sections.items():
            serialized = json.dumps(value, ensure_ascii=False)
            if len(serialized.encode('utf-8')) <= 7*1024*1024:
                path = folder / (name + '.json')
                write_json(path, value)
                files.append(path)
            else:
                pieces = [serialized[i:i+500000] for i in range(0, len(serialized), 500000)]
                for number, content in enumerate(pieces, 1):
                    path = folder / (name + '-part-' + str(number) + '.json')
                    write_json(path, {'section': name, 'part': number, 'parts': len(pieces), 'content': content,
                                      'reading': 'Concatenate content fields in part order to reconstruct section JSON.'})
                    files.append(path)
        guide = folder / '00-READ-FIRST.md'
        io_path(guide).write_text('# '+args['title']+'\n\nRead coverage first, then scoped task evidence (HTML, DOM, accessibility, scripts/images), then network sources. These captures are not sanitized reusable knowledge.\n\nTask evidence checkpoint: '+str(checkpoint)+'\nNavigation actions are observations, not replay-verified automation tools.\n', encoding='utf-8')
        files.insert(0, guide)
        attachments = context.setdefault('pending_file_attachments', [])
        reserved_images = len(context.get('pending_image_attachments', [])) + max(1, len(context.get('pending_visual_attachments', [])))
        visual = None
        if pictures:
            for record, _ in pictures:
                record['requested_total'] = len(pictures)
            pdf = folder / '04-VISUAL-EVIDENCE.pdf'
            saving = asyncio.create_task(asyncio.to_thread(_pdf, pictures, pdf))
            try:
                await asyncio.shield(saving)
            except asyncio.CancelledError:
                await saving
                raise
            from .automatic_visuals import merge_visual_pages
            try:
                visual = await merge_visual_pages(pictures, context)
                visual['discovery_artifact_path'] = str(pdf)
            except asyncio.CancelledError:
                raise
            except Exception:
                visual = {'path': str(pdf), 'pictures': len(pictures), 'queued_for_copilot': False,
                          'status': 'unavailable', 'note': 'Visual merge failed; discovery PDF retained locally.'}
                data['gaps'].append({'collector': 'visual_attachment', 'error': 'Unable to queue merged visual context'})
        manifest = []
        for path in files:
            payload = io_path(path).read_bytes()
            manifest.append({'path': str(path), 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'attached': False})
            byte_limit = (20 if path.suffix == '.pdf' else 8) * 1024 * 1024
            if not compact and len(payload) <= byte_limit and attachment_slots(attachments + [None]*reserved_images):
                attachments.append(str(path))
                manifest[-1]['attached'] = True
        for state in data['states']:
            if state.get('viewport'):
                manifest.append({**state['viewport'], 'state': state['id'], 'attached': False,
                                 'purpose': 'Full per-state viewport; PDF is a bounded sample'})
        write_json(folder / 'manifest.json', manifest)
        write_json(checkpoint, data)
        uncertain = bool(data['actions'] and 'to_state' not in data['actions'][-1])
        coverage = {'routes': sorted({safe_url(item['url']) for item in data['states']}),
                    'frontier': sorted({safe_url(url) for url in data['frontier']
                                       if url not in {item['url'] for item in data['states']}}),
                    'states': [{'id': item['id'], 'url': safe_url(item['url']),
                                'settling': item['settling'], 'viewport': item.get('viewport'),
                                'forms': [form for frame in item['frames']
                                          for form in frame.get('dom', {}).get('application', {}).get('forms', [])]}
                               for item in data['states']],
                    'limitations': ['Observed safe frontier only; dynamic/deep states and server implementation are not proven complete.',
                                    'PDF is sampled; per-state viewports are in the local manifest.',
                                    'Additional source fetching is deferred in compact mode.' if compact else 'Source capture is bounded.']}
        if compact:
            write_json(folder / '00-COVERAGE-SUMMARY.json', coverage)
        return {'status': 'uncertain' if uncertain else 'partial', 'knowledge_directory': str(folder), 'checkpoint': str(checkpoint),
                'evidence_kind': 'raw_task_evidence_not_reusable_knowledge',
                'states_captured': len(data['states']), 'actions': len(data['actions']),
                'files': [] if compact else manifest, 'manifest_path': str(folder / 'manifest.json'),
                'compact': compact, 'coverage': coverage if compact else None,
                'visual': visual, 'gaps': data['gaps'], 'side_effects_uncertain': uncertain,
                'next_action': 'Read attached evidence and coverage. Resume browser.discover for untried controls; independently replay routes before generating tools.'}
    finally:
        page.remove_listener('response', on_response)
        if pixels is not None and not pixels.done():
            pixels.cancel()
            await asyncio.gather(pixels, return_exceptions=True)
        for _, image in pictures:
            image.close()
        for task in list(pending_bodies):
            task.cancel()
        if pending_bodies:
            await asyncio.gather(*pending_bodies, return_exceptions=True)

