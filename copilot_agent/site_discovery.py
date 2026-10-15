"""Resumable, evidence-first discovery on the existing owned website page."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from io import BytesIO
from PIL import Image
from urllib.parse import urlsplit

from .browser_inspection import SNAPSHOT
from .local_crawler import knowledge_root, saved_html
from .persistence import io_path, write_json
from .screenshot_evidence import _pdf, MASK, METRICS
from .policy import PolicyError
from .web_navigation import get_navigation_page, _install_origin_guard

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
    if not context.get('approved'):
        raise PolicyError('Current session authorization is required for discovery.')
    page = get_navigation_page(context, args.get('tab_id'))
    await _install_origin_guard(page, context, page.url)
    start_url = page.url
    parsed = urlsplit(start_url)
    key = hashlib.sha256((args['title'] + parsed.scheme + '://' + parsed.netloc).encode()).hexdigest()[:16]
    folder = knowledge_root(context['config']) / ('discovery-' + key)
    io_path(folder).mkdir(parents=True, exist_ok=True)
    checkpoint = folder / 'checkpoint.json'
    data = {'states': [], 'actions': [], 'network': [], 'gaps': [], 'attempted': []}
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
                        frame.evaluate(INVENTORY), frame.locator('body').aria_snapshot(), frame.evaluate(SOURCES), return_exceptions=True)
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
                    with Image.open(BytesIO(raw)) as source:
                        image = source.convert('RGB')
                    pictures.append(({'number': len(pictures)+1, 'requested_total': 0,
                        'label': 'State '+str(state['id']), 'url': page.url,
                        'scroll': {'x': metrics['x'], 'y': metrics['y']}, 'kind': 'viewport'}, image))
                else:
                    data['gaps'].append({'state': state['id'], 'collector': 'visual_consistency', 'error': 'Page changed during paired capture'})
            except Exception as exc:
                data['gaps'].append({'state': state['id'], 'collector': 'screenshots', 'error': type(exc).__name__})
            finally:
                if not pixels.done():
                    pixels.cancel()
                    await asyncio.gather(pixels, return_exceptions=True)
            # Reveal lazy/virtualized content and preserve each sampled DOM, not just the final scroll.
            if len(pictures) < 30 and time.monotonic() < deadline:
                original = await page.evaluate(METRICS)
                state['scroll_samples'] = []
                try:
                    for y in sorted({round(original['maxY']/2), original['maxY']} - {original['y']}):
                        if len(pictures) >= 30 or time.monotonic() >= deadline or page.url != state['url']:
                            break
                        await page.evaluate('(y)=>window.scrollTo({top:y,behavior:"instant"})', y)
                        await asyncio.sleep(.15)
                        raw, dom = await asyncio.gather(page.screenshot(type='png', scale='css', timeout=5000, mask=[page.locator(MASK)]), page.evaluate(SNAPSHOT, {'maxNodes': 2000}))
                        state['scroll_samples'].append({'y': y, 'dom': dom})
                        with Image.open(BytesIO(raw)) as source:
                            pictures.append(({'number': len(pictures)+1, 'requested_total': 0, 'label': 'State '+str(state['id'])+' scroll sample', 'url': page.url, 'scroll': {'x': original['x'], 'y': y}, 'kind': 'viewport'}, source.convert('RGB')))
                except Exception as exc:
                    data['gaps'].append({'state': state['id'], 'collector': 'scroll_samples', 'error': type(exc).__name__})
                finally:
                    if page.url == state['url']:
                        await page.evaluate('(p)=>window.scrollTo(p.x,p.y)', original)
            data['states'].append(state)
            for frame_state in state['frames']:
                for node in frame_state.get('resources', {}).get('controls', []):
                    href = node.get('href')
                    if (str(node.get('tag', '')).lower() == 'a' and href and href not in data['frontier']
                            and not re.search(r'delete|destroy|sign.?out|log.?out|remove', href, re.I)):
                        data['frontier'].append(href)
            if data['actions'] and data['actions'][-1]['status'] in {'clicked_not_yet_verified', 'click_failed_observe'}:
                data['actions'][-1].update(to_state=state['id'], observed_outcome=outcome)
            write_json(checkpoint, data)
            if (not args.get('explore', True) or outcome['outcome'] != 'stable'
                    or iteration + 1 >= args.get('max_states', 12) or time.monotonic() >= deadline):
                break
            acted = False
            for frame in list(page.frames):
                controls = frame.locator('nav a,nav button,[role=navigation] a,[role=navigation] button,[role=tab],[aria-expanded],summary')
                for index in range(min(await controls.count(), 200)):
                    control = controls.nth(index)
                    try:
                        label = (await control.inner_text(timeout=700))[:200]
                        href = await control.get_attribute('href', timeout=700)
                        kind = await control.get_attribute('type', timeout=700)
                        signature = json.dumps([page.url, frame.url, index, label, href])
                        if signature in data['attempted']:
                            continue
                        data['attempted'].append(signature)
                        if kind == 'submit' or re.search(r'delete|remove|destroy|sign.?out|log.?out|submit|save|purchase|confirm', label+' '+(href or ''), re.I):
                            continue
                        if not await control.is_visible() or not await control.is_enabled():
                            continue
                        data['actions'].append({'from_state': state['id'], 'frame': frame.url, 'index': index, 'label': label, 'href': href, 'status': 'started'})
                        write_json(checkpoint, data)
                        await _install_origin_guard(page, context, page.url)
                        await control.click(timeout=3000)
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
                    await page.goto(destination, wait_until='domcontentloaded', timeout=10000)
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
        io_path(guide).write_text('# '+args['title']+'\n\nRead coverage first, then page evidence (HTML, DOM, accessibility, scripts/images), then network sources.\n\nKnowledge checkpoint: '+str(checkpoint)+'\nNavigation actions are observations, not replay-verified automation tools.\n', encoding='utf-8')
        files.insert(0, guide)
        attachments = context.setdefault('pending_file_attachments', [])
        reserved_images = len(context.get('pending_image_attachments', []))
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
            files.insert(1, pdf)
            visual = {'path': str(pdf), 'pictures': len(pictures)}
        manifest = []
        for path in files:
            payload = io_path(path).read_bytes()
            manifest.append({'path': str(path), 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'attached': False})
            byte_limit = (20 if path.suffix == '.pdf' else 8) * 1024 * 1024
            if len(payload) <= byte_limit and attachment_slots(attachments + [None]*reserved_images):
                attachments.append(str(path))
                manifest[-1]['attached'] = True
        write_json(folder / 'manifest.json', manifest)
        write_json(checkpoint, data)
        uncertain = bool(data['actions'] and 'to_state' not in data['actions'][-1])
        return {'status': 'uncertain' if uncertain else 'partial', 'knowledge_directory': str(folder), 'checkpoint': str(checkpoint),
                'states_captured': len(data['states']), 'actions': len(data['actions']), 'files': manifest,
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

