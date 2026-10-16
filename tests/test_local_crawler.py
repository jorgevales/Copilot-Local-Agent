import asyncio
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.local_crawler import crawl_websites, read_knowledge, website_url
from copilot_agent.session_setup import choose_package_mode, guided_discovery
from copilot_agent.tools import ToolRegistry


class Page:
    def __init__(self, owner):
        self.owner = owner
        self.url = 'about:blank'
        self.closed = False

    async def goto(self, url, **_):
        self.url = url
        self.owner.visited.append(url)
        return SimpleNamespace(status=200)

    async def content(self):
        if self.url.endswith('/private'):
            return '<html><body><form><input type="password"></form></body></html>'
        if self.url.endswith('/second'):
            return '<html><body><h1>Second page knowledge</h1><p>' + ('Saved second content for company website navigation. ' * 8) + '</p><a href="/">Home</a></body></html>'
        return '<html><body><h1>Company knowledge</h1><p>Already signed in.</p><a href="/second">Next page</a><a href="https://other.test/">Other site</a></body></html>'

    async def close(self):
        self.closed = True

    async def bring_to_front(self):
        pass


class EdgeContext:
    def __init__(self):
        self.pages, self.visited = [], []

    async def new_page(self):
        page = Page(self)
        self.pages.append(page)
        return page


class LocalCrawlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch('copilot_agent.local_crawler.knowledge_root', return_value=self.root / 'knowledge')
        self.patch.start()
        self.browser = SimpleNamespace(context=EdgeContext())
        self.context = {'browser': self.browser, 'config': SimpleNamespace(),
                        'session_dir': self.root / 'session', 'approved': True,
                        'cancel_event': threading.Event()}

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def test_actual_crawl4ai_uses_connected_context_and_saves_readable_pages(self):
        outcome = await crawl_websites({'urls': ['https://internal.test/'], 'title': 'Operations'}, self.context)
        self.assertEqual('completed', outcome['status'])
        self.assertEqual(2, outcome['saved_pages'])
        self.assertEqual(['https://internal.test/', 'https://internal.test/second'], self.browser.context.visited)
        index = json.loads(Path(outcome['index_path']).read_text(encoding='utf-8'))
        page = json.loads(Path(index['pages']['https://internal.test/second']['path']).read_text(encoding='utf-8'))
        self.assertIn('Second page knowledge', page['markdown'])
        self.assertIn('<h1>', page['html'])
        self.assertTrue(all(item.closed for item in self.browser.context.pages))
        self.assertIn('Operations', read_knowledge({'path': outcome['index_path']}, self.context)['content'])

    async def test_page_budget_resumes_remaining_frontier(self):
        args = {'urls': ['https://internal.test/'], 'title': 'Resumable', 'max_pages': 1}
        first = await crawl_websites(args, self.context)
        self.assertEqual('partial', first['status'])
        second = await crawl_websites({**args, 'max_pages': 0}, self.context)
        self.assertEqual('completed', second['status'])
        self.assertEqual(2, second['saved_pages'])
        self.assertEqual(1, self.browser.context.visited.count('https://internal.test/'))

    async def test_changed_title_reuses_same_site_folder_and_saved_frontier(self):
        first = await crawl_websites({'urls': ['https://internal.test/'], 'title': 'First title', 'max_pages': 1}, self.context)
        second = await crawl_websites({'urls': ['https://internal.test/'], 'title': 'Better title'}, self.context)
        self.assertEqual(first['index_path'], second['index_path'])
        self.assertIn('sites', Path(second['index_path']).parts)
        self.assertEqual(self.browser.context.visited.count('https://internal.test/'), 1)
        self.assertEqual(second['saved_pages'], 2)
        self.assertEqual(second['evidence_kind'], 'raw_task_evidence_not_reusable_knowledge')

    async def test_multiple_origin_pages_are_stored_in_their_respective_site_folders(self):
        result = await crawl_websites({'urls': ['https://first.test/', 'https://second.test/'],
                                      'title': 'Two sites', 'max_pages': 2}, self.context)
        index = json.loads(Path(result['index_path']).read_text(encoding='utf-8'))
        self.assertIn('campaigns', Path(result['index_path']).parts)
        first = Path(index['pages']['https://first.test/']['path'])
        second = Path(index['pages']['https://second.test/']['path'])
        self.assertNotEqual(first.parent, second.parent)
        self.assertIn('sites', first.parts)
        self.assertIn('sites', second.parts)
        self.assertIn('first.test', str(first))
        self.assertIn('second.test', str(second))

    async def test_repeated_cycles_refresh_without_new_browser(self):
        outcome = await crawl_websites({'urls': ['https://internal.test/'], 'title': 'Repeated',
            'cycles': 2, 'refresh_seconds': 0}, self.context)
        self.assertEqual('completed', outcome['status'])
        self.assertEqual(2, outcome['cycles_completed'])
        self.assertEqual(2, self.browser.context.visited.count('https://internal.test/'))

    async def test_login_form_does_not_become_saved_knowledge(self):
        outcome = await crawl_websites({'urls': ['https://internal.test/private'], 'title': 'Login'}, self.context)
        self.assertEqual('partial', outcome['status'])
        self.assertEqual(0, outcome['saved_pages'])
        self.assertEqual(1, outcome['failed_pages'])

    async def test_long_knowledge_and_runtime_paths_work(self):
        long_root = self.root / ('shared-folder-' * 6) / ('project-folder-' * 6) / ('knowledge-folder-' * 6)
        context = {**self.context, 'session_dir': long_root / 'sessions' / 'run-one'}
        with patch('copilot_agent.local_crawler.knowledge_root', return_value=long_root / 'knowledge'):
            result = await crawl_websites({'urls': ['https://internal.test/'], 'title': 'Long shared paths'}, context)
            self.assertEqual('completed', result['status'])
            self.assertGreater(len(result['index_path']), 260)
            self.assertIn('Long shared paths', read_knowledge({'path': result['index_path']}, context)['content'])

    def test_saved_html_keeps_business_form_data_but_omits_credentials_and_scripts(self):
        from copilot_agent.local_crawler import saved_html
        document = '<html><body><h1>Navigation</h1><script>secretToken="private";</script><input type="hidden" value="secret"><input type="password" value="private"><input name="customer-name" value="Customer name"><textarea>Customer notes</textarea><a onclick="send()" data-token="private" href="/next">Next</a></body></html>'
        result = saved_html(document)
        self.assertIn('Navigation', result)
        self.assertIn('href="/next"', result)
        self.assertNotIn('private', result)
        self.assertNotIn('secret', result)
        self.assertNotIn('onclick', result)
        self.assertIn('value="Customer name"', result)
        self.assertIn('Customer notes', result)

    async def test_stop_retains_index_and_pending_routes(self):
        self.context['cancel_event'].set()
        outcome = await crawl_websites({'urls': ['https://internal.test/'], 'title': 'Stopped'}, self.context)
        self.assertEqual('cancelled', outcome['status'])
        self.assertEqual(1, outcome['pending_pages'])

    async def test_stop_cancels_inflight_page_without_waiting_for_page_timeout(self):
        started = asyncio.Event()
        original_new_page = self.browser.context.new_page
        async def new_page():
            page = await original_new_page()
            async def wait_forever(*args, **kwargs):
                started.set()
                await asyncio.Event().wait()
            page.goto = wait_forever
            return page
        self.browser.context.new_page = new_page
        running = asyncio.create_task(crawl_websites({'urls': ['https://internal.test/'], 'title': 'Active stop'}, self.context))
        await asyncio.wait_for(started.wait(), 5)
        self.context['cancel_event'].set()
        outcome = await asyncio.wait_for(running, 2)
        self.assertEqual('cancelled', outcome['status'])
        self.assertEqual(1, outcome['pending_pages'])
        self.assertTrue(all(page.closed for page in self.browser.context.pages))

    async def test_tool_registry_calls_real_crawler(self):
        result = await ToolRegistry().execute('crawl4ai.crawl',
            {'urls': ['https://internal.test/'], 'title': 'Callable'}, self.context)
        self.assertTrue(result['ok'], result)
        self.assertEqual(2, result['result']['saved_pages'])

    async def test_read_chunks_and_reject_outside_storage(self):
        from copilot_agent.policy import PolicyError
        folder = self.root / 'knowledge'
        folder.mkdir()
        file = folder / 'large.json'
        file.write_text('x' * 10000)
        first = read_knowledge({'path': str(file), 'limit': 8000}, self.context)
        second = read_knowledge({'path': str(file), 'offset': first['next_offset']}, self.context)
        self.assertEqual(10000, len(first['content']) + len(second['content']))
        with self.assertRaises(PolicyError):
            read_knowledge({'path': str(self.root / 'outside.txt')}, self.context)

    async def test_guided_login_titles_and_multiple_sites(self):
        answers = iter(['yes', 'https://internal.test/', 'First site', '', '1',
                        'https://second.test/', 'Second site', '', '1', ''])
        report = []
        result = await guided_discovery(self.context['config'], self.browser, self.context['session_dir'],
            AsyncMock(side_effect=lambda _: next(answers)), report.append)
        self.assertEqual(['First site', 'Second site'], [item['title'] for item in result])
        self.assertTrue(all(Path(item['index_path']).exists() for item in result))
        self.assertTrue(all(page.closed for page in self.browser.context.pages))

    async def test_guided_continuous_stop_keeps_path_and_frontier(self):
        answers = iter(['yes', 'https://internal.test/', 'Keep refreshing', '', '2', '', ''])
        async def ask(prompt):
            if 'Discovery is running' in prompt:
                await asyncio.sleep(.05)
            return next(answers)
        result = await guided_discovery(self.context['config'], self.browser, self.context['session_dir'], ask, lambda _: None)
        self.assertEqual(1, len(result))
        self.assertTrue(Path(result[0]['index_path']).exists())
        self.assertTrue(all(page.closed for page in self.browser.context.pages))

    async def test_registry_crawl4ai_read_can_inspect_accessible_files_outside_roots(self):
        external = self.root / 'outside-project' / 'large-source.md'
        external.parent.mkdir()
        external.write_text('outside-root evidence ' * 3000, encoding='utf-8')
        result = await ToolRegistry().execute('crawl4ai.read',
            {'path': str(external), 'limit': 8000}, self.context)
        self.assertTrue(result['ok'], result)
        self.assertEqual(str(external.resolve()), result['result']['path'])
        self.assertEqual(8000, len(result['result']['content']))
        self.assertIsNotNone(result['result']['next_offset'])

    async def test_escaped_content_windows_have_no_gaps_after_registry_projection(self):
        folder = self.root / 'knowledge'
        folder.mkdir()
        file = folder / 'escaped.json'
        content = ('\\\"\n' * 10000)
        file.write_text(content, encoding='utf-8', newline='')
        cursor, chunks = 0, []
        while True:
            result = await ToolRegistry().execute('crawl4ai.read', {'path': str(file), 'offset': cursor}, self.context)
            self.assertTrue(result['ok'], result)
            self.assertNotIn('truncated', result['result'])
            chunks.append(result['result']['content'])
            cursor = result['result']['next_offset']
            if cursor is None:
                break
        self.assertEqual(content, ''.join(chunks))

    async def test_orchestrator_exposes_callable_crawl_and_returns_saved_paths(self):
        from copilot_agent.orchestrator import Orchestrator
        from tests.test_orchestrator import MockBrowser, final_response, tool_response
        from tests.test_protocol_state import make_fixture
        root, config, state, _ = make_fixture('orchestrator-local-crawl-')
        config._continuous_package_session = True
        config._package_review_enabled = False
        browser = MockBrowser([final_response, lambda message: tool_response(message,
            name='crawl4ai.crawl', call_id='crawl-local',
            arguments={'urls': ['https://internal.test/'], 'title': 'Agent discovery'}), final_response])
        browser.context = self.browser.context
        agent = Orchestrator(config, browser, ToolRegistry(), state,
            approval_decider=lambda _: 'deny', display=lambda _: None)
        await agent.initialize()
        result = await agent.turn('Read the local website with Crawl4AI.')
        self.assertEqual('complete', result['completion_status'])
        outcome = state.data['calls']['crawl-local']['result']
        self.assertTrue(outcome['ok'], outcome)
        self.assertEqual(2, outcome['result']['saved_pages'])
        self.assertTrue(Path(outcome['result']['index_path']).exists())

    async def test_real_edge_retains_signed_in_context_and_existing_chat_tab(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            native = await playwright.chromium.launch(channel='msedge', headless=True)
            try:
                connected = await native.new_context()
                await connected.add_cookies([{'name': 'fixture-session', 'value': 'synthetic-only',
                    'domain': 'fixture.test', 'path': '/'}])
                chat = await connected.new_page()
                async def serve(route):
                    self.assertIn('fixture-session=synthetic-only', route.request.headers.get('cookie', ''))
                    path = route.request.url.removeprefix('https://fixture.test')
                    page = '<html><body><h1>Signed-in fixture</h1><p>' + ('Rendered company knowledge. ' * 12) + '</p>'
                    if path == '/':
                        page += '<a href="/next">Next</a>'
                    await route.fulfill(status=200, content_type='text/html', body=page + '</body></html>')
                await connected.route('**/*', serve)
                context = {**self.context, 'browser': SimpleNamespace(context=connected)}
                outcome = await crawl_websites({'urls': ['https://fixture.test/'], 'title': 'Real Edge'}, context)
                self.assertEqual('completed', outcome['status'])
                self.assertEqual(2, outcome['saved_pages'])
                self.assertFalse(chat.is_closed())
                self.assertEqual('about:blank', chat.url)
                self.assertEqual([chat], connected.pages)
                self.assertEqual('synthetic-only', (await connected.cookies())[0]['value'])
            finally:
                await native.close()

    async def test_startup_mode_resets_and_is_not_persisted_config(self):
        from copilot_agent.config import Config
        config = Config(root=self.root)
        await choose_package_mode(config, AsyncMock(return_value='2'), lambda _: None)
        self.assertFalse(config._package_review_enabled)
        self.assertTrue(config._continuous_package_session)
        self.assertNotIn('_continuous_package_session', config.as_dict())
        fresh = Config(root=self.root)
        await choose_package_mode(fresh, AsyncMock(return_value='1'), lambda _: None)
        self.assertTrue(fresh._package_review_enabled)
        self.assertFalse(fresh._continuous_package_session)

    def test_url_requires_http_without_embedded_credentials(self):
        for url in ('file:///C:/private', 'https://user:secret@example.com/', 'javascript:alert(1)'):
            with self.assertRaises(ValueError):
                website_url(url)
