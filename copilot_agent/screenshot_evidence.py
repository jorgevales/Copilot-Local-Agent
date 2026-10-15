"""One labeled, full-resolution PDF for a configurable batch of page captures."""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
import textwrap
import uuid
from urllib.parse import urlsplit, urlunsplit

from PIL import Image, ImageDraw, ImageFont

from .persistence import io_path
from .policy import PolicyError


def _object(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


CAPTURE_PROPERTIES = {
    'tab_id': {'type': 'string', 'maxLength': 100},
    'shots': {'type': 'array', 'minItems': 1, 'maxItems': 30, 'items': _object({
        'label': {'type': 'string', 'minLength': 1, 'maxLength': 160},
        'selector': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
        'scroll_container': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
        'scroll_x': {'type': 'integer', 'minimum': 0, 'maximum': 10000000},
        'scroll_y': {'type': 'integer', 'minimum': 0, 'maximum': 10000000},
        'full_page': {'type': 'boolean'},
        'clip': _object({key: {'type': 'integer', 'minimum': 1 if key in {'width', 'height'} else 0,
                              'maximum': 100000} for key in ('x', 'y', 'width', 'height')},
                        ('x', 'y', 'width', 'height')),
    }, ('label',))},
    'max_shots': {'type': 'integer', 'minimum': 1, 'maximum': 30},
    'restore_scroll': {'type': 'boolean'},
    'full_page': {'type': 'boolean'},
}

METRICS = '() => ({x:scrollX,y:scrollY,width:innerWidth,height:innerHeight,maxY:Math.max(0,document.documentElement.scrollHeight-innerHeight)})'
MASK = 'input[type=password],[autocomplete=current-password],[autocomplete=new-password]'


def _pdf(pages, target):
    font = ImageFont.load_default(size=18)
    output = []
    try:
        for record, image in pages:
            width = max(800, image.width)
            label = f"Screenshot {record['number']:02d} of {record['requested_total']:02d} - {record['label']}"
            detail = f"Page scroll: ({record['scroll']['x']}, {record['scroll']['y']}) CSS pixels | {record['kind']}"
            lines = []
            for value in (label, record['url'], detail, record.get('target', '')):
                lines.extend(textwrap.wrap(value, max(30, (width - 40) // 11)) or [''])
            header = 30 + len(lines) * 26
            sheet = Image.new('RGB', (width, image.height + header), 'white')
            draw = ImageDraw.Draw(sheet)
            for i, line in enumerate(lines):
                draw.text((20, 12 + i * 26), line, font=font, fill='black')
            sheet.paste(image, (0, header))
            output.append(sheet)
        path = io_path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        output[0].save(path, 'PDF', save_all=True, append_images=output[1:], resolution=96,
                       quality=95, subsampling=0, title='Labeled browser screenshot evidence')
    finally:
        for image in output:
            image.close()


async def capture_evidence(page, args, context, observation=None):
    original = await page.evaluate(METRICS)
    url = page.url
    parsed = urlsplit(url)
    safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    shots = args.get('shots')
    if shots is None:
        if args.get('full_page'):
            shots = [{'label': 'Full page', 'full_page': True}]
        else:
            count = args.get('max_shots', 3) if original['maxY'] else 1
            positions = list(dict.fromkeys(round(original['maxY'] * i / max(1, count - 1)) for i in range(count)))
            shots = [{'label': f'Page section {i + 1}: scroll Y={y}', 'scroll_y': y} for i, y in enumerate(positions)]
    records, pages, gaps, containers = [], [], [], []
    structural = None
    try:
        for index, shot in enumerate(shots):
            image = None
            try:
                if page.url != url:
                    raise PolicyError('Page navigated during screenshot batch; remaining captures were not taken')
                if sum(bool(shot.get(key)) for key in ('selector', 'clip', 'full_page')) > 1:
                    raise PolicyError('Use an element selector, viewport clip, or full page separately in each shot')
                container = page.locator(shot['scroll_container']) if shot.get('scroll_container') else None
                if container is not None:
                    if await container.count() != 1:
                        raise PolicyError('scroll_container must identify exactly one element')
                    saved = await container.evaluate('(n)=>({x:n.scrollLeft,y:n.scrollTop})')
                    containers.append((container, saved))
                if 'scroll_y' in shot or 'scroll_x' in shot:
                    current = saved if container is not None else await page.evaluate(METRICS)
                    position = {'x': shot.get('scroll_x', current['x']), 'y': shot.get('scroll_y', current['y'])}
                    if container is not None:
                        await container.evaluate('(n,p)=>n.scrollTo({left:p.x,top:p.y,behavior:"instant"})', position)
                    else:
                        await page.evaluate('(p)=>window.scrollTo({left:p.x,top:p.y,behavior:"instant"})', position)
                if shot.get('selector'):
                    locator = page.locator(shot['selector'])
                    if await locator.count() != 1:
                        raise PolicyError('Screenshot selector must identify exactly one element')
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    screenshot = locator.screenshot(type='png', scale='css', timeout=10000,
                                                    mask=[page.locator(MASK)])
                else:
                    screenshot = page.screenshot(type='png', scale='css', full_page=shot.get('full_page', False),
                                                 timeout=10000, mask=[page.locator(MASK)])
                if observation is not None:
                    structural, pixels = await asyncio.gather(observation(), screenshot, return_exceptions=True)
                    observation = None
                    if isinstance(pixels, BaseException):
                        raise pixels
                else:
                    pixels = await screenshot
                if page.url != url:
                    raise PolicyError('Page navigated during capture; this picture was excluded')
                with Image.open(BytesIO(pixels)) as source:
                    image = source.convert('RGB')
                if shot.get('clip'):
                    clip = shot['clip']
                    box = (clip['x'], clip['y'], clip['x'] + clip['width'], clip['y'] + clip['height'])
                    if box[2] > image.width or box[3] > image.height:
                        raise PolicyError('Clip extends outside the captured viewport; use reported CSS dimensions')
                    cropped = image.crop(box)
                    image.close()
                    image = cropped
                metrics = await page.evaluate(METRICS)
                record = {'number': index + 1, 'requested_total': len(shots), 'label': shot['label'], 'url': safe_url,
                          'scroll': {'x': metrics['x'], 'y': metrics['y']},
                          'kind': 'element' if shot.get('selector') else 'clip' if shot.get('clip') else 'full_page' if shot.get('full_page') else 'viewport',
                          'target': shot.get('selector') or str(shot.get('clip') or ''),
                          'width': image.width, 'height': image.height}
                if container is not None:
                    record['container'] = {'selector': shot['scroll_container'],
                        **await container.evaluate('(n)=>({x:n.scrollLeft,y:n.scrollTop})')}
                    record['target'] += ' | container=' + shot['scroll_container'] + ' ' + str(record['container'])
                records.append(record)
                pages.append((record, image))
                image = None
            except Exception as error:
                gaps.append({'number': index + 1, 'label': shot['label'], 'error': str(error)[:400]})
                if page.url != url:
                    break
            finally:
                if image is not None:
                    image.close()
        if observation is not None:
            try:
                structural = await observation()
            except Exception as error:
                structural = error
        result = {'status': 'partial' if gaps else 'observed', 'shots': records, 'gaps': gaps,
                  'requested_shots': len(shots), 'coverage': 'Explicit captures or sampled scroll positions; not a guarantee of complete page coverage',
                  'coordinate_space': 'Viewport CSS pixels; each picture reports its page/container scroll',
                  'side_effects_uncertain': False}
        if pages:
            target = Path(context['session_dir']) / 'screenshots' / (uuid.uuid4().hex + '-evidence.pdf')
            saving = asyncio.create_task(asyncio.to_thread(_pdf, pages, target))
            try:
                await asyncio.shield(saving)
            except asyncio.CancelledError:
                await saving  # Do not close image buffers while the writer still uses them.
                raise
            data = io_path(target).read_bytes()
            pending = context.setdefault('pending_file_attachments', [])
            pending.append(str(target))
            result['path'] = str(target)  # Preserve the original browser.screenshot path contract.
            result['screenshot'] = {'path': str(target), 'sha256': hashlib.sha256(data).hexdigest(),
                                    'bytes': len(data), 'format': 'pdf', 'pictures': len(pages),
                                    'queued_for_copilot': True}
        if structural is not None:
            result['_structure'] = structural
        return result
    finally:
        for _, image in pages:
            image.close()
        if args.get('restore_scroll', True) and page.url == url:
            try:
                for container, position in reversed(containers):
                    await container.evaluate('(n,p)=>n.scrollTo({left:p.x,top:p.y,behavior:"instant"})', position)
                await page.evaluate('(p)=>window.scrollTo({left:p.x,top:p.y,behavior:"instant"})', original)
            except Exception:
                # Captures remain evidence even if the site replaced a scroll container.
                pass
