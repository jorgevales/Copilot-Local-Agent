"""Startup consent authorizes exact prepared plans only for this agent lifetime."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from copilot_agent.approvals import ApprovalManager
from copilot_agent.session_mode import configure_session, START_PROMPT
from copilot_agent.state import SessionState


class SessionPlanApprovalTests(unittest.IsolatedAsyncioTestCase):
    def manager(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state = SessionState(Path(temporary.name) / 'session')
        manager = ApprovalManager(state, decide=AsyncMock(return_value='deny'), feedback=Mock())
        manager.session_plan_approval = True
        return manager, state

    async def test_exact_code_package_file_and_browser_plans_are_audited_without_prompts(self):
        manager, state = self.manager()
        cases = [('code_runner', {'script_sha256': 'abc', 'plan': {'script': 'print(1)'}}),
                 ('automation.run', {'approval_scope_type': 'automation_package',
                    'requires_fresh_run_confirmation': True, 'archive_sha256': '123',
                    'python_stage_reviews': [{'stage': 'one', 'script': 'print(1)'}]}),
                 ('files.create', {'path': 'S:/output.txt'}),
                 ('browser.click', {'owned_tab_id': 'tab-1', 'target': 'Save'})]
        hashes = []
        for index, (name, prepared) in enumerate(cases):
            call = {'name': name, 'call_id': str(index), 'arguments': {}}
            allowed, digest = await manager.request({'tool_requests': [call]}, call, prepared)
            self.assertTrue(allowed)
            hashes.append(digest)
        self.assertEqual(len(set(hashes)), 4)
        manager.decide.assert_not_called()
        self.assertEqual(state.data['approvals'], {})
        records = list((state.directory / 'approvals').glob('*.json'))
        self.assertEqual(len(records), 4)
        self.assertTrue(all(json.loads(path.read_text())['plan_hash'] in hashes for path in records))

    async def test_changed_prepared_source_gets_new_hash_and_revocation_prompts_again(self):
        manager, state = self.manager()
        call = {'name': 'code_runner', 'call_id': 'code', 'arguments': {}}
        plan = {'tool_requests': [call]}
        _, first = await manager.request(plan, call, {'script_sha256': 'first'})
        _, second = await manager.request(plan, call, {'script_sha256': 'second'})
        self.assertNotEqual(first, second)
        manager.revoke_session_grants()
        allowed, _ = await manager.request(plan, call, {'script_sha256': 'second'})
        self.assertFalse(allowed)
        manager.decide.assert_awaited_once()
        resumed = ApprovalManager(state, decide=AsyncMock(return_value='deny'), feedback=Mock())
        self.assertFalse(resumed.session_plan_approval)

    def test_startup_authority_is_explicit_ephemeral_and_revoke_resets_it(self):
        config = SimpleNamespace()
        configure_session(config, True, approve_plans=True)
        self.assertTrue(config._session_plan_approval)
        configure_session(config, False)
        self.assertFalse(config._session_plan_approval)
        configure_session(config, True)
        self.assertFalse(config._session_plan_approval)
        for phrase in ('file writes', 'code', 'package execution', 'without repeated', 'MFA', 'fresh session'):
            self.assertIn(phrase, START_PROMPT)

    def test_startup_grant_reaches_orchestrator_and_copilot_guidance(self):
        from copilot_agent.orchestrator import Orchestrator
        from tests.test_protocol_state import make_fixture
        from tests.test_orchestrator import MockBrowser
        root, config, state, registry = make_fixture('session-plan-wiring-')
        configure_session(config, True, approve_plans=True)
        with patch('copilot_agent.storage.discoveries_storage_paths', return_value={
                's_path': str(root), 'unc_path': str(root)}):
            engine = Orchestrator(config, MockBrowser([]), registry, state, display=lambda text: None)
        self.assertTrue(engine.approvals.session_plan_approval)
        message, _ = engine.prompts.build('user_turn', 'Perform the requested work.', 'request-1')
        self.assertTrue(json.loads(message)['session_plan_authorization']['active'])
        engine.approvals.revoke_session_grants()
        self.assertFalse(config._session_plan_approval)
        self.assertFalse(engine.approvals.session_plan_approval)

    async def test_batch_preparation_validation_still_rejects_mismatched_source(self):
        manager, _ = self.manager()
        call = {'name': 'code_runner', 'call_id': 'code', 'arguments': {}}
        with self.assertRaises(ValueError):
            await manager.request({'tool_requests': [call]}, call, {'script_sha256': 'changed'},
                                  prepared_plan={'code': {'script_sha256': 'original'}})
        manager.decide.assert_not_called()

    def test_direct_permission_update_uses_same_session_consent_after_preparation(self):
        from agent_ui.runtime import AgentRuntime
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.request_approval = Mock(side_effect=AssertionError('Repeated prompt'))
        state = Mock()
        context = {'config': SimpleNamespace(_session_plan_approval=True), 'session_state': state}
        runtime.permission_context = Mock(return_value=context)
        prepared = {'grant_id': 'exact-grant', 'scope': 'read-only'}
        with patch('copilot_agent.research_permissions.prepare_permissions', return_value=prepared) as prepare, \
                patch('copilot_agent.research_permissions.execute_permissions', new=AsyncMock(return_value={'status': 'updated'})) as execute:
            result = runtime.manage_permission('renew', 'exact-grant')
        self.assertEqual(result['status'], 'updated')
        prepare.assert_called_once()
        self.assertTrue(execute.call_args.args[2]['approved'])
        self.assertEqual(execute.call_args.args[2]['permission_reviewed'], prepared)
        state.event.assert_called_once()
        runtime.request_approval.assert_not_called()
