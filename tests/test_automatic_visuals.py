import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch, Mock

from PIL import Image
from copilot_agent.automatic_visuals import capture_visuals, execute_with_visuals, merge_visual_pages, SCROLL_PANEL, paired_browser_action, capture_action_phase


class VisualsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_during_before_capture_never_dispatches_action(self):
        from copilot_agent.web_navigation import NavigationStop
        event = threading.Event()
        action = AsyncMock()
        async def phase(page, context, label, phase, action_id):
            if phase == 'before':
                event.set()
        with patch('copilot_agent.automatic_visuals.capture_action_phase', side_effect=phase):
            with self.assertRaises(NavigationStop):
                await paired_browser_action(None, {'cancel_event': event}, 'click', action)
        action.assert_not_awaited()
    async def test_existing_discovery_and_research_merge_one_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            context = {'session_dir': folder, 'source_request_id': 'r1', 'pending_visual_attachments': []}
            record = {'label': 'Discovered page', 'url': 'https://example.com/',
                      'scroll': {'x': 0, 'y': 0}, 'kind': 'viewport'}
            with Image.new('RGB', (300, 200), 'white') as image:
                first = await merge_visual_pages([(record, image)] * 8, context)
                second = await merge_visual_pages([(record, image)] * 8, context)
            self.assertEqual(first['path'], second['path'])
            self.assertEqual(second['pictures'], 12)
            self.assertEqual(context['pending_visual_attachments'], [first['path']])

    async def test_registry_attaches_visual_result_without_explicit_request(self):
        from copilot_agent.tools import ToolRegistry
        registry = ToolRegistry()
        with tempfile.TemporaryDirectory() as folder, patch.object(registry, 'validate_call'), \
                patch.object(registry, '_execute', new=AsyncMock(return_value={'status': 'observed'})), \
                patch('copilot_agent.automatic_visuals.capture_action_phase', new=AsyncMock()), \
                patch('copilot_agent.automatic_visuals.flush_visual_context', new=AsyncMock(return_value={
                    'status': 'captured', 'pictures': 5, 'queued_for_copilot': True})):
            result = await registry.execute('browser.recon', {}, {'session_dir': folder, 'approved': True})
        self.assertTrue(result['ok'])
        self.assertEqual(result['result']['visual_context']['pictures'], 5)

    async def test_action_runs_once_between_before_after_even_on_failure(self):
        events = []
        async def phase(page, context, label, phase, action_id):
            events.append(phase)
        async def action():
            events.append('action')
            raise ValueError('action failed')
        with patch('copilot_agent.automatic_visuals.capture_action_phase', side_effect=phase):
            with self.assertRaises(ValueError):
                await paired_browser_action(None, {}, 'plan step click', action)
        self.assertEqual(events, ['before', 'action', 'after'])

    async def test_action_pairs_bypass_discovery_sample_cap(self):
        pixels = BytesIO()
        Image.new('RGB', (300, 200), 'white').save(pixels, 'PNG')
        page = Mock(url='https://example.com/page', is_closed=Mock(return_value=False))
        page.screenshot = AsyncMock(return_value=pixels.getvalue())
        with tempfile.TemporaryDirectory() as folder, patch('copilot_agent.automatic_visuals._url_policy'):
            context = {'session_dir': folder, 'source_call_id': 'call-1'}
            for sequence in range(8):
                await capture_action_phase(page, context, 'click', 'before', str(sequence))
                await capture_action_phase(page, context, 'click', 'after', str(sequence))
            result = await merge_visual_pages([], context)
        self.assertEqual(result['pictures'], 16)
        self.assertTrue(result['queued_for_copilot'])
        self.assertIn('BEFORE', result['captions'][0])
        self.assertIn('AFTER', result['captions'][1])

    async def test_scrolls_only_independent_owned_revisit(self):
        pixels = BytesIO()
        Image.new('RGB', (300, 200), 'white').save(pixels, 'PNG')
        page, clone = Mock(url='https://example.com/page'), Mock(url='https://example.com/page')
        for item in (page, clone):
            item.screenshot = AsyncMock(return_value=pixels.getvalue())
            item.evaluate = AsyncMock(side_effect=lambda script, *args: [] if 'querySelectorAll' in script and script != SCROLL_PANEL else
                {'x': 0, 'y': 0, 'maxY': 400, 'width': 300, 'height': 200})
        clone.goto, clone.close = AsyncMock(), AsyncMock()
        browser = Mock(new_tool_page=AsyncMock(return_value=clone))
        with tempfile.TemporaryDirectory() as folder, patch('copilot_agent.automatic_visuals._url_policy'), \
                patch('copilot_agent.automatic_visuals._install_origin_guard', new=AsyncMock()):
            result = await capture_visuals(page, {'session_dir': folder, 'browser': browser}, label='REA')
        self.assertEqual(result['pictures'], 7)
        self.assertTrue(any('internal scrolling panel' in caption for caption in result['captions']))
        self.assertFalse(any('scrollTo' in call.args[0] for call in page.evaluate.await_args_list))
        self.assertTrue(any('scrollTo' in call.args[0] for call in clone.evaluate.await_args_list))
        clone.close.assert_awaited_once()

    async def test_real_pdf_batches_and_twelve_picture_cap(self):
        pixels = BytesIO()
        Image.new('RGB', (300, 200), 'white').save(pixels, 'PNG')
        page = Mock(url='https://example.com/page')
        page.screenshot = AsyncMock(return_value=pixels.getvalue())
        page.evaluate = AsyncMock(side_effect=lambda script: [] if 'querySelectorAll' in script else
            {'x': 0, 'y': 0, 'maxY': 0, 'width': 300, 'height': 200})
        with tempfile.TemporaryDirectory() as folder, patch('copilot_agent.automatic_visuals._url_policy'):
            context = {'session_dir': folder, 'source_request_id': 'r1', 'pending_visual_attachments': []}
            for index in range(6):
                result = await capture_visuals(page, context, label=f'page-{index}', revisit=False)
            self.assertEqual(result['pictures'], 12)
            self.assertEqual(len(context['pending_visual_attachments']), 1)
            self.assertTrue(Path(result['path']).read_bytes().startswith(b'%PDF'))
            self.assertEqual(page.screenshot.await_count, 12)
            context['source_request_id'] = 'r2'
            second = await capture_visuals(page, context, label='next batch', revisit=False)
            self.assertEqual(second['pictures'], 3)
            self.assertNotEqual(result['path'], second['path'])

    async def test_capture_and_investigation_overlap(self):
        started = asyncio.Event()
        async def capture(*args):
            started.set()
            await asyncio.sleep(.01)
            return {'status': 'captured'}
        async def operation():
            await asyncio.wait_for(started.wait(), 1)
            return {'status': 'completed'}
        with patch('copilot_agent.automatic_visuals._safe_capture', side_effect=capture):
            result = await execute_with_visuals('rea.inspect_page', {}, {}, operation)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['visual_context']['status'], 'captured')

    async def test_failed_investigation_cancels_visual_task(self):
        cleaned = asyncio.Event()
        started = asyncio.Event()
        async def capture(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        async def operation():
            await started.wait()
            raise ValueError('failure')
        with patch('copilot_agent.automatic_visuals._safe_capture', side_effect=capture):
            with self.assertRaises(ValueError):
                await execute_with_visuals('rea.inspect_page', {}, {}, operation)
        self.assertTrue(cleaned.is_set())

    async def test_missing_page_is_explicit_and_does_not_block(self):
        async def operation():
            return {'status': 'completed'}
        result = await execute_with_visuals('rea.inspect_page', {}, {}, operation)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['visual_context']['status'], 'unavailable')
        self.assertFalse(result['visual_context']['queued_for_copilot'])
