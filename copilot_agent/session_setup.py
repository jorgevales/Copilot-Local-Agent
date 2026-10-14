"""Plain-language, session-only package and website discovery choices."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import threading

from .local_crawler import crawl_websites, open_login_page, website_url


async def choose_package_mode(config, ask, report, *, supplied=None):
    choice = supplied
    if choice is None:
        report('Choose how packages run for this session. The choice resets when the agent closes.')
        report('Immediate running skips package checking and lets downloads and package code run for the rest of this session. A damaged ZIP or unusable run instructions can still stop a run.')
        while True:
            answer = (await ask('Package checking: 1 = Review before running (recommended), 2 = Skip review and run immediately for this session [1/2]: ')).strip()
            if answer in {'', '1', '2'}:
                choice = 'immediate' if answer == '2' else 'reviewed'
                break
            report('Please choose 1 or 2.')
    if choice not in {'reviewed', 'immediate'}:
        raise ValueError('Choose reviewed or immediate package mode.')
    config._package_review_enabled = choice == 'reviewed'
    config._continuous_package_session = choice == 'immediate'
    report('Package mode for this session: ' + ('immediate continuous running; quality review skipped.'
                                               if choice == 'immediate' else 'review before running.'))


async def guided_discovery(config, browser, session_dir, ask, report, cancel_event=None):
    if (await ask('Discover websites locally with Crawl4AI before starting the agent [y/N]? ')).strip().lower() not in {'y', 'yes'}:
        return []
    report('Saved website content stays in shared Discoveries knowledge. The agent receives its file paths and can read content when your task needs it; content it reads is sent to Copilot.')
    saved = []
    while True:
        address = (await ask('Paste the website address, or press Enter to finish: ')).strip()
        if not address:
            break
        try:
            address = website_url(address)
        except ValueError as error:
            report(str(error))
            continue
        title = (await ask('What title should we give this website knowledge? ')).strip()
        if not title:
            report('A title is needed so you can find the saved knowledge later.')
            continue
        page = None
        try:
            page = await open_login_page(browser, address)
            report('The website is open in Edge. Sign in yourself if asked, and open the starting page you want explored.')
            if (await ask('When the website is ready, press Enter to start discovery, or type skip: ')).strip().lower() == 'skip':
                continue
            # The operator may have selected a more useful authenticated start page.
            start = website_url(page.url)
            mode = (await ask('1 = Explore once, 2 = Keep refreshing until you stop [1/2]: ')).strip()
            stop = threading.Event()
            context = {'config': config, 'browser': browser, 'session_dir': session_dir,
                       'approved': True, 'cancel_event': stop,
                       'automation_progress': lambda item: report('Saved ' + str(item['saved_pages']) + ' pages for ' + title + '.')}
            task = asyncio.create_task(crawl_websites({'urls': [start], 'title': title,
                'cycles': 0 if mode == '2' else 1}, context))
            prompt = asyncio.create_task(ask('Discovery is running. Press Enter to stop and keep the saved pages: ')) if mode == '2' else None
            external_stop = asyncio.create_task(_watch_stop(cancel_event, stop, task)) if cancel_event is not None else None
            try:
                if prompt:
                    # A terminal input() thread cannot be cancelled. Keep one
                    # reader until the operator finishes this continuous crawl.
                    task.add_done_callback(lambda done: report('Discovery ended. Press Enter to continue.')
                                           if not done.cancelled() else None)
                    await prompt
                    if not task.done():
                        stop.set()
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                        report('Discovery stopped. Completed pages and the remaining routes are saved.')
                    else:
                        saved.append(await task)
                else:
                    saved.append(await task)
            finally:
                for pending in (prompt, external_stop, task):
                    if pending is not None and not pending.done():
                        pending.cancel()
                        with suppress(asyncio.CancelledError):
                            await pending
            # Include interrupted indexes too, without uploading their page content.
            from .persistence import io_path
            import json
            if context.get('crawl4ai_saved_index'):
                index_path = context['crawl4ai_saved_index']
                index_file = io_path(index_path)
                record = json.loads(index_file.read_text(encoding='utf-8'))
                if not any(item.get('index_path') == index_path for item in saved):
                    saved.append({'title': title, 'index_path': index_path,
                                  'saved_pages': len(record.get('pages', {})), 'status': record.get('status')})
            for item in saved:
                if item.get('title') == title:
                    report('Knowledge saved: ' + item['index_path'])
            config._guided_knowledge_paths = list(saved)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            report('This website discovery stopped: ' + str(error)[:500] + '. Saved pages are retained; you can retry.')
        finally:
            if page is not None:
                await page.close()
        if cancel_event is not None and cancel_event.is_set():
            break
    return saved


async def _watch_stop(cancel_event, stop, task):
    while not cancel_event.is_set():
        await asyncio.sleep(.2)
    stop.set()
    task.cancel()
