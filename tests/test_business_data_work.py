"""Customer/company data is usable; effects and record identity remain checked."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.automation_packages import _package_requires_fresh_confirmation
from copilot_agent.policy import PathPolicy
from copilot_agent.reconciliation import navigation_scope_allows
from copilot_agent.tools import ToolRegistry


class BusinessDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_customer_summary_reaches_real_tool_route_without_durable_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            context = {'config': {'customer_data_work': True}, 'session_dir': directory,
                       'customer_key': 'customer-one', 'approved': True}
            expected = {'status': 'verified', 'identity_verified': True, 'facts': [{'value': 'Business data'}]}
            with patch('copilot_agent.tools.execute_navigation', new=AsyncMock(return_value=expected)) as run:
                result = await ToolRegistry()._execute('browser.customer_summary',
                    {'customer_key': 'customer-one'}, context, PathPolicy([directory]))
            self.assertEqual(expected, result)
            run.assert_awaited_once()

    def test_customer_summary_is_an_identity_checked_read(self):
        self.assertEqual('read_only', ToolRegistry().definition('browser.customer_summary')['approval_policy'])
        self.assertIsNone(ToolRegistry().definition('browser.customer_summary')['output_size_limit'])

    def test_complete_customer_results_reach_attachment_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'customer': str(i), 'text': 'Observed business data. ' * 1000} for i in range(10)]
            original = {'ok': True, 'tool': 'browser.customer_summary', 'result': {'facts': rows}}
            result = ToolRegistry()._limit(original, {'config': {'customer_data_work': True},
                'website_private': True, 'session_dir': directory})
            self.assertEqual(original, result)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_customer_navigation_uses_existing_origin_grant(self):
        page = SimpleNamespace(url='https://example.com/customers/one', is_closed=lambda: False)
        browser = SimpleNamespace(tool_page=page, page=object(), chat_page=object(), _tool_pages=[page],
            _navigation_state={'tabs': {'tab-1': {'page': page}}})
        request = {'name': 'browser.plan', 'arguments': {'customer_key': 'customer-one',
            'steps': [{'op': 'navigate', 'url': 'https://example.com/customers/one/documents'}]}}
        self.assertTrue(navigation_scope_allows(request, browser, ['example.com']))
        request['arguments']['steps'] = [{'op': 'click', 'effect': 'consequential'}]
        self.assertFalse(navigation_scope_allows(request, browser, ['example.com']))

    def test_package_session_grant_covers_customer_reads_and_internal_navigation(self):
        for tool_id, arguments in (
            ('browser.customer_summary', {'customer_key': 'customer-one'}),
            ('browser.open', {'url': 'https://service.internal/customers'}),
            ('browser.tabs', {'operation': 'open', 'url': 'https://10.0.0.8/customers'}),
            ('browser.plan', {'customer_key': 'customer-one', 'steps': [
                {'op': 'navigate', 'url': 'https://service.internal/customers/one'},
                {'op': 'capture'}]})):
            with self.subTest(tool_id=tool_id):
                self.assertFalse(_package_requires_fresh_confirmation({'stages': [
                    {'kind': 'tool', 'tool_id': tool_id, 'arguments': arguments}]}))
        self.assertTrue(_package_requires_fresh_confirmation({'stages': [
            {'kind': 'tool', 'tool_id': 'browser.plan', 'arguments': {
                'steps': [{'op': 'click', 'effect': 'consequential'}]}}]}))

    def test_secret_redaction_survives_full_result_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            result = ToolRegistry()._limit({'ok': True, 'tool': 'synthetic',
                'result': {'text': 'api_key=synthetic-secret ' + 'x' * 20000}},
                {'config': {'customer_data_work': True}, 'session_dir': directory})
            self.assertNotIn('synthetic-secret', json.dumps(result))
            self.assertEqual(20000, result['result']['text'].count('x'))
