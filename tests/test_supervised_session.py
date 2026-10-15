import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from copilot_agent.approvals import ApprovalManager
from copilot_agent.config import Config
from copilot_agent.policy import PolicyError
from copilot_agent.state import SessionState
from copilot_agent.session_mode import configure_session
from copilot_agent.web_navigation import _candidates, validate_navigation
from tests import test_orchestrator as orchestrator_tests
from tests.test_orchestrator import final_response, tool_response
from tests.test_web_navigation import search_plan


class SupervisedSessionTests(unittest.IsolatedAsyncioTestCase):
    def manager(self):
        directory = tempfile.TemporaryDirectory(prefix='supervised-session-')
        self.addCleanup(directory.cleanup)
        decide = AsyncMock(return_value='deny')
        manager = ApprovalManager(SessionState(Path(directory.name)), decide)
        manager.discovery_session = True
        return manager, decide

    async def test_effectful_plans_and_revisions_are_hash_bound_and_each_need_approval(self):
        manager, decide = self.manager()
        decide.return_value = 'once'
        digests = []
        for index, name in enumerate(('code_runner', 'browser.plan', 'files.grant_path', 'local_attachment', 'automation.run')):
            call = {'call_id': str(index), 'name': name, 'arguments': {'path': 'revised-' + str(index)}}
            prepared = {'approval_scope_type': 'automation_package', 'requires_fresh_run_confirmation': True} if name == 'automation.run' else None
            plan={'tool_requests':[call]}
            if name=='local_attachment':
                plan['files']=[{'path':'synthetic-fixture.txt','name':'synthetic-fixture.txt'}]
            allowed, digest = await manager.request(plan, call, prepared)
            self.assertTrue(allowed)
            digests.append(digest)
        self.assertEqual(len(digests), len(set(digests)))
        self.assertEqual(5,decide.await_count)
        self.assertEqual(5,len(manager.state.data['approvals']))
        self.assertTrue(all(grant['decision']=='once' for grant in manager.state.data['approvals'].values()))

    async def test_grant_is_ephemeral_revocable_and_not_in_config_or_restored_state(self):
        manager, decide = self.manager()
        config = Config()
        configure_session(config,True)
        self.assertNotIn('_discovery_session', config.as_dict())
        self.assertFalse(ApprovalManager(manager.state).discovery_session)
        manager.revoke_session_grants()
        call = {'call_id': 'after-close', 'name': 'synthetic.write', 'arguments': {}}
        self.assertFalse((await manager.request({'tool_requests': [call]}, call))[0])
        decide.assert_awaited_once()

    async def test_supervision_does_not_accept_mismatched_prepared_code(self):
        manager, decide = self.manager()
        call = {'call_id': 'code', 'name': 'code_runner', 'arguments': {}}
        with self.assertRaises(ValueError):
            await manager.request({'tool_requests': [call]}, call, {'script_sha256': 'new'},
                                  prepared_plan={'code': {'script_sha256': 'old'}})
        decide.assert_not_awaited()

    async def test_option_four_authorizes_current_action_and_discovery_without_future_effect_bypass(self):
        manager, decide = self.manager()
        manager.discovery_session = False
        callback = MagicMock()
        manager.on_discovery_grant = callback
        decide.side_effect = ['supervised','deny']
        call = {'call_id': 'start', 'name': 'synthetic.write', 'arguments': {}}
        self.assertTrue((await manager.request({'tool_requests': [call]}, call))[0])
        self.assertTrue(manager.discovery_session)
        self.assertFalse(manager.supervised_session)
        callback.assert_called_once()
        revised = {**call, 'call_id': 'revised', 'arguments': {'path': 'different.txt'}}
        self.assertFalse((await manager.request({'tool_requests': [revised]}, revised))[0])
        self.assertEqual(2,decide.await_count)
        self.assertTrue(all(grant['decision']=='deny' for grant in manager.state.data['approvals'].values()))

    async def test_unnamed_roles_position_and_xpath_are_valid_runtime_locators(self):
        for locator in ({'role': 'button', 'nth': 1}, {'xpath': '//button[2]'}, {'css': 'button:nth-of-type(2)'}):
            plan = copy.deepcopy(search_plan())
            plan['steps'][0]['locator'] = locator
            validate_navigation('browser.plan', plan)
        page = MagicMock()
        result = await _candidates(page, {'role': 'button', 'nth': 1}, {})
        page.get_by_role.assert_called_once_with('button')
        page.get_by_role.return_value.nth.assert_called_once_with(1)
        self.assertEqual([('role', page.get_by_role.return_value.nth.return_value)], result)

    async def test_small_repair_keeps_technique_and_requests_fresh_exact_approval(self):
        with patch('copilot_agent.policy.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')), \
             patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')):
            fixture = orchestrator_tests.OrchestratorTests()
            decide=AsyncMock(return_value='once')
            root, config, state, registry, browser, app = fixture.fixture([
                final_response,
                lambda msg: tool_response(msg, 'first', 'synthetic.write', {'path': 'typo.txt'}),
                lambda msg: tool_response(msg, 'repair', 'synthetic.write', {'path': 'type.txt'}),
                final_response], decide)
            configure_session(config,True)
            app.approvals.discovery_session = True
            observed = []
            async def execute(name, args, context):
                self.assertTrue(context['approved'])
                observed.append(args['path'])
                return {'ok': len(observed) == 2, 'result': {'status': 'completed' if len(observed) == 2 else 'not_started',
                    'side_effects_uncertain': False}, **({} if len(observed) == 2 else {'error': {'code': 'operation_failed', 'message': 'Correct the path typo.'}})}
            registry.execute = execute
            await app.initialize()
            await app.turn('Repair the specific failing path and continue the same technique.')
            self.assertEqual(['typo.txt', 'type.txt'], observed)
            self.assertEqual(2,decide.await_count)
            self.assertEqual([], state.data['retry_records'])
