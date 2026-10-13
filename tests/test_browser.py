"""Offline contract tests; no browser, file deletion, network, or Copilot send."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent import browser as browser_module
from copilot_agent.browser import (BrowserAdapter, BrowserUIError, CaptureTimeoutError,
                                  SubmissionAmbiguousError, fresh_assistant, model_rank,
                                  public_progress)
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

    def test_public_progress_filters_protocol_payload_and_only_keeps_post_turn_visible_text(self):
        messages = [
            {'key': 4, 'order': 0, 'role': 'assistant', 'text': 'old unrelated response'},
            {'key': 1, 'order': 1, 'role': 'user', 'text': 'request_id req'},
            {'key': 2, 'order': 2, 'role': 'assistant', 'text': 'I am preparing the ZIP.'},
            {'key': 3, 'order': 3, 'role': 'assistant', 'text': BEGIN + '\n{}\n' + END},
        ]
        self.assertEqual([messages[2]], public_progress(messages, 1, 'req'))


class ReadinessControl:
    async def is_enabled(self):
        return True


class ReadinessAdapter(BrowserAdapter):
    def __init__(self, *, editor_text='', stop_states=None, messages=None):
        super().__init__(SimpleNamespace(startup_timeout=.005, response_timeout=.03,
                                         response_max_duration=.15, poll_interval=.003))
        self.model_label = 'discovered model'
        self.editor = FakeEditor()
        self.editor.text = editor_text
        self.stop_states = list(stop_states or [False])
        self.readiness_calls = 0
        self.messages = list(messages or [])
        self.diagnostic_calls = []

    async def _editor(self, required=True):
        return self.editor

    async def _editor_text(self, editor):
        return editor.text

    async def _visible(self, selector):
        return ReadinessControl()

    async def _stop_present(self):
        index = min(self.readiness_calls, len(self.stop_states) - 1)
        self.readiness_calls += 1
        return self.stop_states[index]

    async def _evaluate(self, script, arg=None):
        if script == browser_module._MESSAGE_SNAPSHOT:
            return self.messages
        if script == browser_module._ATTACHMENTS:
            return {'names': [], 'busy': False}
        return []

    async def diagnostics(self, reason='failure'):
        self.diagnostic_calls.append(reason)


class InteractionReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_generation_uses_response_window_and_prints_public_progress(self):
        messages = [
            {'key': 1, 'order': 0, 'role': 'user', 'text': 'request_id req'},
            {'key': 2, 'order': 1, 'role': 'assistant', 'text': 'Building the ZIP and checking its files.'},
            {'key': 3, 'order': 2, 'role': 'assistant', 'text': BEGIN + '\n{}\n' + END},
        ]
        adapter = ReadinessAdapter(stop_states=[True, True, True, True, False], messages=messages)
        progress = []
        adapter.set_feedback(progress.append)

        self.assertTrue(await adapter.verify_interaction_ready('discovered model', request_id='req'))

        self.assertGreaterEqual(adapter.readiness_calls, 5)
        self.assertEqual(1, len(progress))
        self.assertEqual('Building the ZIP and checking its files.', progress[0]['message'])

    async def test_unsubmitted_composer_draft_is_preserved_and_reported(self):
        adapter = ReadinessAdapter(editor_text='Keep this exact unsent request.')

        with self.assertRaisesRegex(BrowserUIError, 'unsent draft'):
            await adapter.verify_interaction_ready('discovered model')

        self.assertEqual('Keep this exact unsent request.', adapter.editor.text)
        self.assertEqual(['interaction_readiness_unsent_draft'], adapter.diagnostic_calls)

    async def test_reconciled_draft_requires_exact_hash_and_no_matching_user_turn(self):
        draft = BEGIN + '\n{"request_id":"req","kind":"steering"}\n' + END
        digest = hashlib.sha256(draft.encode()).hexdigest()
        adapter = ReadinessAdapter(editor_text=draft)
        adapter.page = SimpleNamespace(is_closed=lambda: False)

        self.assertEqual(draft, await adapter.read_reconciled_draft('req', digest))
        with self.assertRaisesRegex(BrowserUIError, 'no longer matches'):
            await adapter.read_reconciled_draft('req', '0' * 64)
        adapter.messages = [{'key': 1, 'order': 0, 'role': 'user', 'text': 'request_id req'}]
        with self.assertRaisesRegex(BrowserUIError, 'already visible'):
            await adapter.read_reconciled_draft('req', digest)


class StartupRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_proof_endpoint_never_falls_back_after_connection_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            config = SimpleNamespace(visible=True, copilot_url='https://m365.cloud.microsoft/',
                                     profile_dir=profile, debug_port=63741, attach_existing=True,
                                     startup_timeout=1, _proof_exact_edge_endpoint=(63741, str(profile.resolve())))
            adapter = BrowserAdapter(config)
            adapter._acquire_controller = lambda: None
            adapter.diagnostics = AsyncMock()
            adapter.close = AsyncMock()
            adapter._connect_running_edge_fallback = AsyncMock(return_value=object())
            manager = SimpleNamespace(start=AsyncMock(return_value=object()))
            playwright_package = ModuleType('playwright')
            playwright_async_api = ModuleType('playwright.async_api')
            playwright_async_api.async_playwright = lambda: manager
            playwright_package.async_api = playwright_async_api

            with patch.dict(sys.modules, {'playwright': playwright_package,
                                          'playwright.async_api': playwright_async_api}), \
                 patch.object(browser_module.edge, 'get_cdp_version', return_value={'Browser':'Edge'}), \
                 patch.object(browser_module.edge, 'validate_endpoint'), \
                 patch.object(browser_module.edge, 'validate_profile_ownership'), \
                 patch.object(browser_module.edge, 'connect_bounded',
                              new=AsyncMock(side_effect=EndpointError('synthetic attach failure'))), \
                 patch('playwright.async_api.async_playwright', return_value=manager):
                with self.assertRaisesRegex(BrowserUIError, 'no fallback port or profile'):
                    await adapter.start()

            adapter._connect_running_edge_fallback.assert_not_awaited()
            self.assertEqual(63741, config.debug_port)
            self.assertEqual(profile.resolve(), Path(config.profile_dir).resolve())

    async def test_exact_proof_endpoint_rejects_port_change_after_attachment(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary)
            config = SimpleNamespace(visible=True, copilot_url='https://m365.cloud.microsoft/',
                                     profile_dir=profile, debug_port=63741, attach_existing=True,
                                     startup_timeout=1, _proof_exact_edge_endpoint=(63741, str(profile.resolve())))
            adapter = BrowserAdapter(config)
            adapter._acquire_controller = lambda: None
            adapter.diagnostics = AsyncMock()
            adapter.close = AsyncMock()
            manager = SimpleNamespace(start=AsyncMock(return_value=object()))

            async def switched_endpoint(*args, **kwargs):
                config.debug_port = 63742
                return object()

            with patch.object(browser_module.edge, 'get_cdp_version', return_value={'Browser':'Edge'}), \
                 patch.object(browser_module.edge, 'validate_endpoint'), \
                 patch.object(browser_module.edge, 'validate_profile_ownership'), \
                 patch.object(browser_module.edge, 'connect_bounded', new=switched_endpoint), \
                 patch('playwright.async_api.async_playwright', return_value=manager):
                with self.assertRaisesRegex(BrowserUIError, 'exact existing Edge port'):
                    await adapter.start()

    async def test_resume_claims_the_existing_chat_with_the_exact_committed_request(self):
        request_id = 'committed-request'

        class Page:
            def __init__(self, url, messages):
                self.url = url
                self.messages = messages
                self.front = False
            def is_closed(self): return False
            async def evaluate(self, script, arg=None):
                self.assert_snapshot = script == browser_module._MESSAGE_SNAPSHOT
                return self.messages
            async def bring_to_front(self): self.front = True

        unrelated = Page('https://m365.cloud.microsoft/chat/conversation/init', [
            {'key': 1, 'role': 'user', 'text': 'request_id another-request'}])
        committed = Page('https://m365.cloud.microsoft/chat/conversation/target', [
            {'key': 2, 'role': 'user', 'text': 'request_id ' + request_id},
            {'key': 3, 'role': 'assistant', 'text': 'response for ' + request_id}])
        adapter = BrowserAdapter(SimpleNamespace())
        adapter.context = SimpleNamespace(pages=[unrelated, committed])

        selected = await adapter._claim_committed_request_page(request_id)

        self.assertIs(selected, committed)
        self.assertIs(adapter.page, committed)
        self.assertTrue(committed.assert_snapshot)

    async def test_resume_refuses_duplicate_tabs_for_the_same_committed_request(self):
        request_id = 'committed-request'

        class Page:
            def __init__(self, url): self.url = url
            def is_closed(self): return False
            async def evaluate(self, script, arg=None):
                return [{'key': 1, 'role': 'user', 'text': 'request_id ' + request_id}]

        adapter = BrowserAdapter(SimpleNamespace())
        adapter.context = SimpleNamespace(pages=[
            Page('https://m365.cloud.microsoft/chat/conversation/first'),
            Page('https://m365.cloud.microsoft/chat/conversation/duplicate')])

        with self.assertRaisesRegex(BrowserUIError, 'exactly one existing Copilot conversation'):
            await adapter._claim_committed_request_page(request_id)

        self.assertIsNone(adapter.page)

    async def test_startup_reuses_initial_blank_page_without_opening_another(self):
        class Page:
            url = 'about:blank'
            def is_closed(self): return False
        class Context:
            def __init__(self):
                self.pages = [Page()]
                self.new_pages = 0
            async def new_page(self):
                self.new_pages += 1
                return Page()
        adapter = BrowserAdapter.__new__(BrowserAdapter)
        adapter.context = Context()

        claimed = await adapter._claim_chat_page()

        self.assertIs(claimed, adapter.context.pages[0])
        self.assertEqual(0, adapter.context.new_pages)

    async def test_startup_opens_one_page_when_edge_has_no_blank_page(self):
        class Page:
            url = 'https://example.com/'
            def is_closed(self): return False
        class Context:
            def __init__(self):
                self.pages = [Page()]
                self.new_pages = 0
            async def new_page(self):
                self.new_pages += 1
                page = Page()
                page.url = 'about:blank'
                return page
        adapter = BrowserAdapter.__new__(BrowserAdapter)
        adapter.context = Context()

        await adapter._claim_chat_page()

        self.assertEqual(1, adapter.context.new_pages)

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
    def __init__(self, owner, fails=False, transient_failures=0):
        self.owner = owner
        self.fails = fails
        self.transient_failures = transient_failures
        self.clicks = 0
    async def is_enabled(self):
        return not self.owner.clicked or self.owner.current_send_ready()
    async def click(self, **kwargs):
        self.clicks += 1
        if self.fails or self.transient_failures:
            if self.transient_failures:
                self.transient_failures -= 1
            raise TimeoutError('possible click delivery')
        self.owner.clicked = True
        self.owner.editor.text = ''


class OfflineAdapter(BrowserAdapter):
    def __init__(self, answer=None, click_fails=False, *, answers=None,
                 stop_states=None, send_states=None, copy_answers=None,
                 clipboard_statuses=None, dom_answers=None, transient_click_failures=0):
        super().__init__(SimpleNamespace(response_timeout=0.25, poll_interval=0.001,
                                         capture_stable_samples=2, max_capture_chars=5000))
        self.page = SimpleNamespace(url='https://m365.cloud.microsoft/chat')
        self.model_label = 'discovered model'
        self.editor = FakeEditor()
        self.button = FakeButton(self, click_fails, transient_click_failures)
        self.clicked = False
        default = BEGIN + '\n{"request_id":"req","malformed":}\n' + END
        self.answers = list(answers if answers is not None else [default if answer is None else answer])
        self.stop_states = list(stop_states if stop_states is not None else [True, False])
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
        if script == browser_module._ATTACHMENTS:
            return {'names': [], 'busy': False, 'error': False, 'alerts': []}
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
    async def test_recover_committed_response_reads_current_chat_without_a_second_send(self):
        complete = BEGIN + '\n{"request_id":"req","response_type":"final"}\n' + END
        browser = OfflineAdapter(answers=[complete], send_states=[True])
        browser.clicked = True  # A prior process already submitted this request.

        result = await browser.capture_committed_response('req')

        self.assertEqual(complete, result)
        self.assertEqual(0, browser.button.clicks)
        self.assertEqual('existing_chat_text', browser.last_capture_observation['capture_method'])
        self.assertEqual({'request_id': 'req', 'user_key': 2, 'assistant_key': 3, 'committed': True},
                         browser.last_submission)

    async def test_recover_waits_on_active_generation_without_visible_text_changes(self):
        complete = BEGIN + '\n{"request_id":"req","response_type":"final"}\n' + END
        browser = OfflineAdapter(answers=[''] * 10 + [complete], stop_states=[True] * 10 + [False],
                                 send_states=[False] * 10 + [True])
        browser.clicked = True  # Recovery reads the committed turn and never clicks Send.
        browser.config.response_timeout = 0.04
        browser.config.response_max_duration = 0.6
        browser.config.poll_interval = 0.005

        result = await browser.capture_committed_response('req')

        self.assertEqual(complete, result)
        self.assertGreaterEqual(browser.capture_index, 10)
        self.assertEqual(0, browser.button.clicks)

    async def test_visible_assistant_progress_extends_idle_capture_and_is_emitted(self):
        complete = BEGIN + '\n{"request_id":"req","response_type":"final"}\n' + END

        class ProgressAdapter(OfflineAdapter):
            async def _evaluate(self, script, arg=None):
                messages = await super()._evaluate(script, arg)
                if self.clicked and self.after_click_evaluations > 1:
                    reply = messages.pop() if messages[-1]['role'] == 'assistant' and messages[-1]['key'] == 3 else None
                    messages.append(dict(key=4 + self.capture_index, order=2, role='assistant',
                                         text='Copilot is preparing package segment ' + str(self.capture_index + 1) + '.'))
                    if reply is not None:
                        reply['order'] = 3
                        messages.append(reply)
                return messages

        browser = ProgressAdapter(answers=['', '', '', '', complete], send_states=[True])
        browser.answers = [''] * 8 + [complete]
        browser.config.response_timeout = 0.05
        browser.config.response_max_duration = 0.5
        browser.config.poll_interval = 0.01
        events = []
        browser.set_feedback(lambda event: events.append(event))

        result = await browser.exchange('message req', 'req')

        self.assertEqual(complete, result)
        updates = [event for event in events if event['type'] == 'progress']
        self.assertGreaterEqual(len(updates), 9)
        self.assertIn('Copilot is preparing package segment 1.', updates[0]['message'])

    async def test_active_generation_signal_extends_idle_limit_without_text_changes(self):
        complete = BEGIN + '\n{"request_id":"req","response_type":"final"}\n' + END
        browser = OfflineAdapter(answers=[''] * 10 + [complete], stop_states=[True] * 10 + [False],
                                 send_states=[False] * 10 + [True])
        browser.config.response_timeout = 0.04
        browser.config.response_max_duration = 0.6
        browser.config.poll_interval = 0.005
        events = []
        browser.set_feedback(events.append)

        result = await browser.exchange('message req', 'req')

        self.assertEqual(complete, result)
        self.assertGreaterEqual(browser.capture_index, 10)
        self.assertTrue(any(event['type'] == 'generation' and 'generating' in event['message'].casefold()
                            for event in events))

    async def test_stop_button_keeps_a_complete_envelope_waiting_until_generation_ends(self):
        complete = BEGIN + '\n{"request_id":"req","response_type":"final"}\n' + END

        class StopButtonAdapter(OfflineAdapter):
            def __init__(self):
                super().__init__(answers=[complete] * 8, stop_states=[False], send_states=[True])
                self.stop_button_states = [True, True, True, False, False]

            async def _stop_present(self):
                return await BrowserAdapter._stop_present(self)

            async def _evaluate(self, script, arg=None):
                if "querySelectorAll('button')" in script:
                    index = min(max(self.capture_index, 0), len(self.stop_button_states) - 1)
                    return self.clicked and self.stop_button_states[index]
                return await super()._evaluate(script, arg)

        browser = StopButtonAdapter()
        browser.config.response_timeout = 0.25
        browser.config.poll_interval = 0.001

        result = await browser.exchange('message req', 'req')

        self.assertEqual(complete, result)
        self.assertGreaterEqual(browser.capture_index, 4)
        self.assertFalse(browser.last_capture_observation['stop_present'])

    async def test_completed_loading_container_is_not_the_generation_signal(self):
        class VisibleStopProbe(BrowserAdapter):
            async def _evaluate(self, script, arg=None):
                self.stop_selector = script
                return False

        browser = VisibleStopProbe(SimpleNamespace())
        self.assertFalse(await browser._stop_present())
        self.assertIn("querySelectorAll('button')", browser.stop_selector)
        self.assertIn('stop generating', browser.stop_selector)
        self.assertNotIn('loading-message', browser.stop_selector)

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

    async def test_send_ready_without_observed_stop_does_not_prove_generation_finished(self):
        complete = BEGIN + '\n{"request_id":"req","response_type":"final"}\n' + END
        browser = OfflineAdapter(answers=[complete], stop_states=[False], send_states=[True])
        browser.config.response_timeout = .03

        with self.assertRaises(CaptureTimeoutError):
            await browser.exchange('message req', 'req')

        self.assertFalse(browser.last_capture_observation['generation_observed'])
        self.assertFalse(browser.last_capture_observation['generation_ended'])
        self.assertFalse(browser.last_capture_observation['complete_current_text'])


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

    async def test_click_timeout_retries_once_only_after_exact_unsent_draft_is_proven(self):
        browser = OfflineAdapter(click_fails=True)
        with self.assertRaises(SubmissionAmbiguousError):
            await browser.exchange('message req', 'req')
        with self.assertRaises(SubmissionAmbiguousError):
            await browser.exchange('message req', 'req')
        self.assertEqual(browser.button.clicks, 2)

    async def test_transient_send_timeout_reuses_same_request_after_unsent_proof(self):
        browser = OfflineAdapter(transient_click_failures=1)
        commits = []

        result = await browser.exchange('message req', 'req', on_submitted=lambda: commits.append('req'))

        self.assertTrue(response_envelope_closed(result))
        self.assertEqual(browser.button.clicks, 2)
        self.assertEqual(commits, ['req'])
        self.assertTrue(browser.last_submission['committed'])

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
        browser = OfflineAdapter(answers=[stale] * 5 + [current], send_states=[True])
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
