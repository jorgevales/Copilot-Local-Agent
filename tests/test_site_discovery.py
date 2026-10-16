import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.site_discovery import attachment_slots, discover, settle
from copilot_agent.tools import ToolRegistry
from tests import test_web_navigation as navigation_fixtures


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncertain_discovery_cannot_receive_completed_call_status(self):
        from copilot_agent.state import SessionState
        with tempfile.TemporaryDirectory() as directory:
            state = SessionState(Path(directory) / 'session')
            registry = ToolRegistry()
            call = {'call_id': 'discover-fixture', 'name': 'browser.discover', 'version': '1.0',
                    'arguments': {'title': 'Synthetic discovery'}}
            context = {'approved': True, 'session_dir': state.directory,
                       'config': {'allowed_roots': [directory]}}
            async def visual(name, args, context, operation):
                return await operation()
            with patch.object(registry, 'validate_call', return_value=None), \
                 patch.object(registry, '_execute', new=AsyncMock(return_value={'status': 'uncertain', 'side_effects_uncertain': True})), \
                 patch('copilot_agent.automatic_visuals.execute_with_visuals', new=visual):
                result = await registry.execute(call['name'], call['arguments'], context)
            state.begin_call(call, state_changing=True)
            state.finish_call(call['call_id'], result)
            self.assertFalse(result['ok'])
            self.assertEqual('uncertain', state.data['calls'][call['call_id']]['status'])

    def test_outer_timeout_covers_the_registered_discovery_budget(self):
        definition = ToolRegistry().definition('browser.discover')
        maximum = definition['input_schema']['properties']['max_seconds']['maximum']
        self.assertGreaterEqual(definition['timeout'], maximum + 90)

    def test_file_budget_includes_existing_attachments(self):
        self.assertEqual(18, attachment_slots([]))
        self.assertEqual(1, attachment_slots(['existing'] * 17))
        self.assertEqual(0, attachment_slots(['existing'] * 20))

    def test_registered_schema(self):
        ToolRegistry().validate_input('browser.discover', {'title': 'Navigation', 'max_states': 3})

    async def test_transient_error_is_observed_until_destination(self):
        page = AsyncMock()
        page.url = 'https://example.test/target'
        page.evaluate.side_effect = [
            {'url': 'https://example.test/error', 'ready': 'complete', 'text': 'Bad gateway'},
            *[{'url': page.url, 'ready': 'complete', 'text': 'Target'}] * 4]
        import time
        events = []
        with patch('copilot_agent.site_discovery.asyncio.sleep', new=AsyncMock()):
            result = await settle(page, time.monotonic()+5, events)
        self.assertEqual('stable', result['outcome'])
        self.assertTrue(events[0]['error_page'])
        self.assertEqual(page.url, events[-1]['url'])

    async def test_real_browser_capture_shared_files_pdf_and_resume(self):
        fixture = navigation_fixtures.NavigationBrowserTests()
        await fixture.asyncSetUp()
        try:
            await fixture.page.set_content('<nav><button aria-label="Cerrar sesión" aria-expanded="false" onclick="window.unsafeClicked=true"></button><button aria-expanded="false" onclick="this.setAttribute(\'aria-expanded\',\'true\');document.querySelector(\'main\').textContent=\'Expanded\'">Menu</button></nav><main>Home</main><script>window.fixture=1</script><iframe srcdoc="<h1>Frame</h1>"></iframe>')
            with tempfile.TemporaryDirectory() as directory:
                context = fixture.context
                context['pending_file_attachments'] = []
                with patch('copilot_agent.site_discovery.knowledge_root', return_value=Path(directory)):
                    result = await discover({'title': 'Fixture', 'max_states': 2, 'max_seconds': 20}, context)
                    self.assertEqual(2, result['states_captured'])
                    self.assertFalse(await fixture.page.evaluate('!!window.unsafeClicked'))
                    self.assertGreaterEqual(result['visual']['pictures'], 2)
                    self.assertLessEqual(result['visual']['pictures'], 12)
                    self.assertTrue(Path(result['visual']['path']).read_bytes().startswith(b'%PDF-'))
                    checkpoint = json.loads(Path(result['checkpoint']).read_text(encoding='utf-8'))
                    self.assertEqual(2, len(checkpoint['states'][0]['frames']))
                    self.assertIn('source', checkpoint['states'][0]['frames'][0]['resources']['scripts'][0])
                    for state in checkpoint['states']:
                        self.assertTrue(Path(state['viewport']['path']).read_bytes().startswith(b'\x89PNG'))
                    self.assertEqual({'00-READ-FIRST.md', '01-COVERAGE.json', '02-PAGE-EVIDENCE.json',
                                      '03-NETWORK-AND-SOURCES.json'},
                                     {Path(path).name for path in context['pending_file_attachments']})
                    self.assertIn(result['visual']['path'], context['pending_visual_attachments'])
                    self.assertIn('to_state', checkpoint['actions'][0])
                    resumed = await discover({'title': 'A clearer title', 'max_states': 1, 'explore': False}, context)
                    self.assertEqual(result['checkpoint'], resumed['checkpoint'])
                    self.assertIn('sites', Path(resumed['checkpoint']).parts)
                    self.assertEqual(resumed['evidence_kind'], 'raw_task_evidence_not_reusable_knowledge')
                    self.assertEqual(3, resumed['states_captured'])
                    context['config']['compact_navigation'] = True
                    context['pending_file_attachments'].clear()
                    compact = await discover({'title': 'Compact', 'max_states': 1, 'explore': False}, context)
                    self.assertTrue(compact['compact'])
                    self.assertEqual([], context['pending_file_attachments'])
                    self.assertEqual([], compact['files'])
                    self.assertTrue(Path(compact['manifest_path']).is_file())
                    self.assertTrue(compact['coverage']['routes'])
                    full = json.loads(Path(compact['manifest_path']).read_text(encoding='utf-8'))
                    self.assertGreater(len(full), 4)
                    last = json.loads(Path(compact['checkpoint']).read_text(encoding='utf-8'))['states'][-1]
                    self.assertEqual('compact', last['frames'][0]['delivered_sources']['mode'])
        finally:
            await fixture.asyncTearDown()
