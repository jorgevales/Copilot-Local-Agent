import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from copilot_agent.orchestrator import Orchestrator
from copilot_agent.policy import PolicyError
from tests.test_orchestrator import MockBrowser, final_response
from tests.test_protocol_state import make_fixture
from copilot_agent.tools import ToolRegistry
from copilot_agent.outbound_results import pack_outbound, composer_characters
from copilot_agent.browser import SubmissionNotSentError
from tests.test_browser import ReadinessAdapter


class PackingTests(unittest.TestCase):
    def fixture(self, content):
        directory = tempfile.TemporaryDirectory(prefix='outbound-packing-')
        self.addCleanup(directory.cleanup)
        message = {'protocol_version': '1.0', 'session_id': 'synthetic-session',
                   'request_id': 'synthetic-request', 'kind': 'tool_results',
                   'context': {'private_history': 'HISTORY-CANARY-NOT-EXPORTED'}, 'content': content}
        return message, Path(directory.name)

    def test_short_response_stays_inline_without_writing_files(self):
        message, directory = self.fixture({'results': []})
        original = json.dumps(message)
        text, paths = pack_outbound(original, [], directory)
        self.assertEqual(original, text)
        self.assertEqual([], paths)
        self.assertEqual([], list(directory.iterdir()))

    def test_multipart_is_lossless_with_offsets_errors_unicode_and_bounded_files(self):
        content = {'results': [{'call_id': 'read', 'tool': 'crawl4ai.read', 'ok': True,
                    'result': {'content': ('Quoted "text"\n' + '\U0001f600') * 10000,
                               'offset': 8000, 'next_offset': 9000}},
                   {'call_id': 'failed', 'tool': 'browser.observe', 'ok': False,
                    'error': 'Synthetic inaccessible page'}], 'instruction': 'Keep all evidence.'}
        message, directory = self.fixture(content)
        text, paths = pack_outbound(json.dumps(message, ensure_ascii=False), [], directory,
                                    max_file_bytes=32768)
        self.assertGreater(len(paths), 1)
        self.assertLess(len(paths), 20)
        self.assertLess(composer_characters(text), 16000)
        parts = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        joined = ''
        for number, (path, part) in enumerate(zip(paths, parts), 1):
            self.assertLessEqual(path.stat().st_size, 32768)
            self.assertEqual(number, part['part'])
            self.assertEqual(len(paths), part['part_count'])
            self.assertEqual(len(joined), part['content_offset'])
            joined += part['content_segment']
            self.assertNotIn('HISTORY-CANARY-NOT-EXPORTED', path.read_text(encoding='utf-8'))
        self.assertEqual(content, json.loads(joined))
        self.assertEqual(1, parts[0]['summary']['failed_result_count'])
        self.assertEqual('crawl4ai.read', parts[0]['result_index'][0]['tool'])

    def test_eighteen_existing_files_share_one_response_slot(self):
        message, directory = self.fixture({'results': [], 'evidence': 'x' * 30000})
        existing = [Path('selected-' + str(index) + '.md') for index in range(18)]
        _, paths = pack_outbound(json.dumps(message), existing, directory)
        self.assertEqual(existing, paths[:18])
        self.assertEqual(19, len(paths))

    def test_exhausted_attachment_slots_fail_before_writing_or_truncating(self):
        message, directory = self.fixture({'evidence': 'x' * 30000})
        with self.assertRaisesRegex(PolicyError, 'nothing was sent or truncated'):
            pack_outbound(json.dumps(message), [Path(str(i) + '.md') for i in range(19)], directory)
        self.assertEqual([], list(directory.iterdir()))

    def test_exhausted_file_size_budget_fails_before_writing(self):
        message, directory = self.fixture({'evidence': 'x' * 100000})
        with self.assertRaisesRegex(PolicyError, 'Nothing was sent or truncated'):
            pack_outbound(json.dumps(message), [], directory, max_file_bytes=4000)
        self.assertEqual([], list(directory.iterdir()))

    def test_utf16_count_matches_browser_for_non_bmp_characters(self):
        self.assertEqual(3, composer_characters('a\U0001f600'))


class LimitedBrowser(MockBrowser):
    async def exchange(self, text, *args, **kwargs):
        if len(text.encode('utf-16-le')) // 2 > 20000:
            raise AssertionError('Send disabled: composer character limit exceeded')
        return await super().exchange(text, *args, **kwargs)


class OutboundResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_resume_compacts_audit_metadata_without_losing_scope_or_pending_effects(self):
        with patch('copilot_agent.policy.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')), \
             patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')):
            _, config, state, _ = make_fixture('outbound-private-resume-')
            agent = Orchestrator(config, LimitedBrowser([]), ToolRegistry(), state, display=lambda _: None)
            history = [{'content_sha256': str(i).zfill(64), 'content_bytes': 328,
                        'website_content_omitted': True} for i in range(28)]
            pending = {'call': {'status': 'uncertain', 'action_hash': 'a' * 64}}
            message = {'protocol_version': '1.0', 'session_id': state.session_id,
                'request_id': 'resume', 'kind': 'user_task', 'content': 'Create a synthetic patient; start but never finish consultation.',
                'context': {'constraints': ['exact-scope-' * 1000], 'pending_operations': pending, 'attachments': history},
                'execution_strategy': {'planning': 'p' * 2000, 'answering': 'a' * 2000,
                                       'target_navigation': 't' * 2000},
                'session_plan_authorization': {'active': True, 'scope': 'user-approved session'}}
            packed, files = await agent._pack_outbound_response(json.dumps(message), [])
        result = json.loads(packed)
        self.assertLess(composer_characters(packed), 15872)
        self.assertEqual([], files)
        self.assertEqual(message['content'], result['content'])
        self.assertEqual(message['context']['constraints'], result['context']['constraints'])
        self.assertEqual(pending, result['context']['pending_operations'])
        self.assertEqual(message['session_plan_authorization'], result['session_plan_authorization'])
        table = result['context']['attachments']
        self.assertEqual(history, [dict(zip(table['columns'], row)) for row in table['rows']])

    async def test_actual_smaller_editor_limit_drives_result_attachment_transport(self):
        with patch('copilot_agent.policy.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')), \
             patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')):
            _, config, state, _ = make_fixture('outbound-small-editor-')
            browser = LimitedBrowser([final_response])
            browser.composer_character_limit = AsyncMock(return_value=6000)
            agent = Orchestrator(config, browser, ToolRegistry(), state, display=lambda _: None)
            content = {'results': [{'tool': 'local_python', 'ok': True, 'result': {'content': 'x' * 10000}}]}
            await agent._send('tool_results', content)
        self.assertLess(composer_characters(browser.sent[0]['wire_text']), 6000)
        self.assertEqual(content, browser.sent[0]['message']['content'])
        self.assertEqual(1, browser.composer_character_limit.await_count)

    async def test_browser_rejects_actual_limit_overflow_before_filling_the_editor(self):
        adapter = ReadinessAdapter()
        adapter.editor.evaluate = AsyncMock(return_value=1000)
        adapter.editor.fill = AsyncMock()
        with self.assertRaises(SubmissionNotSentError):
            await adapter._prepare_submission('req ' + 'x' * 1000, 'req', ())
        adapter.editor.fill.assert_not_awaited()

    async def test_browser_exposes_editor_limit_and_falls_back_if_it_is_unavailable(self):
        adapter = ReadinessAdapter()
        adapter.editor.evaluate = AsyncMock(return_value=8000)
        self.assertEqual(8000, await adapter.composer_character_limit())
        adapter.editor.evaluate = AsyncMock(side_effect=RuntimeError('Synthetic absent attribute'))
        self.assertIsNone(await adapter.composer_character_limit())

    async def test_ten_long_crawler_reads_send_short_text_and_complete_result_attachment(self):
        with patch('copilot_agent.policy.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')), \
             patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')):
            _, config, state, _ = make_fixture('outbound-tool-results-')
            browser = LimitedBrowser([final_response])
            agent = Orchestrator(config, browser, ToolRegistry(), state, display=lambda _: None)
            content = {'results': [{'call_id': f'read-{index}', 'tool': 'crawl4ai.read', 'ok': True,
                'result': {'path': f'page-{index}.json', 'offset': index * 8000,
                    'content': ('Navigation knowledge ðŸ˜€ ' * 350), 'next_offset': None}}
                for index in range(10)], 'instruction': 'Investigate these observed website results.'}
            await agent._send('tool_results', content)
        sent = browser.sent[0]
        self.assertLess(len(sent['wire_text'].encode('utf-16-le')) // 2, 16000)
        files = [path for path in sent['attachments'] if path.name.startswith('tool-results-')]
        self.assertEqual(1, len(files))
        payload = json.loads(files[0].read_text(encoding='utf-8'))
        self.assertEqual(content, payload['content'])
        self.assertEqual(10, payload['summary']['result_count'])
        self.assertLess(len(sent['attachments']), 20)
