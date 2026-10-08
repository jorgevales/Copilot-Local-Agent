"""Automatic reconciliation uses the original owned tab and fresh page state."""
import tempfile
import unittest
from pathlib import Path

from copilot_agent.reconciliation import ReconciliationRequired, capture_baseline, reconcile_browser_call
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry


class Page:
    def __init__(self, url, title):
        self.url, self.current_title = url, title

    async def title(self):
        return self.current_title

    def is_closed(self):
        return False


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


if __name__ == '__main__':
    unittest.main()
