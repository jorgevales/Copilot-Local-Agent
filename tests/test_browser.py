"""Offline contract tests; no browser, file deletion, network, or Copilot send."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

from copilot_agent.browser import (BrowserAdapter, BrowserUIError, CaptureTimeoutError,
                                  SubmissionAmbiguousError, fresh_assistant, model_rank)
from copilot_agent.browser import uploads_verified
from copilot_agent.browser import composer_comparison
from copilot_agent.browser import SubmissionNotSentError
from copilot_agent.browser import upload_alert_is_error
from copilot_agent.browser import model_access_exhausted
from copilot_agent.browser import response_envelope_closed
from copilot_agent.reused_browser import EndpointError, cdp_endpoint, validate_endpoint
from copilot_agent.protocol import BEGIN, END


class CorrelationTests(unittest.TestCase):
    def test_daily_model_limit_is_classified_without_mistaking_quoted_protocol_data(self):
        notice="You've used today's GPT 6.1 Sol access. You are now using Auto. GPT 6.1 Sol will be available again tomorrow."
        self.assertTrue(model_access_exhausted(notice))
        self.assertFalse(model_access_exhausted('<<<COPILOT_AGENT_V1_BEGIN>>> '+notice))
        self.assertFalse(model_access_exhausted('A discussion about model access.'))


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
                 stop_states=None, send_states=None):
        super().__init__(SimpleNamespace(response_timeout=0.25, poll_interval=0.001,
                                         capture_stable_samples=2, max_capture_chars=5000))
        self.page = SimpleNamespace(url='https://m365.cloud.microsoft/chat')
        self.model_label = 'discovered model'
        self.editor = FakeEditor()
        self.button = FakeButton(self, click_fails)
        self.clicked = False
        default = BEGIN + '\nmalformed but completed assistant text\n' + END
        self.answers = list(answers if answers is not None else [default if answer is None else answer])
        self.stop_states = list(stop_states or [False])
        self.send_states = list(send_states or [True])
        self.capture_index = -1
        self.after_click_evaluations = 0
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
        return messages
    async def _editor(self, required=True):
        return self.editor
    async def _visible(self, selector):
        return self.button
    async def attach_files(self, paths):
        return None
    async def _expand_response_code(self, request_id):
        return None
    async def diagnostics(self, reason='failure'):
        self.diagnostic_calls.append(reason)


class ExchangeTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertIn('malformed but completed', result)
        self.assertEqual(commits, ['req'])
        self.assertEqual(browser.button.clicks, 1)

    async def test_slow_line_stream_waits_for_closing_marker_and_stability(self):
        complete = BEGIN + '\n{"partial":true}\n' + END
        browser = OfflineAdapter(answers=[BEGIN, BEGIN + '\n{', BEGIN + '\n{"partial":true}',
                                          complete, complete],
                                 stop_states=[True, True, True, False, False],
                                 send_states=[False, False, False, True, True])
        events = []
        browser.set_feedback(events.append)
        result = await browser.exchange('message req', 'req')
        self.assertEqual(complete, result)
        candidates = [event['raw'] for event in events if event['type'] == 'candidate']
        self.assertIn(BEGIN + '\n{"partial":true}', candidates)
        self.assertTrue(browser.last_capture_observation['generation_ended'])
        self.assertTrue(browser.last_capture_observation['closing_marker_present'])

    async def test_delayed_closing_marker_is_not_accepted_when_send_looks_ready(self):
        partial = BEGIN + '\n{"still":"streaming"}'
        complete = partial + '\n' + END
        browser = OfflineAdapter(answers=[partial, partial, complete, complete],
                                 send_states=[True, True, True, True])
        result = await browser.exchange('message req', 'req')
        self.assertEqual(complete, result)
        self.assertGreaterEqual(browser.capture_index, 3)

    async def test_complete_marker_waits_for_stop_to_change_back_to_send(self):
        complete = BEGIN + '\nnot-json\n' + END
        browser = OfflineAdapter(answers=[complete] * 5,
                                 stop_states=[True, True, False, False],
                                 send_states=[False, False, True, True])
        self.assertEqual(complete, await browser.exchange('message req', 'req'))
        self.assertTrue(browser.last_capture_observation['generation_observed'])
        self.assertFalse(browser.last_capture_observation['stop_present'])
        self.assertTrue(browser.last_capture_observation['send_ready'])


class ToolContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_context_route_contains_initial_popup_requests(self):
        class Context:
            async def route(self, pattern, handler):
                self.pattern, self.handler = pattern, handler
            async def add_init_script(self, script):
                self.script = script
            async def route_web_socket(self, pattern, handler):
                self.websocket_handler = handler
            def on(self, event, handler):
                self.event, self.register = event, handler
        class Route:
            def __init__(self, url):
                self.request = SimpleNamespace(url=url)
                self.result = None
            async def abort(self, reason):
                self.result = 'abort'
            async def continue_(self):
                self.result = 'continue'
        browser = BrowserAdapter(SimpleNamespace(allowed_domains=['example.com']))
        browser.tool_context = Context()
        # Persistent Copilot context has no route method; calling it would fail.
        browser.context = SimpleNamespace()
        await browser._configure_tool_context()
        blocked = Route('https://unapproved.example/initial-popup-request')
        await browser.tool_context.handler(blocked)
        self.assertEqual(blocked.result, 'abort')
        allowed = Route('https://example.com/allowed')
        await browser.tool_context.handler(allowed)
        self.assertEqual(allowed.result, 'continue')
        self.assertEqual(browser.tool_context.event, 'page')
        self.assertIn('window.open', browser.tool_context.script)
        self.assertEqual(browser.tool_errors[0]['type'], 'blocked_request')
        class Socket:
            url = 'wss://unapproved.example/socket'
            closed = False
            async def close(self):
                self.closed = True
        socket = Socket()
        await browser.tool_context.websocket_handler(socket)
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

    async def test_incomplete_reply_times_out_even_when_send_is_ready(self):
        browser = OfflineAdapter(answer=BEGIN + '\n{"unfinished":true}', send_states=[True])
        with self.assertRaisesRegex(CaptureTimeoutError, 'No local action ran'):
            await browser.exchange('message req', 'req')
        self.assertFalse(browser.last_capture_observation['closing_marker_present'])

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
