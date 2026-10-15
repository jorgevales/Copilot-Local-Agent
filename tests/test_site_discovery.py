import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.site_discovery import attachment_slots, discover, settle
from copilot_agent.tools import ToolRegistry
from tests import test_web_navigation as navigation_fixtures


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
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
            await fixture.page.set_content('<nav><button aria-expanded="false" onclick="this.setAttribute(\'aria-expanded\',\'true\');document.querySelector(\'main\').textContent=\'Expanded\'">Menu</button></nav><main>Home</main><script>window.fixture=1</script><iframe srcdoc="<h1>Frame</h1>"></iframe>')
            with tempfile.TemporaryDirectory() as directory:
                context = fixture.context
                context['pending_file_attachments'] = []
                with patch('copilot_agent.site_discovery.knowledge_root', return_value=Path(directory)):
                    result = await discover({'title': 'Fixture', 'max_states': 2, 'max_seconds': 20}, context)
                    self.assertEqual(2, result['states_captured'])
                    self.assertEqual(2, result['visual']['pictures'])
                    self.assertTrue(Path(result['visual']['path']).read_bytes().startswith(b'%PDF-'))
                    checkpoint = json.loads(Path(result['checkpoint']).read_text(encoding='utf-8'))
                    self.assertEqual(2, len(checkpoint['states'][0]['frames']))
                    self.assertIn('source', checkpoint['states'][0]['frames'][0]['resources']['scripts'][0])
                    self.assertEqual(5, len(context['pending_file_attachments']))
                    self.assertIn('to_state', checkpoint['actions'][0])
                    resumed = await discover({'title': 'Fixture', 'max_states': 1, 'explore': False}, context)
                    self.assertEqual(3, resumed['states_captured'])
        finally:
            await fixture.asyncTearDown()
