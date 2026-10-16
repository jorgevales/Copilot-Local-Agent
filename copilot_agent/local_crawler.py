"""Local Crawl4AI, using owned tabs in the already connected Edge session.

Page content is saved only in the configured shared knowledge directory. There
is no cloud crawler, LLM extraction, copied cookie file, or second browser.
"""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
import uuid

from .persistence import io_path, write_json
from .policy import PolicyError, config_value, reject_path_redirection
from .knowledge_views import (canonical_site_origin, evidence_folder,
                              evidence_namespace, website_storage_root)


def website_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter a complete http:// or https:// website address without a password.')
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', parsed.query, ''))


def knowledge_root(config):
    """Use the existing S:/UNC resolver and its configured extended-I/O fallback."""
    from .site_knowledge import knowledge_directory
    return knowledge_directory({'config': config}) / 'websites'


def saved_html(document):
    """Keep business text/form values; remove scripts and credential controls."""
    from lxml import html
    tree = html.fromstring(document)
    for element in list(tree.xpath('//script | //input[@type="hidden"]')):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        hint = ' '.join(element.attrib.get(name, '') for name in ('type', 'name', 'id', 'autocomplete'))
        credential = (element.attrib.get('type', '').lower() in {'password', 'hidden', 'file'}
                      or re.search(r'password|passwd|access.?token|refresh.?token|api.?key|client.?secret|authorization', hint, re.I))
        if element.tag.lower() in {'input', 'textarea'} and credential:
            element.attrib.pop('value', None)
            if element.tag.lower() == 'textarea':
                element.text = ''
        for name in list(element.attrib):
            if name.lower().startswith('on') or re.search(r'(?:token|secret|password|authorization)', name, re.I):
                del element.attrib[name]
    return html.tostring(tree, encoding='unicode')


async def open_login_page(browser, url):
    if getattr(browser, 'context', None) is None:
        raise PolicyError('The connected Edge session is required before website discovery.')
    page = await browser.context.new_page()
    try:
        await page.goto(website_url(url), wait_until='domcontentloaded', timeout=60000)
        await page.bring_to_front()
        return page
    except BaseException:
        await page.close()
        raise


def crawler_factory(browser, scratch, page_timeout, *, visual_context=None):
    """Supply Crawl4AI with the company's live browser rather than launching one."""
    os.environ['CRAWL4AI_NO_CLOUD_NOTICE'] = '1'
    from crawl4ai import AsyncWebCrawler, BrowserConfig
    from crawl4ai.async_crawler_strategy import AsyncCrawlerStrategy
    from crawl4ai.async_logger import AsyncLogger
    from crawl4ai.models import AsyncCrawlResponse

    class ConnectedEdgeStrategy(AsyncCrawlerStrategy):
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass  # Only crawl-owned pages are closed; the company browser stays open.

        async def crawl(self, url, **options):
            page = await browser.context.new_page()
            try:
                if visual_context is not None:
                    from .automatic_visuals import paired_browser_action
                    response = await paired_browser_action(page, visual_context, 'crawl4ai page navigate',
                        lambda: page.goto(url, wait_until='domcontentloaded', timeout=page_timeout))
                else:
                    response = await page.goto(url, wait_until='domcontentloaded', timeout=page_timeout)
                config = options.get('config')
                script = getattr(config, 'js_code', None)
                for expression in ([script] if isinstance(script, str) else script or []):
                    await page.evaluate(expression)
                condition = getattr(config, 'wait_for', None)
                if condition:
                    if condition.startswith('js:'):
                        await page.wait_for_function(condition[3:], timeout=page_timeout)
                    else:
                        await page.wait_for_selector(condition.removeprefix('css:'), timeout=page_timeout)
                else:
                    from .site_discovery import settle
                    await settle(page, time.monotonic() + min(12, page_timeout/1000), [])
                captured_html = await page.content()  # Preserve the observed DOM before visual scrolls reveal virtualized content.
                if visual_context is not None:
                    from .automatic_visuals import capture_visuals
                    try:
                        visual_context['crawl_visual_context'] = await asyncio.wait_for(capture_visuals(page, visual_context,
                            label='crawl4ai discovered page', revisit=False, scroll_owned_page=True), 20)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        visual_context['crawl_visual_context'] = {'status': 'unavailable',
                            'note': 'Crawl page visual capture was unavailable; saved page evidence remains authoritative.'}
                        visual_context.setdefault('automatic_visual_gaps', []).append(
                            {'source': 'crawl4ai', 'status': 'capture_unavailable'})
                return AsyncCrawlResponse(html=captured_html,
                    response_headers={}, status_code=response.status if response else 200,
                    redirected_url=page.url)
            finally:
                await page.close()

    return AsyncWebCrawler(crawler_strategy=ConnectedEdgeStrategy(),
        config=BrowserConfig(headless=False, verbose=False), base_directory=str(scratch),
        logger=AsyncLogger(verbose=False))


async def crawl_websites(args, context, *, factory=None):
    """Resumable, concurrent BFS; zero page/depth/cycle budgets mean unlimited.

    Every completed page and frontier is committed incrementally. A repeated
    cycle refreshes observed routes and follows new links. Stop is checked
    between pages and batches; cancellation closes the active owned tabs.
    """
    if not context.get('approved'):
        raise PolicyError('Approve local website discovery for this session first.')
    from crawl4ai import CacheMode, CrawlerRunConfig
    browser = context['browser']
    if getattr(browser, 'context', None) is None:
        raise PolicyError('The connected Edge session is unavailable.')
    urls = list(dict.fromkeys(website_url(url) for url in args['urls']))
    title = args['title'].strip()
    if not title:
        raise ValueError('Give this website knowledge a title.')
    storage_root = website_storage_root(knowledge_root(context['config']))
    site_origins = sorted({canonical_site_origin(url) for url in urls})
    if len(site_origins) == 1:
        folder = evidence_folder(context, site_origins[0], 'crawl4ai', root=storage_root)
    else:
        identity = [(origin, evidence_namespace(context, origin)) for origin in site_origins]
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
        folder = storage_root / 'campaigns' / key
    reject_path_redirection(folder)
    index_path = folder / 'index.json'
    storage = io_path(folder)
    storage.mkdir(parents=True, exist_ok=True)
    index_file = io_path(index_path)
    index = json.loads(index_file.read_text(encoding='utf-8')) if index_file.exists() else {
        'schema_version': 1, 'title': title, 'urls': urls, 'pages': {}, 'frontier': [], 'errors': {}}
    index['evidence_kind'] = 'raw_task_evidence_not_reusable_knowledge'
    index['title'] = title
    new_seeds = [url for url in urls if url not in index.get('urls', [])]
    index['urls'] = list(dict.fromkeys(index.get('urls', []) + urls))
    context['crawl4ai_saved_index'] = str(index_path)
    origins = {(urlsplit(url).scheme, urlsplit(url).netloc) for url in urls}
    max_pages, max_depth = args.get('max_pages', 0), args.get('max_depth', 0)
    cycles, concurrency = args.get('cycles', 1), args.get('concurrency', 4)
    cancel = context.get('cancel_event')
    stopped = lambda: bool(cancel and cancel.is_set())
    scratch = Path(context['session_dir']) / 'crawl4ai' / uuid.uuid4().hex
    run_config = CrawlerRunConfig(cache_mode=CacheMode.DISABLED, verbose=False,
        word_count_threshold=0, score_links=False, remove_forms=True)
    page_count, cycle = 0, 0
    frontier = deque(index.get('frontier') or [(url, 0) for url in urls])
    resumed_frontier = bool(index.get('frontier'))
    queued = {url for url, _ in frontier}
    frontier.extend((url, 0) for url in new_seeds if url not in queued)

    def save(status):
        index.update(status=status, frontier=list(frontier), updated_at=time.time())
        write_json(index_path, index)

    async def capture(crawler, url, depth):
        result = await crawler.arun(url=url, config=run_config)
        if not result.success:
            index['errors'][url] = 'Capture failed; open this website and check its sign-in or access.'
            return []
        destination = website_url(result.redirected_url or result.url or url)
        # Sign-in and external redirects must not replace saved target knowledge.
        if (urlsplit(destination).scheme, urlsplit(destination).netloc) not in origins and not args.get('follow_external', False):
            index['errors'][url] = 'Website redirected outside the selected site. Sign in and retry.'
            return []
        html = result.html or ''
        if re.search(r'<input\b[^>]*\btype\s*=\s*[\"\']?password\b', html, re.I):
            index['errors'][url] = 'Sign in manually in Edge, then run discovery again.'
            return []
        markdown = getattr(result.markdown, 'raw_markdown', result.markdown) or ''
        page_key = hashlib.sha256(url.encode()).hexdigest()
        page_folder = evidence_folder(context, destination, 'crawl4ai', root=storage_root)
        page_path = page_folder / (page_key + '.json')
        reject_path_redirection(page_path)
        links = result.links
        if hasattr(links, 'model_dump'):
            links = links.model_dump()
        links = links or {}
        payload = {'title': title, 'url': url, 'resolved_url': destination, 'depth': depth,
                   'captured_at': time.time(), 'status_code': result.status_code,
                   'markdown': str(markdown), 'html': saved_html(html), 'links': links,
                   'metadata': result.metadata or {},
                   'evidence_kind': 'raw_task_evidence_not_reusable_knowledge'}
        write_json(page_path, payload)
        data = io_path(page_path).read_bytes()
        index['pages'][url] = {'path': str(page_path), 'sha256': hashlib.sha256(data).hexdigest(), 'depth': depth}
        index['errors'].pop(url, None)
        children = []
        if not max_depth or depth < max_depth:
            for link in [*links.get('internal', []), *links.get('external', [])]:
                try:
                    child = website_url(urljoin(destination, link.get('href', '')))
                except (ValueError, TypeError):
                    continue
                route_parts = {re.sub(r'[-_]', '', part.lower()) for part in urlsplit(child).path.split('/')}
                if route_parts & {'logout', 'logoff', 'signout', 'delete', 'destroy'}:
                    # A navigation crawl must not sign the operator out or
                    # follow obvious destructive GET controls.
                    index.setdefault('excluded_routes', {})[child] = 'Sign-out or destructive navigation control'
                    continue
                if args.get('follow_external', False) or (urlsplit(child).scheme, urlsplit(child).netloc) in origins:
                    children.append((child, depth + 1))
        progress = context.get('automation_progress')
        if callable(progress):
            progress({'event': 'website_discovery_page', 'title': title,
                      'saved_pages': len(index['pages']), 'index_path': str(index_path)})
        return children

    try:
        save('running')
        crawler_manager = (factory(browser, scratch, args.get('page_timeout_seconds', 60) * 1000)
                           if factory else crawler_factory(browser, scratch,
                               args.get('page_timeout_seconds', 60) * 1000, visual_context=context))
        async with crawler_manager as crawler:
            while not stopped() and (not cycles or cycle < cycles):
                seen = set(index['pages']) if resumed_frontier and cycle == 0 else set()
                while frontier and not stopped() and (not max_pages or page_count < max_pages):
                    batch = []
                    while frontier and len(batch) < concurrency and (not max_pages or page_count + len(batch) < max_pages):
                        url, depth = frontier.popleft()
                        if url not in seen:
                            seen.add(url)
                            batch.append((url, depth))
                    if not batch:
                        continue
                    pending = asyncio.gather(*(capture(crawler, url, depth) for url, depth in batch), return_exceptions=True)
                    try:
                        while not pending.done():
                            if stopped():
                                pending.cancel()
                                raise asyncio.CancelledError
                            await asyncio.wait({pending}, timeout=.2)
                        outcomes = await pending
                    except asyncio.CancelledError:
                        pending.cancel()
                        with suppress(asyncio.CancelledError):
                            await pending
                        frontier.extendleft(reversed(batch))
                        if stopped():
                            break
                        raise
                    except BaseException:
                        pending.cancel()
                        with suppress(asyncio.CancelledError):
                            await pending
                        frontier.extendleft(reversed(batch))
                        raise
                    page_count += len(batch)
                    for (url, _), outcome in zip(batch, outcomes):
                        if isinstance(outcome, BaseException):
                            index['errors'][url] = 'Capture failed; completed pages were retained. Retry discovery.'
                        else:
                            frontier.extend(item for item in outcome if item[0] not in seen)
                    save('running')
                cycle += 1
                if frontier or max_pages and page_count >= max_pages or stopped() or cycles and cycle >= cycles:
                    break
                frontier.extend((url, record['depth']) for url, record in index['pages'].items())
                frontier.extend((url, 0) for url in urls if url not in index['pages'])
                # Responsive wait; Stop does not wait for the refresh interval.
                deadline = time.monotonic() + args.get('refresh_seconds', 30)
                while not stopped() and time.monotonic() < deadline:
                    await asyncio.sleep(min(.2, max(0, deadline - time.monotonic())))
        status = 'cancelled' if stopped() else 'partial' if frontier or index['errors'] else 'completed'
        save(status)
    except BaseException:
        save('interrupted')
        raise
    return {'status': status, 'title': title, 'index_path': str(index_path),
            'knowledge_directory': str(folder), 'saved_pages': len(index['pages']),
            'pending_pages': len(frontier), 'failed_pages': len(index['errors']),
            'read_tool': 'crawl4ai.read', 'cycles_completed': cycle,
            'evidence_kind': 'raw_task_evidence_not_reusable_knowledge'}


def read_knowledge(args, context, *, policy=None):
    """Read arbitrary-sized saved knowledge in windows without UI result truncation."""
    if policy is not None:
        requested = policy.resolve(args['path'], must_exist=True)
    else:
        legacy = knowledge_root(context['config']).resolve()
        root = website_storage_root(legacy).resolve()
        requested = Path(args['path']).resolve()
        roots = (legacy, root / 'sites', root / 'campaigns')
        if not any(requested.is_relative_to(candidate) for candidate in roots):
            raise PolicyError('Choose a file inside the shared website knowledge directory.')
        reject_path_redirection(requested)
    cap = config_value(context.get('config', {}), 'max_attachment_bytes', 100 * 1024 * 1024)
    if not requested.is_file() or requested.stat().st_size > cap:
        raise PolicyError('Crawl4AI read accepts files up to the configured attachment size limit.')
    text = io_path(requested).read_text(encoding='utf-8')
    offset, limit = args.get('offset', 0), args.get('limit', 8000)
    content = text[offset:offset + limit]
    budget = min(12000, max(1000, config_value(context.get('config', {}), 'max_output_chars', 12000)))
    while True:
        result = {'path': str(requested), 'content': content, 'offset': offset,
                  'next_offset': offset + len(content) if offset + len(content) < len(text) else None,
                  'total_characters': len(text)}
        if len(json.dumps({'ok': True, 'tool': 'crawl4ai.read', 'result': result}, ensure_ascii=False)) <= budget - 150:
            return result
        if not content:
            raise ValueError('The configured output budget cannot fit this file address.')
        content = content[:len(content) // 2]
