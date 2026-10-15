import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.browser_inspection import execute_inspection
from copilot_agent.screenshot_evidence import METRICS
from copilot_agent.policy import PathPolicy
from copilot_agent.tools import ToolRegistry
from tests import test_web_navigation as navigation_fixtures


class InspectionConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_dom_and_screenshot_really_start_in_parallel_and_partial_results_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            dom_started, image_started = asyncio.Event(), asyncio.Event()
            async def dom(*args):
                if args[0] == METRICS:
                    return {'x': 0, 'y': 0, 'width': 800, 'height': 600, 'maxY': 0}
                if args[0].startswith('(p)=>window.scrollTo'):
                    return None
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
        self.context['pending_file_attachments'] = []
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
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertEqual(hashlib.sha256(data).hexdigest(), screenshot['sha256'])
        self.assertEqual([screenshot['path']], self.context['pending_file_attachments'])
        self.assertEqual([], self.context['pending_image_attachments'])

    async def test_scroll_element_and_precise_region_batch_is_one_labeled_pdf(self):
        await self.fixture.page.set_content('''<style>body{margin:0}#details{margin-top:1400px;width:320px;height:180px;background:red}#panel{height:100px;width:300px;overflow:auto}#panel div{height:800px}</style><h1>Top</h1><div id="panel"><div>Scrollable panel</div></div><section id="details">Requested detail</section>''')
        await self.fixture.page.evaluate('window.scrollTo(0,150)')
        response = await self.registry.execute('browser.screenshot', {'shots': [
            {'label': 'Top of page', 'scroll_y': 0},
            {'label': 'Precise top region', 'scroll_y': 0, 'clip': {'x': 0, 'y': 0, 'width': 300, 'height': 100}},
            {'label': 'Scrollable panel interior', 'scroll_container': '#panel', 'scroll_y': 250, 'selector': '#panel'},
            {'label': 'Requested red details', 'selector': '#details'}]}, self.context)
        self.assertTrue(response['ok'], response)
        result = response['result']
        self.assertEqual(4, result['screenshot']['pictures'])
        self.assertEqual(['viewport', 'clip', 'element', 'element'], [shot['kind'] for shot in result['shots']])
        self.assertEqual((300, 100), (result['shots'][1]['width'], result['shots'][1]['height']))
        self.assertEqual(250, result['shots'][2]['container']['y'])
        self.assertEqual(320, result['shots'][3]['width'])
        self.assertEqual(150, await self.fixture.page.evaluate('scrollY'))
        self.assertEqual(0, await self.fixture.page.locator('#panel').evaluate('(n)=>n.scrollTop'))
        self.assertEqual([result['screenshot']['path']], self.context['pending_file_attachments'])
        data = Path(result['screenshot']['path']).read_bytes()
        self.assertEqual(4, data.count(b'/Type /Page\n'))
        self.assertTrue(data.rstrip().endswith(b'%%EOF'))
        self.context['pending_file_attachments'].clear()
        automatic = await self.registry.execute('browser.screenshot', {}, self.context)
        self.assertTrue(automatic['ok'], automatic)
        self.assertEqual(3, automatic['result']['screenshot']['pictures'])
        positions = [shot['scroll']['y'] for shot in automatic['result']['shots']]
        self.assertEqual(0, positions[0])
        self.assertGreater(positions[1], positions[0])
        self.assertGreater(positions[2], positions[1])
        self.assertEqual(150, await self.fixture.page.evaluate('scrollY'))
        self.assertEqual(1, len(self.context['pending_file_attachments']))

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
