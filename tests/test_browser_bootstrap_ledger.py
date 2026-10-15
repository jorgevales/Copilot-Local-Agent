import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.orchestrator import Orchestrator
from copilot_agent.policy import PathPolicy, PolicyError
from copilot_agent.reconciliation import abandon_uncertain_browser_call
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry
from tests import test_orchestrator as orchestration
from tests import test_protocol_state as protocol_fixtures


class BootstrapLedgerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = SessionState(self.root / 'session')
        self.state.approve_domain('example.com')
        self.state.approve_domain('studio.example')
        self.owner = object()
        self.browser = SimpleNamespace(tool_page=None, tool_context=self.owner, context=self.owner,
            _tool_pages=[], _navigation_state=None, config=SimpleNamespace(_permissive_session=False))
        async def new_page():
            page = SimpleNamespace(url='about:blank', context=self.owner, closed=False)
            page.is_closed = lambda: page.closed
            async def goto(url, **kwargs): page.url = url
            async def close(): page.closed = True
            page.goto, page.close, page.title = goto, close, AsyncMock(return_value='Fresh checkpoint')
            self.browser._tool_pages.append(page)
            return page
        self.browser.new_tool_page = AsyncMock(side_effect=new_page)
        self.context = {'browser': self.browser, 'session_state': self.state,
                        'session_dir': self.state.directory, 'policy': PathPolicy([self.root]),
                        'approved': True, 'config': {}}

    async def test_list_before_open_is_an_empty_read_without_approval(self):
        self.context['approved'] = False
        response = await ToolRegistry().execute('browser.tabs', {'operation': 'list'}, self.context)
        self.assertTrue(response['ok'], response)
        self.assertEqual([], response['result']['tabs'])
        self.browser.new_tool_page.assert_not_awaited()
        info = await ToolRegistry().execute('browser.info', {}, self.context)
        self.assertTrue(info['ok'], info)
        self.assertFalse(info['result']['owned_page_available'])
        self.assertEqual('browser.open', info['result']['next_action'])

    def test_failed_tab_inventory_never_locks_the_browser_domain(self):
        call = {'call_id': 'inventory', 'name': 'browser.tabs', 'version': '1.0', 'arguments': {'operation': 'list'}}
        self.state.begin_call(call, state_changing=True)
        self.state.finish_call('inventory', {'ok': False, 'error': {'code': 'policy_denied', 'message': 'Owned tool page is unavailable'}})
        self.assertFalse(self.state.data['calls']['inventory']['state_changing'])
        self.assertEqual('completed', self.state.data['calls']['inventory']['status'])
        self.state.begin_call({'call_id': 'open', 'name': 'browser.open', 'version': '1.0', 'arguments': {'url': 'https://studio.example/'}})

    async def test_missing_original_tab_can_establish_an_approved_fresh_checkpoint(self):
        request = {'call_id': 'old', 'name': 'browser.click', 'version': '1.0', 'arguments': {'selector': '#search'}}
        self.state.begin_call(request)
        self.state.finish_call('old', {'ok': False, 'error': {'code': 'policy_denied', 'message': 'Owned tool page is unavailable'}})
        result = await abandon_uncertain_browser_call(self.state, self.browser, 'old', 'https://studio.example/')
        self.assertEqual('checkpoint_verified', result['status'])
        self.assertFalse(result['completion_credited'])
        self.assertEqual('abandoned_unverifiable', self.state.data['calls']['old']['status'])

    async def test_recovery_validation_failure_is_not_another_uncertain_operation(self):
        page = await self.browser.new_tool_page()
        page.url = 'https://example.com/original'
        self.browser.tool_page = page
        self.state.begin_call({'call_id': 'old', 'name': 'browser.click', 'version': '1.0', 'arguments': {'selector': '#submit'}})
        self.state.finish_call('old', {'ok': False, 'error': {'code': 'timeout'}})
        request = {'call_id': 'recover', 'name': 'browser.recover_uncertain', 'version': '1.0',
                   'arguments': {'call_id': 'old', 'checkpoint_url': 'https://studio.example/'}}
        self.state.begin_call(request, uncertainty_recovery=True)
        response = await ToolRegistry().execute(request['name'], request['arguments'], self.context)
        self.state.finish_call('recover', response)
        self.assertFalse(response['ok'])
        self.assertFalse(response['result'].get('side_effects_uncertain', True), response)
        self.assertEqual('completed', self.state.data['calls']['recover']['status'])
        self.assertEqual('uncertain', self.state.data['calls']['old']['status'])
        self.assertEqual(1, self.browser.new_tool_page.await_count)

    async def test_orchestrator_lists_before_open_without_approval_or_uncertain_ledger(self):
        def list_request(message):
            response = orchestration.tool_response(message, 'inventory', 'browser.tabs', {'operation': 'list'})
            response['approval_required'] = False
            return response
        with patch('copilot_agent.policy.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')), \
             patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')):
            root, config, state, _ = protocol_fixtures.make_fixture('bootstrap-ledger-')
            browser = orchestration.MockBrowser([orchestration.final_response, list_request, orchestration.final_response])
            browser.tool_page, browser.tool_context, browser._tool_pages = None, object(), []
            app = Orchestrator(config, browser, ToolRegistry(), state,
                approval_decider=lambda _: self.fail('Tab inventory requested approval'), display=lambda _: None)
            await app.initialize()
            await app.turn('List the owned website tabs before opening a website.')
            call = state.data['calls']['inventory']
            self.assertFalse(call['state_changing'])
            self.assertTrue(call['result']['ok'], call['result'])
            self.assertEqual('completed', call['status'])
            call.update(status='abandoned_unverifiable', result={'ok': False, 'error': {'code': 'policy_denied'}})
            def repeated_inventory(message):
                response = orchestration.tool_response(message, 'inventory-again', 'browser.tabs', {'operation': 'list'})
                response['approval_required'] = False
                return response
            browser.responders.extend([repeated_inventory, orchestration.final_response])
            await app.turn('List tabs again; the previous inventory was incorrectly quarantined.')
            self.assertTrue(state.data['calls']['inventory-again']['result']['ok'])

    def test_legacy_inventory_and_preflight_refusal_are_repaired_but_real_effect_is_retained(self):
        for call_id, name, arguments, message in (
            ('inventory', 'browser.tabs', {'operation': 'list'}, 'Owned tool page is unavailable'),
            ('recovery', 'browser.recover_uncertain', {'call_id': 'inventory', 'checkpoint_url': 'https://studio.example/'},
             'Recovery checkpoint must remain on the uncertain action website'),
            ('actual-write', 'browser.click', {'selector': '#submit'}, 'Timed out after submitting')):
            self.state.data['calls'][call_id] = {'status': 'uncertain', 'state_changing': True,
                'request': {'name': name, 'version': '1.0', 'arguments': arguments},
                'result': {'ok': False, 'error': {'code': 'policy_denied', 'message': message}}}
        self.assertEqual(['inventory', 'recovery'], self.state.repair_browser_observations())
        for call_id in ('inventory', 'recovery'):
            self.assertEqual('completed', self.state.data['calls'][call_id]['status'])
            self.assertFalse(self.state.data['calls'][call_id]['completion_credited'])
        self.assertEqual('uncertain', self.state.data['calls']['actual-write']['status'])
        self.assertEqual([], self.state.repair_browser_observations())

    def test_private_resume_keeps_observation_identity_and_does_not_lock_on_an_interrupted_list(self):
        self.state.data['website_private'] = True
        self.state.begin_call({'call_id': 'inventory', 'name': 'browser.tabs', 'version': '1.0', 'arguments': {'operation': 'list'}})
        resumed = SessionState(self.state.directory, resume=True)
        call = next(iter(resumed.data['calls'].values()))
        self.assertTrue(call['browser_observation_only'])
        self.assertFalse(call['state_changing'])
        self.assertEqual('completed', call['status'])

    def test_ledger_repair_preserves_an_unresolved_copilot_submission(self):
        self.state.begin_call({'call_id': 'inventory', 'name': 'browser.tabs', 'version': '1.0', 'arguments': {'operation': 'list'}})
        self.state.data['calls']['inventory']['status'] = 'uncertain'
        self.state.data['pending_submission'] = {'request_id': 'pending'}
        self.state.data['status'] = 'submission_uncertain'
        self.state.repair_browser_observations()
        self.assertEqual('submission_uncertain', self.state.data['status'])
