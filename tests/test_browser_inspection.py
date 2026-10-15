import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.browser_inspection import execute_inspection
from copilot_agent.policy import PathPolicy
from copilot_agent.tools import ToolRegistry
from tests import test_web_navigation as navigation_fixtures


class InspectionConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_dom_and_screenshot_really_start_in_parallel_and_partial_results_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            dom_started, image_started = asyncio.Event(), asyncio.Event()
            async def dom(*args):
                dom_started.set()
                await image_started.wait()
                return {'dom': {'nodes': []}}
            async def screenshot(**kwargs):
                image_started.set()
                await dom_started.wait()
                raise RuntimeError('Synthetic screenshot failure')
            page = SimpleNamespace(url='https://fixture.test/', evaluate=dom,
                                   screenshot=screenshot, locator=lambda _: object())
            with patch('copilot_agent.browser_inspection.get_navigation_page', return_value=page), \
                 patch('copilot_agent.browser_inspection._install_origin_guard', new=AsyncMock()):
                result = await asyncio.wait_for(execute_inspection('browser.inspect', {},
                    {'approved': True, 'session_dir': directory}), 2)
            self.assertEqual('partial', result['status'])
            self.assertIn('structure', result)
            self.assertFalse(result['side_effects_uncertain'])
            self.assertEqual(result, json.loads(Path(result['artifact_path']).read_text(encoding='utf-8')))


class InspectionBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = navigation_fixtures.NavigationBrowserTests()
        await self.fixture.asyncSetUp()
        self.addAsyncCleanup(self.fixture.asyncTearDown)
        self.context = self.fixture.context
        self.context['policy'] = PathPolicy([self.context['session_dir']])
        self.context['pending_image_attachments'] = []
        self.registry = ToolRegistry()

    async def test_dom_shadow_forms_api_metadata_and_real_image_are_delivered_together(self):
        await self.fixture.page.evaluate("async () => { const response = await fetch('/api/status?token=secret-value'); await response.text(); }")
        await self.fixture.page.wait_for_function("performance.getEntriesByType('resource').some(r => r.name.includes('/api/status'))")
        response = await self.registry.execute('browser.inspect', {'max_nodes': 300}, self.context)
        self.assertTrue(response['ok'], response)
        result = response['result']
        self.assertTrue(result['parallel_capture'])
        self.assertTrue(result['same_url_during_capture'])
        self.assertTrue(any(n['shadow'] and n['label'] == 'Shadow action' for n in result['structure']['dom']['nodes']))
        self.assertTrue(result['structure']['application']['forms'])
        apis = result['structure']['application']['api_candidates']
        self.assertTrue(any(item['url'].endswith('/api/status') for item in apis), apis)
        self.assertNotIn('secret-value', json.dumps(result))
        screenshot = result['screenshot']
        data = Path(screenshot['path']).read_bytes()
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(hashlib.sha256(data).hexdigest(), screenshot['sha256'])
        self.assertEqual([screenshot['path']], self.context['pending_image_attachments'])

    async def test_javascript_arguments_spa_navigation_and_uncertain_effects(self):
        response = await self.registry.execute('browser.javascript', {
            'expression': '(value) => { history.pushState({}, "", "/app/profile"); document.querySelector("h1").textContent=value; return {heading: document.querySelector("h1").textContent}; }',
            'argument': 'Observed profile'}, self.context)
        self.assertTrue(response['ok'], response)
        self.assertEqual('Observed profile', response['result']['value']['heading'])
        self.assertTrue(response['result']['url_after'].endswith('/app/profile'))
        failed = await self.registry.execute('browser.javascript', {
            'expression': '() => { window.partialEffect = true; throw new Error("Inspect partial effect"); }'}, self.context)
        self.assertFalse(failed['ok'])
        self.assertTrue(failed['result']['side_effects_uncertain'])
        self.assertIn('Inspect partial effect', failed['result']['error']['message'])
        self.assertTrue(await self.fixture.page.evaluate('window.partialEffect'))
