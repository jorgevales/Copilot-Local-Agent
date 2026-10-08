"""Automatic reconciliation uses the original owned tab and fresh page state."""
import tempfile
import unittest
from pathlib import Path

from copilot_agent.reconciliation import (ReconciliationRequired, capture_baseline, reconcile_browser_call,
                                          recover_missing_navigation, navigation_scope_allows, browser_diagnostics)
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry


class Page:
    def __init__(self, url, title):
        self.url, self.current_title = url, title
        self.closed = False

    async def title(self):
        return self.current_title

    def is_closed(self):
        return self.closed


class Browser:
    def __init__(self, page):
        self.tool_page = page
        self.page = Page('https://m365.cloud.microsoft/chat', 'Copilot')
        self._tool_pages = [page]
        self._navigation_state = {'tabs': {'tab-1': {'page': page}}}


class ReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = SessionState(Path(self.temp.name))
        self.state.data['website_private'] = True
        self.state.approve_domain('example.com')
        self.page = Page('https://example.com/start', 'Start')
        self.browser = Browser(self.page)
        self.call = {'call_id': 'nav-1', 'name': 'browser.plan', 'version': '1.0',
                     'arguments': {'task_id': 'move', 'steps': [
                         {'id': 'go', 'op': 'click', 'effect': 'navigation'}]}}
        baseline = await capture_baseline(self.browser, self.call)
        self.state.begin_call(self.call, reconciliation_baseline=baseline)
        self.state.finish_call('nav-1', {'ok': False, 'error': {'code': 'timeout'},
                                         'result': {'side_effects_uncertain': True}})

    async def test_completed_after_unexpected_destination_and_no_private_url_on_disk(self):
        self.page.url = 'https://example.com/actual?customer=private'
        self.page.current_title = 'Actual page'
        result = await reconcile_browser_call(self.state, self.browser, 'nav-1', 'completed', self.page.url, 'Actual page')
        self.assertEqual('completed', result['status'])
        self.assertEqual('completed', self.state.data['calls']['nav-1']['status'])
        self.assertNotIn('customer=private', self.state.path.read_text(encoding='utf-8'))
        self.state.begin_call(dict(self.call, call_id='next', arguments={'steps': []}))

    async def test_no_effect_requires_unchanged_page(self):
        result = await reconcile_browser_call(self.state, self.browser, 'nav-1', 'not_executed', self.page.url)
        self.assertEqual('not_executed', result['status'])
        self.assertTrue((await reconcile_browser_call(self.state, self.browser, 'nav-1', 'not_executed', self.page.url))['already_reconciled'])

    async def test_conflicts_keep_ledger_blocked(self):
        self.page.url = 'https://example.com/actual'
        with self.assertRaises(ReconciliationRequired):
            await reconcile_browser_call(self.state, self.browser, 'nav-1', 'completed', 'https://example.com/guessed')
        with self.assertRaises(ReconciliationRequired):
            await reconcile_browser_call(self.state, self.browser, 'nav-1', 'not_executed', self.page.url)
        self.assertEqual('uncertain', self.state.data['calls']['nav-1']['status'])

    async def test_requires_original_owned_tab(self):
        self.page.url = 'https://example.com/actual'
        self.browser._reconciliation_pages.clear()
        with self.assertRaises(ReconciliationRequired):
            await reconcile_browser_call(self.state, self.browser, 'nav-1', 'completed', self.page.url)

    async def test_tool_request_resolves_without_user_approval(self):
        self.page.url = 'https://example.com/actual'
        tool = ToolRegistry()
        result = await tool.execute('browser.reconcile', {'call_id': 'nav-1', 'outcome': 'completed',
                                    'observed_url': self.page.url},
                                    {'session_state': self.state, 'browser': self.browser,
                                     'session_dir': self.state.directory, 'approved': False})
        self.assertTrue(result['ok'], result)
        self.assertEqual('completed', self.state.data['calls']['nav-1']['status'])

    async def test_form_effect_has_no_automatic_reconciliation(self):
        write = {'call_id': 'write-1', 'name': 'browser.fill', 'version': '1.0',
                 'arguments': {'selector': '#name', 'text': 'x'}}
        self.assertIsNone(await capture_baseline(self.browser, write))

    async def test_read_only_checks_after_navigation_keep_plan_eligible(self):
        request = dict(self.call, arguments={'task_id': 'move', 'steps': [
            {'id': 'go', 'op': 'click', 'effect': 'navigation'},
            {'id': 'loaded', 'op': 'wait'}, {'id': 'verify', 'op': 'assert'}]})
        self.assertIsNotNone(await capture_baseline(self.browser, request))
        request['arguments']['steps'].append({'id': 'submit', 'op': 'press', 'key': 'Enter'})
        self.assertIsNone(await capture_baseline(self.browser, request))

    async def test_closed_navigation_is_quarantined_and_never_credited(self):
        self.page.closed = True
        self.assertEqual(['nav-1'], recover_missing_navigation(self.state, self.browser))
        call = self.state.data['calls']['nav-1']
        self.assertEqual('unverifiable_original_tab_missing', call['status'])
        self.assertFalse(call['completion_credited'])
        self.assertEqual([], recover_missing_navigation(self.state, self.browser))
        self.state.begin_call(dict(self.call, call_id='fresh', arguments={'steps': []}))

    async def test_restart_restores_safe_quarantine_not_completion(self):
        resumed = SessionState(self.state.directory, resume=True)
        new_browser = Browser(Page('about:blank', ''))
        recovered = recover_missing_navigation(resumed, new_browser)
        self.assertEqual(1, len(recovered))
        self.assertEqual('unverifiable_original_tab_missing', resumed.data['calls'][recovered[0]]['status'])
        self.assertEqual(1, len(resumed.context()['unverified_lost_navigation']))

    async def test_missing_tab_does_not_clear_form_uncertainty(self):
        self.page.closed = True
        self.state.data['calls']['nav-1'].pop('reconciliation_baseline')
        self.state.data['calls']['nav-1']['request']['name'] = 'browser.fill'
        self.assertEqual([], recover_missing_navigation(self.state, self.browser))
        with self.assertRaises(RuntimeError):
            self.state.begin_call(dict(self.call, call_id='fresh'))

    async def test_navigation_scope_excludes_forms_customer_context_and_new_domains(self):
        domains = {'example.com'}
        self.assertTrue(navigation_scope_allows(self.call, self.browser, domains))
        self.assertTrue(navigation_scope_allows({'name': 'browser.open', 'arguments': {'url': 'https://example.com/next'}}, self.browser, domains))
        self.assertFalse(navigation_scope_allows({'name': 'browser.open', 'arguments': {'url': 'https://other.example/'}}, self.browser, domains))
        self.assertFalse(navigation_scope_allows(dict(self.call, arguments={'customer_key': 'current'}), self.browser, domains))
        self.assertFalse(navigation_scope_allows({'name': 'browser.fill', 'arguments': {}}, self.browser, domains))

    async def test_changed_endpoint_cannot_reconcile_original_navigation(self):
        self.page.url = 'https://example.com/actual'
        self.browser.endpoint = 'http://127.0.0.1:9999'
        with self.assertRaises(ReconciliationRequired):
            await reconcile_browser_call(self.state, self.browser, 'nav-1', 'completed', self.page.url)

    async def test_diagnostics_operation_id_can_request_reconciliation(self):
        operation = browser_diagnostics(self.state, self.browser)['operations'][0]['operation_id']
        self.page.url = 'https://example.com/actual'
        result = await reconcile_browser_call(self.state, self.browser, operation, 'completed', self.page.url)
        self.assertEqual('completed', result['status'])

    async def test_multi_navigation_lost_tab_is_not_a_permanent_block(self):
        self.state.data['calls']['nav-1']['reconciliation_baseline']['transition_count'] = 2
        self.page.closed = True
        self.assertEqual(['nav-1'], recover_missing_navigation(self.state, self.browser))
        self.assertFalse(self.state.data['calls']['nav-1']['completion_credited'])

    async def test_consequential_navigation_never_uses_the_scope(self):
        request = {'name': 'browser.plan', 'arguments': {'steps': [
            {'op': 'navigate', 'url': 'https://example.com/next', 'effect': 'consequential'}]}}
        self.assertFalse(navigation_scope_allows(request, self.browser, {'example.com'}))

    async def test_missing_current_tab_does_not_stop_fresh_open_before_execution(self):
        self.page.closed = True
        request = {'name': 'browser.open', 'arguments': {'url': 'https://example.com/start'}}
        self.assertIsNone(await capture_baseline(self.browser, request))

    async def test_query_free_tool_observation_matches_private_fresh_url(self):
        self.page.url = 'https://example.com/actual?customer=private-value'
        result = await reconcile_browser_call(self.state, self.browser, 'nav-1', 'completed', 'https://example.com/actual')
        self.assertEqual('completed', result['status'])
        self.assertNotIn('private-value', self.state.path.read_text(encoding='utf-8'))


class RecoveryOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_tab_fresh_open_navigation_grant_and_visible_exchange(self):
        from tests.test_protocol_state import make_fixture
        from tests.test_orchestrator import MockBrowser, final_response, tool_response
        from copilot_agent.orchestrator import Orchestrator
        root, config, state, _ = make_fixture('navigation-recovery-')
        state.data['website_private'] = True
        state.approve_domain('example.com')
        browser = MockBrowser([final_response,
            lambda msg: tool_response(msg, 'fresh', 'browser.open', {'url': 'https://example.com/start'}),
            lambda msg: tool_response(msg, 'next', 'browser.open', {'url': 'https://example.com/next'}), final_response])
        browser.tool_page = Page('https://example.com/old', 'Old')
        browser.page = Page('https://m365.cloud.microsoft/chat', 'Copilot')
        browser._tool_pages = [browser.tool_page]
        prior = {'name': 'browser.open', 'call_id': 'lost', 'version': '1.0', 'arguments': {'url': 'https://example.com/old'}}
        baseline = await capture_baseline(browser, prior)
        state.begin_call(prior, reconciliation_baseline=baseline)
        state.finish_call('lost', {'ok': False, 'error': {'code': 'timeout'}})
        browser.tool_page.closed = True
        async def new_page():
            page = Page('about:blank', '')
            browser._tool_pages.append(page)
            return page
        browser.new_tool_page = new_page
        registry, calls, approvals, events = ToolRegistry(), [], [], []
        async def execute(name, args, context):
            self.assertTrue(context['approved'])
            calls.append(name)
            browser.tool_page.url = args['url']
            browser.tool_page.current_title = 'Fresh'
            return {'ok': True, 'result': {'url': args['url'], 'title': 'Fresh'}}
        registry.execute = execute
        def approve(preview):
            approvals.append(preview)
            return 'once'
        app = Orchestrator(config, browser, registry, state, approval_decider=approve,
                           display=lambda text: None, event_sink=lambda kind, payload: events.append((kind, payload)))
        await app.initialize()
        await app.turn('Discover the approved page after tab loss.')
        self.assertEqual(['browser.open', 'browser.open'], calls)
        self.assertEqual(1, len(approvals))
        self.assertIn('navigation_scope', approvals[0]['prepared_code'])
        self.assertEqual('unverifiable_original_tab_missing', state.data['calls']['lost']['status'])
        self.assertTrue(state.data['calls']['next']['state_changing'])
        self.assertTrue(any(kind == 'exchange' and payload.get('message_kind') == 'tool_results' for kind, payload in events))
        self.assertTrue(any(kind == 'exchange' and payload.get('actor') == 'Copilot' and 'Decision:' in payload['text'] for kind, payload in events))


if __name__ == '__main__':
    unittest.main()
