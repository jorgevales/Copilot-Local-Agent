import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from copilot_agent.approvals import ApprovalManager
from copilot_agent.config import Config
from copilot_agent.policy import PolicyError
from copilot_agent.state import SessionState
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
        manager.supervised_session = True
        return manager, decide

    async def test_all_valid_plans_and_revisions_are_hash_bound_without_prompts(self):
        manager, decide = self.manager()
        digests = []
        for index, name in enumerate(('code_runner', 'browser.plan', 'files.grant_path', 'local_attachment', 'automation.run')):
            call = {'call_id': str(index), 'name': name, 'arguments': {'path': 'revised-' + str(index)}}
            prepared = {'approval_scope_type': 'automation_package', 'requires_fresh_run_confirmation': True} if name == 'automation.run' else None
            allowed, digest = await manager.request({'tool_requests': [call]}, call, prepared)
            self.assertTrue(allowed)
            digests.append(digest)
        self.assertEqual(len(digests), len(set(digests)))
        decide.assert_not_awaited()
        self.assertEqual({}, manager.state.data['approvals'])

    async def test_grant_is_ephemeral_revocable_and_not_in_config_or_restored_state(self):
        manager, decide = self.manager()
        config = Config()
        config._supervised_session = True
        self.assertNotIn('_supervised_session', config.as_dict())
        self.assertFalse(ApprovalManager(manager.state).supervised_session)
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

    async def test_fresh_conversation_can_authorize_all_plans_once(self):
        manager, decide = self.manager()
        manager.supervised_session = False
        decide.return_value = 'supervised'
        call = {'call_id': 'start', 'name': 'synthetic.write', 'arguments': {}}
        self.assertTrue((await manager.request({'tool_requests': [call]}, call))[0])
        self.assertTrue(manager.supervised_session)
        revised = {**call, 'call_id': 'revised', 'arguments': {'path': 'different.txt'}}
        self.assertTrue((await manager.request({'tool_requests': [revised]}, revised))[0])
        decide.assert_awaited_once()
        self.assertEqual({}, manager.state.data['approvals'])

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

    async def test_small_repair_reuses_failed_technique_without_reapproval(self):
        with patch('copilot_agent.policy.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')), \
             patch('copilot_agent.config.mapped_s_drive_root', side_effect=PolicyError('Offline fixture')):
            fixture = orchestrator_tests.OrchestratorTests()
            root, config, state, registry, browser, app = fixture.fixture([
                final_response,
                lambda msg: tool_response(msg, 'first', 'synthetic.write', {'path': 'typo.txt'}),
                lambda msg: tool_response(msg, 'repair', 'synthetic.write', {'path': 'type.txt'}),
                final_response], lambda _: self.fail('Individual approval requested'))
            app.approvals.supervised_session = True
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
            self.assertEqual([], state.data['retry_records'])
