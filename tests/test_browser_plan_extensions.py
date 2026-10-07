import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from copilot_agent.approvals import ApprovalManager
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.tools import ToolRegistry


class QuietFeedback:
    def section(self, *args, **kwargs): pass
    def emit(self, *args, **kwargs): pass
    def record(self, *args, **kwargs): pass


class BrowserPlanExtensionTests(unittest.TestCase):
    def setUp(self):
        self.context = {'session_dir': Path(tempfile.mkdtemp(prefix='browser-extension-')), 'config': {}}

    def test_browser_wait_and_state_changing_controls_have_bounded_schemas(self):
        registry = ToolRegistry()
        self.assertEqual('read_only', registry.definition('browser.wait')['approval_policy'])
        self.assertEqual('user_approval', registry.definition('browser.press')['approval_policy'])
        self.assertEqual('user_approval', registry.definition('browser.select')['approval_policy'])
        registry.validate_input('browser.wait', {'selector': 'main'})
        with self.assertRaises(ValueError):
            registry.validate_call('browser.wait', {'selector': 'main', 'state': 'eventually'}, self.context)
        with self.assertRaises(ValueError):
            registry.validate_call('browser.press', {'selector': 'button', 'key': 'Control+Enter'}, self.context)

    def test_dependency_hosts_must_be_explicit_hostnames(self):
        registry = ToolRegistry()
        for host in ('*', '*.example.com', 'https://cdn.example.com', 'user@example.com'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                registry.validate_call('browser.open', {'url': 'https://example.com', 'allowed_domains': [host]}, self.context)
        registry.validate_call('browser.open', {'url': 'https://example.com', 'allowed_domains': ['cdn.example.com']}, self.context)

    def test_browser_approval_is_explicit_about_isolated_unauthenticated_profile(self):
        prepared = Orchestrator._browser_preparation({
            'name': 'browser.open', 'arguments': {'url': 'https://example.com'}})
        self.assertTrue(prepared['isolated_profile'])
        self.assertNotIn('shared_authenticated_profile', prepared)
        self.assertEqual('example.com', prepared['website_domain'])

    def test_approval_manager_accepts_only_complete_unique_browser_plan(self):
        root = Path(tempfile.mkdtemp(prefix='browser-plan-test-'))
        state = SimpleNamespace(directory=root, data={'approvals': {}})
        state.grant = lambda key, decision: state.data['approvals'].update({key: {'decision': decision}})
        manager = ApprovalManager(state, lambda preview: 'plan', QuietFeedback())
        calls = [
            {'call_id': 'open', 'name': 'browser.open', 'arguments': {'url': 'https://example.com'}},
            {'call_id': 'read', 'name': 'browser.read', 'arguments': {}},
        ]
        prepared = {'open': {'website_domain': 'example.com'}, 'read': {'managed_tab_only': True}}
        plan = {'tool_requests': calls, 'risk_summary': 'Synthetic browser plan'}

        async def exercise():
            for call in calls:
                allowed, _ = await manager.request(plan, call, prepared[call['call_id']], prepared_plan=prepared)
                self.assertTrue(allowed)

        import asyncio
        asyncio.run(exercise())
        with self.assertRaises(ValueError):
            import asyncio
            asyncio.run(manager.request(plan, calls[0], prepared['open'], prepared_plan={'open': prepared['open']}))


if __name__ == '__main__':
    unittest.main()
