import asyncio
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.rea_python_page import SNAPSHOT, inspect_page


class Page:
    def __init__(self):
        self.url = 'https://fixture.test/users/customer-secret?token=query-secret'
        self.frames = [SimpleNamespace(url=self.url)]
        self.listeners = {}
        self.evaluate = AsyncMock(side_effect=self.snapshot)

    def on(self, event, listener):
        self.listeners[event] = listener

    def remove_listener(self, event, listener):
        if self.listeners[event] is not listener:
            raise AssertionError('Unexpected listener')
        del self.listeners[event]

    async def snapshot(self, expression):
        self.listeners['response'](SimpleNamespace(url='https://fixture.test/api/users/123?token=network-secret', status=200,
            request=SimpleNamespace(method='GET', resource_type='fetch')))
        return {'url': self.url, 'ready_state': 'complete',
                'dom': {'tags': {'button': 2, 'input': 1, 'malicious-secret': 1}, 'roles': {'button': 1}, 'input_types': {'password': 1}, 'visited_elements': 10},
                'forms': [{'action': 'https://fixture.test/auth?secret=form-secret', 'method': 'post', 'field_count': 2, 'name': 'field-secret'}],
                'scripts': [{'src': 'https://fixture.test/js/bundle-secret.js?key=script-secret', 'inline': False}],
                'resources': [{'url': 'https://fixture.test/api/users/456?token=resource-secret', 'kind': 'fetch', 'duration_ms': 3}],
                'navigation': ['https://fixture.test/users/alice-secret?key=link-secret'],
                'framework_hints': ['React', 'framework-secret'], 'title': 'customer-title-secret'}


class PythonPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_supplied_page_metadata_and_redaction(self):
        page = Page()
        result = await inspect_page(page, 0)
        self.assertEqual('partial', result['status'])
        facts = result['findings']
        self.assertEqual(2, facts['dom']['tag_counts']['button'])
        self.assertEqual(1, facts['dom']['input_type_counts']['password'])
        self.assertEqual('GET', facts['network_responses'][0]['method'])
        self.assertEqual('2xx', facts['network_responses'][0]['status_class'])
        self.assertEqual(['React'], facts['framework_hints'])
        self.assertEqual({}, page.listeners)
        self.assertEqual(page.url, 'https://fixture.test/users/customer-secret?token=query-secret')
        self.assertEqual(1, page.evaluate.await_count)
        serialized = json.dumps(result)
        for secret in ('customer-secret', 'query-secret', 'network-secret', 'malicious-secret', 'field-secret', 'script-secret', 'bundle-secret', 'resource-secret', 'alice-secret', 'link-secret', 'framework-secret', 'customer-title-secret'):
            self.assertNotIn(secret, serialized)
        # The evaluated program never asks for authentication material or user content.
        for forbidden in ('document.cookie', 'localStorage', 'sessionStorage', '.innerText', '.textContent', '.value', '.click(', '.fetch(', '.scrollTo(', '.focus('):
            self.assertNotIn(forbidden, SNAPSHOT)

    async def test_listener_cleanup_on_error_and_cancellation(self):
        page = Page()
        page.evaluate = AsyncMock(side_effect=ValueError('synthetic'))
        with self.assertRaises(ValueError):
            await inspect_page(page, 0)
        self.assertEqual({}, page.listeners)
        page = Page()
        page.evaluate = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await inspect_page(page, 0)
        self.assertEqual({}, page.listeners)

    async def test_cleanup_failure_is_explicit_without_exception_details(self):
        page = Page()
        def broken(*args):
            raise RuntimeError('secret-private-system-path')
        page.remove_listener = broken
        with self.assertRaisesRegex(RuntimeError, 'cleanup could not be confirmed') as caught:
            await inspect_page(page, 0)
        self.assertNotIn('secret-private', str(caught.exception))

    async def test_bounds_budget_and_truncation(self):
        page = Page()
        for value in (-1, 3001, True, '500'):
            with self.assertRaises(ValueError):
                await inspect_page(page, value)
        def exhausted():
            raise TimeoutError('Budget exhausted')
        with self.assertRaises(TimeoutError):
            await inspect_page(page, 0, exhausted)
        original = page.snapshot
        async def large(expression):
            result = await original(expression)
            result['dom']['truncated'] = True
            result['resources'] *= 1100
            return result
        page.evaluate = AsyncMock(side_effect=large)
        result = await inspect_page(page, 0)
        self.assertEqual(1000, len(result['findings']['resources']))
        self.assertTrue(any('limit' in gap for gap in result['unknowns']))


class PythonPageBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_python_page_uses_owned_adapter_and_never_probes_node(self):
        from playwright.async_api import async_playwright
        from jsonschema import Draft202012Validator
        from copilot_agent.browser import BrowserAdapter
        from copilot_agent.policy import PathPolicy
        from copilot_agent.tools import ToolRegistry
        with tempfile.TemporaryDirectory(prefix='rea_page_registry_') as directory:
            root = Path(directory).resolve()
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0))
                port = reserve.getsockname()[1]
            async with async_playwright() as playwright:
                native = await playwright.chromium.launch(channel='msedge', headless=True,
                    args=['--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={port}'])
                try:
                    browser = BrowserAdapter(SimpleNamespace(allowed_domains=['fixture.test'], debug_port=port))
                    browser.browser = native
                    browser.tool_context = await native.new_context(service_workers='block')
                    browser.context = browser.tool_context
                    browser.tool_page = await browser.tool_context.new_page()
                    await browser._configure_tool_context(browser.tool_page)
                    async def serve(route):
                        await route.fulfill(status=200, content_type='text/html', body='''<main><h1>private-customer-secret</h1><form method="post" action="/auth?token=form-secret"><input type="password" value="password-secret"><button type="button" onclick="window.mutations++">private-button-secret</button></form><a href="/users/777?token=query-secret">private-label-secret</a></main><script>window.mutations=0;document.cookie='session=cookie-secret';localStorage.setItem('token','storage-secret')</script>''')
                    await browser.tool_context.route('https://fixture.test/**', serve)
                    await browser.tool_page.route('https://fixture.test/**', serve)
                    await browser.tool_page.goto('https://fixture.test/')
                    before = await browser.tool_page.content()
                    config = {'root': str(Path(__file__).resolve().parents[1]), 'rea_backend': 'python_native',
                              'allowed_domains': ['fixture.test'], 'allowed_roots': [str(root)],
                              'rea_timeout_seconds': 10, 'rea_max_parallel': 1}
                    context = {'browser': browser, 'config': config, 'session_dir': str(root / 'session'),
                               'path_policy': PathPolicy([root]), '_rea_runtime': {}}
                    registry = ToolRegistry(config)
                    with patch('copilot_agent.rea._node_health', side_effect=AssertionError('Node must never be probed')) as node_health:
                        output = await registry.execute('rea.inspect_page', {'observation_ms': 0}, context)
                        definition = registry.definition('rea.inspect_page')
                        node_health.assert_not_called()
                    Draft202012Validator(definition['output_schema']).validate(output)
                    result = output['result']
                    self.assertEqual('python_native', result['backend'])
                    self.assertEqual('partial', result['status'])
                    self.assertEqual(1, result['findings']['dom']['tag_counts']['button'])
                    self.assertTrue(result['findings']['forms'])
                    self.assertEqual(before, await browser.tool_page.content())
                    self.assertEqual(0, await browser.tool_page.evaluate('window.mutations'))
                    self.assertTrue(native.is_connected())
                    self.assertFalse(browser.tool_page.is_closed())
                    evidence = Path(result['evidence_path'])
                    if not evidence.is_absolute():
                        evidence = Path(context['session_dir']) / evidence
                    public = json.dumps(result) + evidence.read_text(encoding='utf-8')
                    for value in ('private-customer-secret', 'password-secret', 'private-button-secret', 'private-label-secret', 'form-secret', 'query-secret', 'cookie-secret', 'storage-secret', str(root), root.as_posix()):
                        self.assertNotIn(value, public)
                finally:
                    await native.close()

    async def test_real_owned_page_is_observed_without_mutation_or_content(self):
        from tests.test_web_navigation import NavigationBrowserTests
        fixture = NavigationBrowserTests()
        await fixture.asyncSetUp()
        self.addAsyncCleanup(fixture.asyncTearDown)
        page = fixture.page
        await page.set_content('''<h1>customer-title-secret</h1><main><form action="/auth?token=form-secret" method="post"><input name="customer-secret" value="record-secret"><input type="password" value="credential-secret"><button type="button" onclick="window.mutationCount++">Click</button></form><a href="/users/123?token=link-secret">private-label-secret</a></main><script>window.mutationCount=0;document.cookie='credential=cookie-secret';localStorage.setItem('token','storage-secret')</script>''')
        before = await page.content()
        result = await inspect_page(page, 0)
        self.assertEqual(before, await page.content())
        self.assertEqual(0, await page.evaluate('window.mutationCount'))
        self.assertEqual(2, result['findings']['dom']['tag_counts']['input'])
        self.assertEqual(1, result['findings']['dom']['input_type_counts']['password'])
        self.assertEqual('post', result['findings']['forms'][0]['method'])
        text = json.dumps(result)
        for value in ('customer-title-secret', 'form-secret', 'customer-secret', 'record-secret', 'credential-secret', 'link-secret', 'private-label-secret', 'cookie-secret', 'storage-secret'):
            self.assertNotIn(value, text)


if __name__ == '__main__':
    unittest.main()
