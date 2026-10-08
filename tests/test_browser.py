"""Offline contract tests; no browser, file deletion, network, or Copilot send."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from copilot_agent import browser as browser_module
from copilot_agent.browser import (BrowserAdapter, BrowserUIError, CaptureTimeoutError,
                                  SubmissionAmbiguousError, fresh_assistant, model_rank)
from copilot_agent.browser import uploads_verified
from copilot_agent.browser import composer_comparison
from copilot_agent.browser import SubmissionNotSentError
from copilot_agent.browser import upload_alert_is_error
from copilot_agent.browser import model_access_exhausted
from copilot_agent.browser import response_envelope_closed
from copilot_agent.browser import copied_code_response
from copilot_agent.reused_browser import EndpointError, cdp_endpoint, validate_endpoint
from copilot_agent.protocol import BEGIN, END


class CorrelationTests(unittest.TestCase):
    def test_daily_model_limit_is_classified_without_mistaking_quoted_protocol_data(self):
        notice="You've used today's GPT 6.1 Sol access. You are now using Auto. GPT 6.1 Sol will be available again tomorrow."
        self.assertTrue(model_access_exhausted(notice))
        self.assertFalse(model_access_exhausted('<<<COPILOT_AGENT_V1_BEGIN>>> '+notice))
        self.assertFalse(model_access_exhausted('A discussion about model access.'))

    def test_copied_code_requires_current_identity_and_balanced_complete_container(self):
        complete = '{"request_id":"req","nested":{"value":1},}'
        self.assertEqual(BEGIN + '\n' + complete + '\n' + END,
                         copied_code_response(complete, 'req'))
        self.assertEqual('', copied_code_response('{"request_id":"req","nested":{"value":1}', 'req'))
        self.assertEqual('', copied_code_response('{"request_id":"stale"}', 'req'))


class StartupRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_navigation_timeout_still_checks_visible_page_readiness(self):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        class Page:
            def __init__(self, closed=False):
                self.closed = closed
                self.visits = 0

            async def goto(self, *args, **kwargs):
                self.visits += 1
                raise PlaywrightTimeoutError('synthetic slow first launch')

            def is_closed(self):
                return self.closed

        adapter = BrowserAdapter.__new__(BrowserAdapter)
        adapter.config = SimpleNamespace(copilot_url='https://m365.cloud.microsoft/', startup_timeout=2)
        adapter.page = Page()
        with patch('builtins.print'):
            await adapter._navigate_copilot()
        self.assertEqual(1, adapter.page.visits)
        adapter.page.closed = True
        with self.assertRaises(PlaywrightTimeoutError):
            await adapter._navigate_copilot()

    async def test_startup_diagnostic_exists_before_page_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = BrowserAdapter.__new__(BrowserAdapter)
            adapter.config = SimpleNamespace(runtime_dir=Path(temporary))
            adapter.page = None
            adapter.startup_stage = 'cdp_connection'
            report = await adapter.diagnostics('startup')
            self.assertEqual('cdp_connection', json.loads(report.read_text())['startup_stage'])
            self.assertFalse(json.loads(report.read_text())['page_available'])


class CodeExpansionTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_current_assistant_code_is_scoped_and_absent_controls_do_not_consume_budget(self):
        class Controls:
            visible = False
            clicks = 0
            selected = None
            async def count(self): return 1
            async def is_visible(self): return self.visible
            async def is_enabled(self): return True
            async def click(self, **kwargs): self.clicks += 1
            def locator(self, selector): self.selector = selector; return self
            def filter(self, **kwargs): self.selected = kwargs['has_text']; return self
            def nth(self, index): return self
            def get_by_role(self, role, **kwargs): self.button = (role,kwargs); return self
        controls = Controls()
        adapter = BrowserAdapter.__new__(BrowserAdapter)
        adapter.page = controls
        self.assertEqual(0, await adapter._expand_response_code('current-request'))
        self.assertEqual('current-request', controls.selected)
        self.assertTrue(all('Code Preview' in selector and ('assistant' in selector or 'CopilotMessage' in selector or 'markdown-reply' in selector or 'copilot-message' in selector) for selector in controls.selector.split(',')))
        controls.visible = True
        self.assertEqual(1, await adapter._expand_response_code('current-request'))
        self.assertEqual(1, controls.clicks)

    async def test_copy_button_is_accessible_name_scoped_to_current_code_group(self):
        class Button:
            clicks = 0
            async def count(self): return 1
            async def is_visible(self): return True
            async def is_enabled(self): return True
            async def click(self, **kwargs): self.clicks += 1
        class Group:
            def __init__(self, button): self.button = button
            def get_by_role(self, role, **kwargs):
                self.role, self.name = role, kwargs['name']
                return self.button
        class Groups:
            def __init__(self, group): self.group = group
            def filter(self, **kwargs): self.has_text = kwargs['has_text']; return self
            async def count(self): return 1
            def nth(self, index): return self.group
        class Page:
            def __init__(self):
                self.button, self.group = Button(), None
                self.group = Group(self.button)
                self.groups = Groups(self.group)
            def locator(self, selector): self.selector = selector; return self.groups
            async def evaluate(self, script): return '{"request_id":"current-request"}'
        adapter = BrowserAdapter.__new__(BrowserAdapter)
        adapter.page = Page()
        copied = await adapter._copy_response_code('current-request')
        self.assertEqual('copied', copied['status'])
        self.assertEqual('current-request', adapter.page.groups.has_text)
        self.assertEqual('button', adapter.page.group.role)
        self.assertEqual('^Copy code$', adapter.page.group.name.pattern)
        self.assertIn('[aria-label="Code Preview"]', adapter.page.selector)
        self.assertNotIn('SGs4SWpU', adapter.page.selector)
        self.assertEqual(1, adapter.page.button.clicks)


class RemainingCorrelationTests(unittest.TestCase):
    def test_replaced_user_node_rebinds_only_unique_current_request(self):
        messages = [dict(key=19, order=0, role='user', text='message req-new'),
                    dict(key=20, order=1, role='assistant', text='reply for req-new')]
        self.assertEqual(fresh_assistant(messages, {}, 13, 'req-new'), 'reply for req-new')
        messages.insert(0, dict(key=18, order=-1, role='user', text='duplicate req-new'))
        self.assertEqual(fresh_assistant(messages, {}, 13, 'req-new'), '')

    def test_recycled_key_for_other_user_does_not_anchor_reply(self):
        messages = [dict(key=13, order=0, role='user', text='different old request'),
                    dict(key=20, order=1, role='assistant', text='reply req-new')]
        self.assertEqual(fresh_assistant(messages, {}, 13, 'req-new'), '')

    def test_informational_upload_notice_is_not_failure(self):
        notice = 'Uploading from device will send a copy to OneDrive (work/school).Manage uploads'
        self.assertFalse(upload_alert_is_error(notice))
        self.assertFalse(upload_alert_is_error('Uploading 10 files. Please wait.'))
        self.assertFalse(upload_alert_is_error('Upload complete. Manage uploaded files.'))

    def test_actual_upload_failure_requires_failure_semantics(self):
        for notice in ('An error occurred while uploading your file. Please try again.',
                       'Could not upload this attachment.', 'The file type is not supported.',
                       'This file is too large.', 'You have reached the attachment limit.',
                       'File upload incomplete. Try again.'):
            self.assertTrue(upload_alert_is_error(notice), notice)

    def test_composer_json_whitespace_changes_preserve_literals(self):
        expected = '{\n  "content": "literal  two spaces\\nline",\n  "count": 1\n}'
        actual = '{\n\n  "content": "literal  two spaces\\nline",\n\n  "count": 1\n\n}'
        result = composer_comparison(expected, actual)
        self.assertTrue(result['matches'])
        self.assertEqual(result['comparison'], 'semantic_json')
        self.assertNotEqual(result['expected_sha256'], result['actual_sha256'])

    def test_composer_json_literal_mutation_or_type_change_rejected(self):
        expected = '{"content":"literal  two spaces", "count":1}'
        for actual in ('{"content":"literal two spaces", "count":1}',
                       '{"content":"literal  two spaces", "count":true}',
                       '{"content":"literal  two spaces", "count":2}',
                       '{"content":"literal  two spaces", "count":1,"count":1}'):
            self.assertFalse(composer_comparison(expected, actual)['matches'])
        self.assertFalse(composer_comparison('plain  text', 'plain text')['matches'])

    def test_old_response_and_user_echo_are_excluded(self):
        messages = [dict(key=1, order=0, role='assistant', text='old req'),
                    dict(key=2, order=1, role='user', text='req'),
                    dict(key=3, order=2, role='assistant', text='new response')]
        self.assertEqual(fresh_assistant(messages, {1:'old req'}, 2, 'req'), 'new response')
        self.assertEqual(fresh_assistant(messages[:-1], {1:'old req'}, 2, 'req'), '')

    def test_missing_user_never_accepts_global_assistant(self):
        self.assertEqual(fresh_assistant([dict(key=3, order=2, role='assistant', text='req')], {}, 2, 'req'), '')

    def test_correlated_answer_beats_separate_progress(self):
        messages = [dict(key=2, order=1, role='user', text='req'),
                    dict(key=3, order=2, role='assistant', text='answer request_id req'),
                    dict(key=4, order=3, role='assistant', text='progress')]
        self.assertEqual(fresh_assistant(messages, {}, 2, 'req'), 'answer request_id req')

    def test_rank_disabled_last_and_version_before_mode(self):
        models = [dict(label='GPT 9 Quick response', enabled=True),
                  dict(label='GPT 6 Think deeper', enabled=True),
                  dict(label='GPT 99 Think deeper', enabled=False)]
        self.assertEqual(model_rank(models)[0]['label'], 'GPT 9 Quick response')
        self.assertFalse(model_rank(models)[-1]['enabled'])

    def test_rank_prefers_deeper_only_within_same_version(self):
        models = [dict(label='GPT 6 Quick response', enabled=True), dict(label='GPT 6 Think deeper', enabled=True)]
        self.assertEqual(model_rank(models)[0]['label'], 'GPT 6 Think deeper')

    def test_rank_does_not_compare_cross_provider_numbers(self):
        models = [dict(label='Sonnet 99', enabled=True), dict(label='Opus 5.5', enabled=True)]
        self.assertEqual(model_rank(models), models)

    def test_upload_count_alone_is_not_acceptance(self):
        snapshot = dict(names=['other.md'], busy=False, error=False)
        self.assertFalse(uploads_verified(snapshot, ['intended.md'], True))
        snapshot['names'] = ['intended.md']
        self.assertTrue(uploads_verified(snapshot, ['intended.md'], True))
        snapshot['busy'] = True
        self.assertFalse(uploads_verified(snapshot, ['intended.md'], True))
        snapshot['busy'], snapshot['error'] = False, True
        self.assertFalse(uploads_verified(snapshot, ['intended.md'], True))
        snapshot['error'] = False
        self.assertFalse(uploads_verified(snapshot, ['intended.md'], False))

    def test_endpoint_refuses_remote_wrong_port_and_non_edge(self):
        endpoint = cdp_endpoint(9333)
        for ws, browser in [('ws://evil.test:9333/devtools/a','Edg/1'),
                            ('ws://127.0.0.1:9222/a','Edg/1'),
                            ('ws://127.0.0.1:9333/a','Chrome/1')]:
            with self.assertRaises(EndpointError):
                validate_endpoint(endpoint, dict(webSocketDebuggerUrl=ws, Browser=browser))
        self.assertEqual(validate_endpoint(endpoint, dict(webSocketDebuggerUrl='ws://localhost:9333/a', Browser='Edg/1')), 'ws://localhost:9333/a')


class FakeEditor:
    def __init__(self):
        self.text = ''
    async def fill(self, text, **kwargs):
        self.text = text
    async def evaluate(self, script):
        return self.text


class FakeButton:
    def __init__(self, owner, fails=False):
        self.owner = owner
        self.fails = fails
        self.clicks = 0
    async def is_enabled(self):
        return not self.owner.clicked or self.owner.current_send_ready()
    async def click(self, **kwargs):
        self.clicks += 1
        if self.fails:
            raise TimeoutError('possible click delivery')
        self.owner.clicked = True
        self.owner.editor.text = ''


class OfflineAdapter(BrowserAdapter):
    def __init__(self, answer=None, click_fails=False, *, answers=None,
                 stop_states=None, send_states=None, copy_answers=None,
                 clipboard_statuses=None, dom_answers=None):
        super().__init__(SimpleNamespace(response_timeout=0.25, poll_interval=0.001,
                                         capture_stable_samples=2, max_capture_chars=5000))
        self.page = SimpleNamespace(url='https://m365.cloud.microsoft/chat')
        self.model_label = 'discovered model'
        self.editor = FakeEditor()
        self.button = FakeButton(self, click_fails)
        self.clicked = False
        default = BEGIN + '\n{"request_id":"req","malformed":}\n' + END
        self.answers = list(answers if answers is not None else [default if answer is None else answer])
        self.stop_states = list(stop_states or [False])
        self.send_states = list(send_states or [True])
        self.capture_index = -1
        self.after_click_evaluations = 0
        self.current_answer = ''
        self.copy_answers = list(copy_answers) if copy_answers is not None else None
        self.clipboard_statuses = list(clipboard_statuses or ['copied'])
        self.dom_answers = list(dom_answers or [''])
        self.copy_calls = 0
        self.diagnostic_calls = []

    def _sequence_value(self, values):
        return values[min(max(self.capture_index, 0), len(values) - 1)]

    def current_send_ready(self):
        return bool(self._sequence_value(self.send_states))

    async def _stop_present(self):
        return self.clicked and bool(self._sequence_value(self.stop_states))
    async def _evaluate(self, script, arg=None):
        if not self.clicked:
            return [dict(key=1, order=0, role='assistant', text='stale req')]
        self.after_click_evaluations += 1
        messages = [dict(key=1, order=0, role='assistant', text='stale req'),
                    dict(key=2, order=1, role='user', text='message req')]
        # The first post-click snapshot proves submission. Subsequent snapshots
        # model the response-rendering polls.
        if self.after_click_evaluations > 1:
            self.capture_index += 1
            answer = self._sequence_value(self.answers)
        else:
            answer = ''
        if answer:
            messages.append(dict(key=3, order=2, role='assistant', text=answer))
        self.current_answer = answer
        return messages
    async def _editor(self, required=True):
        return self.editor
    async def _visible(self, selector):
        return self.button
    async def attach_files(self, paths):
        return None
    async def _expand_response_code(self, request_id):
        return None
    async def _copy_response_code(self, request_id):
        self.copy_calls += 1
        status = self._sequence_value(self.clipboard_statuses)
        if self.copy_answers is not None:
            value = self._sequence_value(self.copy_answers)
        elif response_envelope_closed(self.current_answer):
            value = self.current_answer
        else:
            value = self.current_answer
        return {'status':status, 'text':value if status == 'copied' else ''}
    async def _safe_dom_code_response(self, request_id):
        return self._sequence_value(self.dom_answers)
    async def diagnostics(self, reason='failure'):
        self.diagnostic_calls.append(reason)


class PreloadedOfflineAdapter(OfflineAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attachment_uploads = []
        self.attachment_names = []

    async def attach_files(self, paths):
        paths = list(paths)
        self.attachment_uploads.append(paths)
        self.attachment_names = [Path(path).name for path in paths]

    async def _evaluate(self, script, arg=None):
        if script == browser_module._ATTACHMENTS:
            return {'names': list(self.attachment_names), 'busy': False,
                    'error': False, 'alerts': []}
        return await super()._evaluate(script, arg)


class ExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_preloaded_file_reuses_identical_approved_snapshot_path(self):
        with tempfile.TemporaryDirectory(prefix='copilot-preload-source-') as source_dir, \
             tempfile.TemporaryDirectory(prefix='copilot-preload-approved-') as approved_dir:
            source = Path(source_dir) / 'reviewed.txt'
            approved = Path(approved_dir) / source.name
            source.write_bytes(b'exact reviewed bytes')
            approved.write_bytes(source.read_bytes())
            browser = PreloadedOfflineAdapter()

            await browser.preload_attachments([source])
            await browser._reconcile_preloaded_attachments([approved])

            self.assertEqual([[source]], browser.attachment_uploads)

    async def test_exact_preload_uploads_before_model_choice_and_is_not_uploaded_twice(self):
        with tempfile.TemporaryDirectory(prefix='copilot-preload-') as directory:
            attachment = Path(directory) / 'startup.md'
            attachment.write_text('startup contract', encoding='utf-8')
            browser = PreloadedOfflineAdapter()
            browser.model_label = None

            prepared = await browser.preload_exchange(
                'message req', 'req', attachments=[attachment])

            self.assertEqual({'request_id': 'req', 'attachment_count': 1}, prepared)
            self.assertEqual([[attachment]], browser.attachment_uploads)
            self.assertEqual('message req', browser.editor.text)
            self.assertEqual(0, browser.button.clicks)

            browser.model_label = 'discovered model'
            result = await browser.exchange('message req', 'req', attachments=[attachment])

            self.assertTrue(response_envelope_closed(result))
            self.assertEqual([[attachment]], browser.attachment_uploads)
            self.assertEqual(1, browser.button.clicks)
            self.assertIsNone(browser._preloaded_exchange)

    async def test_preloaded_message_refuses_different_submission_without_click(self):
        browser = PreloadedOfflineAdapter()
        await browser.preload_exchange('message req', 'req')

        with self.assertRaisesRegex(SubmissionNotSentError, 'does not match'):
            await browser.exchange('message another', 'another')

        self.assertEqual(0, browser.button.clicks)
        self.assertIsNotNone(browser._preloaded_exchange)

    async def test_upload_capacity_and_zip_reject_before_browser_access(self):
        adapter = BrowserAdapter(SimpleNamespace())
        with self.assertRaises(BrowserUIError):
            await adapter.attach_files([Path('missing-' + str(number) + '.txt') for number in range(21)])
        with self.assertRaises(BrowserUIError):
            await adapter.attach_files([Path('missing.ZIP')])

    async def test_pre_send_failure_proves_no_click_and_no_commit(self):
        browser = OfflineAdapter()
        browser.model_label = None
        commits = []
        with self.assertRaises(SubmissionNotSentError):
            await browser.exchange('message req', 'req', on_submitted=lambda: commits.append('req'))
        self.assertEqual(browser.button.clicks, 0)
        self.assertEqual(commits, [])
        self.assertFalse(browser.last_submission['send_attempted'])
        self.assertFalse(browser._delivery_uncertain)

    async def test_commits_once_and_returns_genuinely_completed_malformed_reply(self):
        browser = OfflineAdapter()
        commits = []
        result = await browser.exchange('message req', 'req', on_submitted=lambda: commits.append('req'))
        self.assertTrue(response_envelope_closed(result))
        self.assertIn('"malformed":}', result)
        self.assertEqual(commits, ['req'])
        self.assertEqual(browser.button.clicks, 1)

    async def test_slow_line_stream_waits_for_closing_marker_and_stability(self):
        complete = BEGIN + '\n{"request_id":"req","partial":true}\n' + END
        browser = OfflineAdapter(answers=[BEGIN, BEGIN + '\n{', BEGIN + '\n{"request_id":"req","partial":true}',
                                          complete, complete],
                                 stop_states=[True, True, True, False, False],
                                 send_states=[False, False, False, True, True])
        events = []
        browser.set_feedback(events.append)
        result = await browser.exchange('message req', 'req')
        self.assertEqual(complete, result)
        candidates = [event['raw'] for event in events if event['type'] == 'candidate']
        self.assertIn(BEGIN + '\n{"request_id":"req","partial":true}', candidates)
        self.assertTrue(browser.last_capture_observation['generation_ended'])
        self.assertTrue(browser.last_capture_observation['complete_current_text'])
        self.assertEqual('chat_text', browser.last_capture_observation['capture_method'])
        self.assertEqual(0, browser.copy_calls)

    async def test_delayed_closing_marker_is_not_accepted_when_send_looks_ready(self):
        partial = BEGIN + '\n{"request_id":"req","still":"streaming"}'
        complete = partial + '\n' + END
        browser = OfflineAdapter(answers=[partial, partial, complete, complete],
                                 send_states=[True, True, True, True])
        result = await browser.exchange('message req', 'req')
        self.assertEqual(complete, result)
        self.assertGreaterEqual(browser.capture_index, 3)

    async def test_complete_marker_waits_for_stop_to_change_back_to_send(self):
        complete = BEGIN + '\n{"request_id":"req","bad":}\n' + END
        browser = OfflineAdapter(answers=[complete] * 5,
                                 stop_states=[True, True, False, False],
                                 send_states=[False, False, True, True])
        self.assertEqual(complete, await browser.exchange('message req', 'req'))
        self.assertTrue(browser.last_capture_observation['generation_observed'])
        self.assertFalse(browser.last_capture_observation['stop_present'])
        self.assertTrue(browser.last_capture_observation['send_ready'])


class ToolContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_page_route_does_not_intercept_chat_context(self):
        class Page:
            def __init__(self, context):
                self.context = context
            async def route(self, pattern, handler):
                self.pattern, self.handler = pattern, handler
            async def add_init_script(self, script):
                self.script = script
            async def route_web_socket(self, pattern, handler):
                self.websocket_handler = handler
            def on(self, event, handler):
                pass
        class Route:
            def __init__(self, url):
                self.request = SimpleNamespace(url=url)
                self.result = None
            async def abort(self, reason):
                self.result = 'abort'
            async def continue_(self):
                self.result = 'continue'
        browser = BrowserAdapter(SimpleNamespace(allowed_domains=['example.com']))
        browser.context = SimpleNamespace()
        browser.tool_context = browser.context
        browser.page = Page(browser.context)
        tool_page = Page(browser.context)
        await browser._configure_tool_context(tool_page)
        blocked = Route('https://unapproved.example/initial-popup-request')
        await tool_page.handler(blocked)
        self.assertEqual(blocked.result, 'abort')
        allowed = Route('https://example.com/allowed')
        await tool_page.handler(allowed)
        self.assertEqual(allowed.result, 'continue')
        self.assertIn('window.open', tool_page.script)
        self.assertEqual(browser.tool_errors[0]['type'], 'blocked_request')
        class Socket:
            url = 'wss://unapproved.example/socket'
            closed = False
            async def close(self):
                self.closed = True
        socket = Socket()
        await tool_page.websocket_handler(socket)
        self.assertTrue(socket.closed)

    async def test_async_commit_callback(self):
        browser = OfflineAdapter()
        commits = []
        async def commit():
            commits.append('committed')
        await browser.exchange('message req', 'req', on_submitted=commit)
        self.assertEqual(commits, ['committed'])

    async def test_click_timeout_never_resends(self):
        browser = OfflineAdapter(click_fails=True)
        with self.assertRaises(SubmissionAmbiguousError):
            await browser.exchange('message req', 'req')
        with self.assertRaises(SubmissionAmbiguousError):
            await browser.exchange('message req', 'req')
        self.assertEqual(browser.button.clicks, 1)

    async def test_capture_timeout_has_one_committed_send(self):
        browser = OfflineAdapter(answer='')
        commits = []
        with self.assertRaises(CaptureTimeoutError):
            await browser.exchange('message req', 'req', on_submitted=lambda: commits.append('req'))
        self.assertEqual(commits, ['req'])
        self.assertEqual(browser.button.clicks, 1)
        self.assertIn('capture', browser.diagnostic_calls)

    async def test_finished_incomplete_reply_is_returned_for_quick_correction(self):
        browser = OfflineAdapter(answer=BEGIN + '\n{"unfinished":true}', send_states=[True])
        result = await browser.exchange('message req', 'req')
        self.assertEqual(BEGIN + '\n{"unfinished":true}', result)
        self.assertFalse(browser.last_capture_observation['complete_current_text'])
        self.assertLess(browser.capture_index, 10)

    async def test_long_plain_text_json_is_captured_without_copy_code(self):
        payload = '{"request_id":"req","content":"' + ('x' * 20000) + '"}'
        browser = OfflineAdapter(answers=[BEGIN + '\n' + payload + '\n' + END], send_states=[True])
        browser.config.max_capture_chars = 50000
        result = await browser.exchange('message req', 'req')
        self.assertEqual(BEGIN + '\n' + payload + '\n' + END, result)
        self.assertEqual(0, browser.copy_calls)

    async def test_plain_text_json_preserves_backslashes(self):
        code = r'{"request_id":"req","value":"C:\\Users\\Example"}'
        browser = OfflineAdapter(answers=[BEGIN + '\n' + code + '\n' + END], send_states=[True])
        result = await browser.exchange('message req', 'req')
        self.assertEqual(BEGIN + '\n' + code + '\n' + END, result)
        self.assertEqual(0, browser.copy_calls)

    async def test_wrong_request_id_is_returned_for_protocol_rejection(self):
        stale = BEGIN + '\n{"request_id":"old-request","value":1}\n' + END
        current = BEGIN + '\n{"request_id":"req","value":2}\n' + END
        browser = OfflineAdapter(answers=[stale] * 4 + [current], send_states=[True])
        result = await browser.exchange('message req', 'req')
        self.assertEqual(stale, result)
        self.assertEqual(0, browser.copy_calls)

    async def test_callback_failure_marks_delivered_uncertainty(self):
        browser = OfflineAdapter()
        def failed_commit():
            raise OSError('state unavailable')
        with self.assertRaises(SubmissionAmbiguousError):
            await browser.exchange('message req', 'req', on_submitted=failed_commit)
        self.assertTrue(browser.last_submission['committed'])
        with self.assertRaises(SubmissionAmbiguousError):
            await browser.exchange('message another', 'another')
        self.assertEqual(browser.button.clicks, 1)


if __name__ == '__main__':
    unittest.main()
