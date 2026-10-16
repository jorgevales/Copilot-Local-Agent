"""Automatic, bounded visual companions to website investigations."""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import uuid
from urllib.parse import urlsplit

from PIL import Image

from .persistence import io_path
from .persistence import write_json
from .performance import trace
from .policy import config_value
from .screenshot_evidence import MASK, METRICS, _pdf
from .web_navigation import get_navigation_page, _install_origin_guard, _url_policy, safe_url, _check_cancelled, NavigationStop


MAX_PICTURES = 12
SCROLL_PANEL = """ratio => {let best=null,area=0,seen=0;for(const n of document.querySelectorAll('main,section,div,[role=main],[role=region]')) {
 if(++seen>2000)break;const r=n.getBoundingClientRect();if(n.scrollHeight-n.clientHeight>80&&r.width>150&&r.height>100&&r.bottom>0&&r.top<innerHeight&&r.width*r.height>area){best=n;area=r.width*r.height;}}
 if(!best)return null;const maxY=best.scrollHeight-best.clientHeight;if(ratio!==null)best.scrollTo({top:Math.round(maxY*ratio),behavior:'instant'});
 return {maxY,y:best.scrollTop};}"""
PASSIVE = {'rea.inspect_page', 'rea.analyze_capture', 'rea.analyze_artifact',
           'browser.recon', 'browser.route', 'operation.learn', 'operation.call',
           'discovery.manifest', 'navigation.intent'}
AFTER = {'browser.open', 'browser.back', 'browser.forward', 'browser.plan', 'browser.inspect', 'browser.discover',
         'browser.javascript', 'browser.customer_summary', 'browser.tabs'}


def relevant(name, args):
    return name.startswith('browser.') or name in PASSIVE or name in AFTER


def _collector(context):
    batch = str(context.get('source_request_id') or 'session-batch')
    return context.setdefault('automatic_visual_context', {}).setdefault('batches', {}).setdefault(batch,
        {'lock': asyncio.Lock(), 'records': [], 'gaps': [],
         'target': str(Path(context['session_dir']) / 'screenshots' / (uuid.uuid4().hex + '-automatic.pdf'))})


async def capture_action_phase(page, context, label, phase, action_id):
    """Actual owned-page action evidence; never subject to discovery sampling limits."""
    collector = _collector(context)
    async with collector['lock']:
        try:
            if page is None or page.is_closed():
                raise ValueError('Owned page unavailable')
            if page.url != 'about:blank':
                _url_policy(context).resolve(page.url)
            url = page.url
            captured_at = datetime.now(timezone.utc).isoformat()
            with trace(context).span('screenshot', call_id=context.get('source_call_id')):
                pixels = await page.screenshot(type='png', scale='css', timeout=2500, mask=[page.locator(MASK)])
            if page.url != url:
                raise ValueError('Page navigated during phase capture')
            scroll = {'x': None, 'y': None}
            try:
                metrics = await asyncio.wait_for(page.evaluate(METRICS), .25)
                scroll = {'x': metrics['x'], 'y': metrics['y']}
            except Exception:
                pass
            path = Path(collector['target']).with_name(uuid.uuid4().hex + '.png')
            io_path(path).parent.mkdir(parents=True, exist_ok=True)
            io_path(path).write_bytes(pixels)
            collector['records'].append({'number': len(collector['records']) + 1,
                'label': f'{phase.upper()} {label} | action={action_id} | {captured_at}',
                'phase': phase, 'action_id': action_id, 'source_call_id': context.get('source_call_id'),
                'captured_at': captured_at, 'url': safe_url(url), 'scroll': scroll,
                'kind': 'actual action viewport', 'image_path': str(path)})
            return collector['records'][-1]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            collector['gaps'].append({'source': label, 'phase': phase, 'action_id': action_id,
                'reason': type(error).__name__, 'note': 'Action evidence unavailable; action was not replayed.'})


async def paired_browser_action(page, context, label, operation, *, after_page=None):
    """Bracket one action exactly once; phase failures never replay the operation."""
    action_id = str(context.get('source_call_id') or 'call') + '/' + uuid.uuid4().hex[:12]
    await capture_action_phase(page, context, label, 'before', action_id)
    result = None
    try:
        _check_cancelled(context)
        if context.get('cancel_event') is not None and context['cancel_event'].is_set():
            raise NavigationStop('cancelled', 'User cancellation received during before-action capture')
        with trace(context).span('action', call_id=context.get('source_call_id')):
            result = await operation()
        return result
    finally:
        try:
            target = after_page(result) if after_page is not None else page
        except Exception:
            target = None
        await capture_action_phase(target, context, label, 'after', action_id)


async def flush_visual_context(context):
    # Empty merge writes existing records and queues the complete shared artifact.
    return await merge_visual_pages([], context)


def _source_page(name, args, context):
    page = get_navigation_page(context, args.get('tab_id'))
    if page.url != 'about:blank':
        _url_policy(context).resolve(page.url)
    requested = args.get('origin')
    if requested and (urlsplit(requested).scheme, urlsplit(requested).netloc) != (urlsplit(page.url).scheme, urlsplit(page.url).netloc):
        raise ValueError('No owned visual page matching the investigated origin')
    return page


def _write_bundle(records, target):
    pages = []
    try:
        for record in records:
            with Image.open(io_path(record['image_path'])) as image:
                pages.append(({**record, 'requested_total': len(records)}, image.convert('RGB')))
        _pdf(pages, target)
    finally:
        for _, image in pages:
            image.close()


async def merge_visual_pages(pages, context):
    """Fold an existing paired discovery batch into the same request PDF."""
    holder = context.setdefault('automatic_visual_context', {})
    batch = str(context.get('source_request_id') or 'session-batch')
    collector = holder.setdefault('batches', {}).setdefault(batch,
        {'lock': asyncio.Lock(), 'records': [], 'gaps': [],
         'target': str(Path(context['session_dir']) / 'screenshots' / (uuid.uuid4().hex + '-automatic.pdf'))})
    async with collector['lock']:
        records = collector['records']
        for record, image in pages:
            if len(records) >= MAX_PICTURES:
                collector['gaps'].append({'source': 'browser.discover', 'note': 'Twelve-picture request sample limit reached.'})
                break
            path = Path(collector['target']).with_name(uuid.uuid4().hex + '.png')
            io_path(path).parent.mkdir(parents=True, exist_ok=True)
            image.save(io_path(path), 'PNG')
            records.append({**record, 'number': len(records) + 1, 'image_path': str(path)})
        if not records:
            return {'status': 'unavailable', 'pictures': 0, 'queued_for_copilot': False}
        selected = list(records)
        compact = context.get('navigation_visual_packet', False)
        if compact:
            # The decision capture is coherent with the DOM/fingerprint. The
            # outer AFTER capture can be later and is audit evidence, not a
            # substitute for that observation. Retain every original PNG.
            decisions = [r for r in records if r.get('phase') == 'decision']
            selected = list({r.get('source_call_id'): r for r in decisions}.values()) if decisions else [records[-1]]
            selected = [dict(record, number=index) for index, record in enumerate(selected, 1)]
            write_json(Path(collector['target']).with_suffix('.json'),
                       {'records': records, 'gaps': collector['gaps'],
                        'decision_image_paths': [r['image_path'] for r in selected]})
        started = time.monotonic()
        writer = asyncio.create_task(asyncio.to_thread(_write_bundle, selected, collector['target']))
        try:
            await asyncio.shield(writer)
        except asyncio.CancelledError:
            await writer
            raise
        payload = io_path(collector['target']).read_bytes()
        trace(context).record('visual_packaging', call_id=context.get('source_call_id'),
                              duration_ms=(time.monotonic() - started) * 1000,
                              bytes=len(payload), pictures=len(selected))
        queued = len(payload) <= config_value(context.get('config', {}), 'max_attachment_bytes', 20 * 1024 * 1024)
        pending = context.setdefault('pending_visual_attachments', [])
        if not queued and collector['target'] in pending:
            pending.remove(collector['target'])
        if queued and collector['target'] not in pending:
            pending.append(collector['target'])
        return {'status': 'attachment_too_large' if not queued else 'partial' if collector['gaps'] else 'captured',
            'pictures': len(selected), 'audit_pictures': len(records), 'compact_current_view': bool(compact), 'bytes': len(payload),
            'path': collector['target'], 'sha256': hashlib.sha256(payload).hexdigest(),
            'queued_for_copilot': queued, 'gaps': list(collector['gaps']),
            'captions': [record['label'] for record in selected]}


async def capture_visuals(page, context, *, label, revisit=True, scroll_owned_page=False):
    """Read the real current view; scroll only a guarded independent revisit."""
    holder = context.setdefault('automatic_visual_context', {})
    batch = str(context.get('source_request_id') or 'session-batch')
    # Shared shallow-copied contexts retain one collector and lock per request.
    collectors = holder.setdefault('batches', {})
    collector = collectors.setdefault(batch, {'lock': asyncio.Lock(), 'records': [], 'gaps': [],
        'target': str(Path(context['session_dir']) / 'screenshots' / (uuid.uuid4().hex + '-automatic.pdf'))})
    async with collector['lock']:
        records, gaps = collector['records'], collector['gaps']
        if len(records) >= MAX_PICTURES:
            return {'status': 'sample_limit', 'path': collector['target'], 'pictures': len(records),
                    'note': 'Twelve-picture visual sample is full; additional pages were not pictured.'}
        clone = None
        original_url = page.url
        try:
            _url_policy(context).resolve(original_url)
            async def record(source, caption, *, crop=None):
                if len(records) >= MAX_PICTURES:
                    return
                if source.url != original_url:
                    raise ValueError('Visual page changed; capture excluded')
                pixels = await source.screenshot(type='png', scale='css', timeout=5000, mask=[source.locator(MASK)])
                if source.url != original_url:
                    raise ValueError('Visual page changed during screenshot; capture excluded')
                metrics = await source.evaluate(METRICS)
                with Image.open(BytesIO(pixels)) as image:
                    image = image.convert('RGB')
                    try:
                        if crop:
                            cropped = image.crop(crop(image.width, image.height))
                            image.close()
                            image = cropped
                        path = Path(collector['target']).with_name(uuid.uuid4().hex + '.png')
                        io_path(path).parent.mkdir(parents=True, exist_ok=True)
                        image.save(io_path(path), 'PNG')
                        records.append({'number': len(records) + 1, 'label': label + ': ' + caption,
                            'url': safe_url(original_url), 'scroll': {'x': metrics['x'], 'y': metrics['y']},
                            'kind': 'closeup' if crop else 'viewport', 'image_path': str(path)})
                    finally:
                        image.close()
            await record(page, 'actual current page overview')
            # Pixel crops preserve transient SPA state without scrolling the analysis page.
            boxes = await page.evaluate("""() => {const boxes=[];for(const n of document.querySelectorAll('button,[role=button],nav,[role=navigation]')) {
                const r=n.getBoundingClientRect();if(r.width>0&&r.height>0&&r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight)
                boxes.push({x:r.x,y:r.y,w:r.width,h:r.height});if(boxes.length===2)break;}return boxes;}""")
            for index, box in enumerate(boxes):
                await record(page, f'actual visible navigation/button region {index+1}',
                    crop=lambda w,h,b=box: (max(0,int(b['x'])-50),max(0,int(b['y'])-50),
                        min(w,int(b['x']+b['w'])+100),min(h,int(b['y']+b['h'])+100)))
            if not boxes:
                await record(page, 'actual upper page closeup', crop=lambda w,h: (0,0,w,max(1,h//2)))
                await record(page, 'actual lower page closeup', crop=lambda w,h: (0,h//2,w,h))
            if (revisit or scroll_owned_page) and len(records) < MAX_PICTURES:
                browser = context['browser']
                if revisit:
                    clone = await browser.new_tool_page()
                    await _install_origin_guard(clone, context, original_url)
                    await clone.goto(original_url, wait_until='domcontentloaded', timeout=10000)
                scroll_page = clone if clone is not None else page
                metrics = await scroll_page.evaluate(METRICS)
                if metrics['maxY']:
                    for y in sorted({round(metrics['maxY']/2), metrics['maxY']}):
                        if len(records) >= MAX_PICTURES:
                            break
                        await scroll_page.evaluate('(y)=>window.scrollTo({top:y,behavior:"instant"})', y)
                        caption = (f'independent authenticated revisit, scroll Y={y}; transient state may differ'
                                   if clone is not None else f'crawl-owned page scroll Y={y}')
                        await record(scroll_page, caption)
                if len(records) < MAX_PICTURES:
                    panel = await scroll_page.evaluate(SCROLL_PANEL, None)
                    if panel and panel.get('maxY', 0):
                        for ratio in (.5, 1):
                            if len(records) >= MAX_PICTURES:
                                break
                            position = await scroll_page.evaluate(SCROLL_PANEL, ratio)
                            await record(scroll_page, f'dominant internal scrolling panel, {round(ratio*100)}%; '
                                + ('independent revisit; transient state may differ' if clone is not None else 'crawl-owned page'))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            gaps.append({'source': label, 'reason': type(error).__name__,
                         'note': 'Visual capture incomplete; investigation result remains authoritative.'})
        finally:
            if clone is not None:
                try:
                    await asyncio.wait_for(clone.close(), 3)
                except Exception:
                    pass
        if records:
            writer = asyncio.create_task(asyncio.to_thread(_write_bundle, list(records), collector['target']))
            try:
                await asyncio.shield(writer)
            except asyncio.CancelledError:
                await writer
                raise
            size = io_path(collector['target']).stat().st_size
            limit = config_value(context.get('config', {}), 'max_attachment_bytes', 20 * 1024 * 1024)
            if size > limit:
                pending = context.setdefault('pending_visual_attachments', [])
                if collector['target'] in pending:
                    pending.remove(collector['target'])
                return {'status': 'attachment_too_large', 'path': collector['target'], 'pictures': len(records),
                        'bytes': size, 'queued_for_copilot': False, 'gaps': gaps}
            pending = context.setdefault('pending_visual_attachments', [])
            if collector['target'] not in pending:
                pending.append(collector['target'])
        return {'status': 'partial' if gaps else 'captured', 'path': collector['target'] if records else None,
                'sha256': hashlib.sha256(io_path(collector['target']).read_bytes()).hexdigest() if records else None,
                'pictures': len(records), 'captions': [r['label'] for r in records],
                'gaps': list(gaps), 'queued_for_copilot': bool(records),
                'coverage': 'Bounded visual samples; not complete page or control coverage.'}


async def _safe_capture(name, args, context):
    try:
        page = _source_page(name, args, context)
        return await asyncio.wait_for(capture_visuals(page, context, label=name), 25)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return {'status': 'unavailable', 'pictures': 0, 'queued_for_copilot': False,
                'reason': type(error).__name__, 'note': 'No matching owned visual page or capture unavailable.'}


async def execute_with_visuals(name, args, context, operation):
    # Serialize observation/action transactions on the SAME owned page, including
    # scroll captures. Existing independent reads on different tabs still overlap.
    if name.startswith('browser.'):
        from .goal_navigation import page_lock
        async with page_lock(context, args):
            return await _execute_with_visuals(name, args, context, operation)
    return await _execute_with_visuals(name, args, context, operation)


async def _execute_with_visuals(name, args, context, operation):
    if name.startswith('browser.') or name in {'operation.call', 'operation.learn'}:
        action_id = str(context.get('source_call_id') or 'call') + '/' + uuid.uuid4().hex[:12]
        def owned_page(arguments):
            try:
                return _source_page(name, arguments, context)
            except Exception:
                return None
        await capture_action_phase(owned_page(args), context, name, 'before', action_id)
        result = None
        try:
            _check_cancelled(context)
            if context.get('cancel_event') is not None and context['cancel_event'].is_set():
                raise NavigationStop('cancelled', 'User cancellation received during before-action capture')
            result = await operation()
            return result
        finally:
            after_args = dict(args)
            if isinstance(result, dict) and result.get('tab_id'):
                after_args['tab_id'] = result['tab_id']
            await capture_action_phase(owned_page(after_args), context, name, 'after', action_id)
            try:
                visual = await flush_visual_context(context)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                visual = {'status': 'unavailable', 'reason': type(error).__name__, 'queued_for_copilot': False}
            if isinstance(result, dict):
                result['visual_context'] = visual
                old_path = result.get('screenshot', {}).get('path')
                pending = context.get('pending_file_attachments', [])
                if visual.get('queued_for_copilot') and old_path in pending:
                    pending.remove(old_path)
    if name == 'crawl4ai.crawl':
        result = await operation()
        if isinstance(result, dict):
            try:
                result['visual_context'] = await flush_visual_context(context)
            except Exception:
                result['visual_context'] = context.get('crawl_visual_context', {
                    'status': 'unavailable', 'note': 'No browser page visual capture was produced for this crawl.'})
        return result
    if not relevant(name, args):
        return await operation()
    if name in AFTER:
        result = await operation()
        if name == 'browser.discover' and isinstance(result, dict) and result.get('visual'):
            visual = result['visual']
            result['visual_context'] = {**visual, 'status': visual.get('status', 'captured'),
                'queued_for_copilot': visual.get('queued_for_copilot', visual['path'] in context.get('pending_file_attachments', [])),
                'association': 'Existing paired screenshots for each visited discovery state; no duplicate visual batch generated.'}
            return result
        visual = await _safe_capture(name, args, context)
    else:
        tasks = [asyncio.create_task(operation()), asyncio.create_task(_safe_capture(name, args, context))]
        try:
            result, visual = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    if isinstance(result, dict):
        result['visual_context'] = visual
        if name == 'browser.inspect' and visual.get('queued_for_copilot'):
            old_path = result.get('screenshot', {}).get('path')
            pending = context.get('pending_file_attachments', [])
            if old_path in pending:
                pending.remove(old_path)  # The automatic merged PDF supplies the same current-page context and closeups.
        if name in {'rea.analyze_capture', 'rea.analyze_artifact'}:
            visual['association'] = 'Current owned browser context only; this is not proof that the file came from this page.'
    return result
