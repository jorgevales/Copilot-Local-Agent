"""Startup latency contracts without launching Edge or sending Copilot messages."""
from pathlib import Path
from types import SimpleNamespace
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from copilot_agent.app import configure_local_knowledge_test, run
from copilot_agent.config import Config
from copilot_agent.policy import PolicyError
from copilot_agent.state import SessionState, latest_committed_request_id
from tests.test_protocol_state import make_fixture


class StartupBrowser:
    def __init__(self, events, reconciled_draft=None):
        self.events = events
        self.model_label = None
        self.reconciled_draft = reconciled_draft

    async def start(self, resume_request_id=None):
        self.events.append('browser:start' + (':' + resume_request_id if resume_request_id else ''))

    async def discover_models(self):
        self.events.append('browser:discover')
        return [
            {'label': 'GPT-6 Sol', 'enabled': True, 'provider': 'OpenAI'},
            {'label': 'Alternate model', 'enabled': True, 'provider': 'OpenAI'},
        ]

    async def select_model(self, label):
        self.events.append('browser:select:' + label)
        self.model_label = label
        return {'label': label, 'checked': True}

    async def verify_interaction_ready(self, expected_model, request_id=None):
        self.events.append('browser:ready:' + expected_model)
        return True

    async def read_reconciled_draft(self, request_id, expected_sha256):
        self.events.append('browser:read-draft:' + request_id)
        return self.reconciled_draft

    async def exchange(self, text, request_id, on_submitted=None):
        self.events.append('browser:exchange:' + request_id)
        if on_submitted:
            on_submitted()
        return 'captured response'

    async def close(self):
        self.events.append('browser:close')


class LocalKnowledgeTestStoreTests(unittest.TestCase):
    def test_local_c_store_requires_empty_direct_localappdata_child(self):
        if os.name != 'nt':
            self.skipTest('C: path policy is Windows-specific')
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp)
            if local.drive.upper() != 'C:':
                self.skipTest('Temporary directory is not on C:')
            parent = local / 'CopilotLocalAgent' / 'live-navigation-tests'
            parent.mkdir(parents=True)
            target = parent / 'run-one'
            config = Config(root=Path(__file__).resolve().parents[1], storage_dir=local / 'runtime')
            with patch.dict(os.environ, {'LOCALAPPDATA': str(local)}):
                configured = configure_local_knowledge_test(config, target)
            self.assertEqual(target.resolve(), configured.resolve())
            self.assertTrue(config._local_knowledge_test_mode)
            self.assertEqual((target / 'Discoveries knowledge').resolve(), config.knowledge_directory.resolve())
            self.assertEqual([str(target.resolve())], config.allowed_roots)
            with self.assertRaisesRegex(ValueError, 'direct child'):
                configure_local_knowledge_test(Config(root=config.root, storage_dir=local / 'other'), target / 'nested')

    def test_local_c_store_preserves_nonempty_existing_target(self):
        if os.name != 'nt':
            self.skipTest('C: path policy is Windows-specific')
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp)
            if local.drive.upper() != 'C:':
                self.skipTest('Temporary directory is not on C:')
            parent = local / 'CopilotLocalAgent' / 'live-navigation-tests'
            target = parent / 'existing'
            target.mkdir(parents=True)
            (target / 'keep.txt').write_text('keep', encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': str(local)}):
                with self.assertRaisesRegex(ValueError, 'must be empty'):
                    configure_local_knowledge_test(Config(root=Path(__file__).resolve().parents[1], storage_dir=local), target)
            self.assertEqual('keep', (target / 'keep.txt').read_text(encoding='utf-8'))


class StartupOrchestrator:
    events = None
    last_config = None

    def __init__(self, config, browser, registry, state, **kwargs):
        type(self).last_config = config
        self.browser = browser
        self.state = state
        self.feedback = SimpleNamespace(color=False)
        self.base_context = {}
        self.findings = SimpleNamespace(data={'findings': []})
        self.events.append('orchestrator:create')

    async def prepare_initialization(self):
        self.events.append('orchestrator:preload')
        return {'request_id': 'synthetic', 'attachment_count': 8}

    async def initialize(self):
        self.events.append('orchestrator:initialize')
        self.state.data['status'] = 'ready'
        return {'response_type': 'final'}

    async def recover_capture_failed_turn(self):
        self.events.append('orchestrator:recover_capture')
        self.state.data['status'] = 'ready'
        return {'response_type': 'final'}

    async def turn(self, user_input, recovered_response=None):
        self.events.append('orchestrator:resume-draft')
        self.asserted_recovered_response = recovered_response
        return {'response_type': 'final'}

    def attachment_queue(self):
        return SimpleNamespace(records=lambda: [], verify=lambda: None,
                               paths=lambda: [], clear=lambda: None)

    async def close(self, **kwargs):
        self.events.append('orchestrator:close')


class StartupFlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_flow(self, answers, explicit_model=None, configured_model='GPT-6 Sol',
                       resume=False, resume_capture=False, resume_unsent=False,
                       exact_attach=False, portable_storage=None, no_share=False,
                       remembered_roots=None, capture_config=False):
        root, config, _, _ = make_fixture('app-startup-flow-')
        config.storage_dir = root
        config.model = configured_model
        config.profile_dir = root / 'profile'
        resume_path = None
        if resume:
            resume_path = config.runtime_dir / 'sessions' / 'existing'
            saved = SessionState(resume_path)
            saved.data['message_count'] = 1
            saved.message('copilot_outbound', 'Initialization already committed.', request_id='prior-request')
            reconciled_draft = 'Exact previously unsent request request_id reconciled-draft'
            if resume_unsent:
                saved.begin_submission('reconciled-draft', reconciled_draft)
                saved.reconcile_submission(False)
            if resume_capture:
                saved.event('capture_failed', request_id='prior-request')
                saved.data['status'] = 'closed'
            else:
                saved.data['status'] = 'ready'
            saved.save()
        events = []
        browser = StartupBrowser(events, reconciled_draft if resume_unsent else None)
        StartupOrchestrator.events = events
        StartupOrchestrator.last_config = None
        replies = iter(answers)

        async def answer(prompt):
            events.append('ask:' + prompt)
            return next(replies)

        explicit_profile = config.storage_dir / 'dedicated-edge-profile' if exact_attach else None
        args = SimpleNamespace(config=None, attach_existing=exact_attach,
                               port=63741 if exact_attach else None,
                               profile=explicit_profile, model=explicit_model, setup_only=False,
                               resume=resume_path, yes_setup=True)
        endpoint_choice = AsyncMock()
        mapped_patch = {'side_effect': PolicyError('unavailable')} if no_share else {'return_value': root}
        selected_storage = Path(portable_storage) if portable_storage else root
        remembered_settings = ({'config': {'allowed_roots': remembered_roots}}
                               if remembered_roots is not None else {})
        with patch.dict(os.environ), \
             patch('copilot_agent.app._UI_PERMISSION_CONTEXT'), \
             patch('copilot_agent.app.Config.load', return_value=config), \
             patch('copilot_agent.app.validate_user_storage_directory', side_effect=lambda path: Path(path)), \
             patch('copilot_agent.app.read_user_settings', return_value=remembered_settings), \
             patch('copilot_agent.app.save_user_settings'), \
             patch('copilot_agent.app.configure_temp_directory',
                   side_effect=lambda storage_root: events.append('temp:verified') or root / 'verified-temp'), \
             patch('copilot_agent.app.discoveries_storage', return_value=selected_storage), \
             patch('copilot_agent.storage.discoveries_storage_paths', return_value={
                 's_path': str(selected_storage) if no_share else r'S:\Discoveries knowledge',
                 'unc_path': str(selected_storage)}), \
             patch('copilot_agent.app.mapped_s_drive_root', **mapped_patch), \
             patch('copilot_agent.config.mapped_s_drive_root', **mapped_patch), \
             patch('copilot_agent.app.choose_edge', new=AsyncMock(side_effect=lambda *a, **k: events.append('edge:choose'))), \
             patch('copilot_agent.app.choose_browser_endpoint', new=endpoint_choice), \
             patch('copilot_agent.app.BrowserAdapter', return_value=browser), \
             patch('copilot_agent.app.Orchestrator', StartupOrchestrator), \
             patch('copilot_agent.app.ask', side_effect=answer), \
             patch('copilot_agent.app.system'):
            await run(args)
        if exact_attach:
            return events, endpoint_choice.await_args.args[0]
        if capture_config:
            return events, StartupOrchestrator.last_config
        return events

    async def test_resume_page_binding_uses_last_confirmed_request_not_uncommitted_tail(self):
        root, config, _, _ = make_fixture('app-resume-binding-')
        state = SessionState(config.runtime_dir / 'sessions' / 'existing')
        state.data['message_count'] = 1
        state.message('copilot_outbound', 'confirmed request', request_id='confirmed')
        state.message('copilot_outbound', 'unconfirmed pending request', request_id='pending')

        self.assertEqual('confirmed', latest_committed_request_id(state))

    async def test_single_tab_discovery_precedes_preload_and_readiness_precedes_prompt(self):
        events = await self.run_flow(['', ':exit'])
        model_prompt = next(item for item in events if item.startswith('ask:Choose'))
        user_prompt = next(item for item in events if item == 'ask:You: ')

        self.assertLess(events.index('browser:discover'), events.index('orchestrator:preload'))
        self.assertLess(events.index('temp:verified'), events.index('edge:choose'))
        self.assertFalse(any(item == 'browser:discover-aux' for item in events))
        self.assertLess(events.index('browser:select:GPT-6 Sol'), events.index(model_prompt))
        self.assertEqual(1, events.count('browser:select:GPT-6 Sol'))
        self.assertLess(events.index(model_prompt), events.index('orchestrator:preload'))
        self.assertLess(events.index('orchestrator:initialize'),
                        events.index('browser:ready:GPT-6 Sol'))
        self.assertLess(events.index('browser:ready:GPT-6 Sol'), events.index(user_prompt))

    async def test_explicit_attach_binds_exact_port_and_profile_before_endpoint_selection(self):
        events, selected_config = await self.run_flow(['', ':exit'], exact_attach=True)
        self.assertTrue(selected_config.attach_existing)
        self.assertEqual(63741, selected_config.debug_port)
        self.assertEqual((63741, str(selected_config.profile_dir.resolve())),
                         selected_config._proof_exact_edge_endpoint)
        self.assertIn('edge:choose', events)

    async def test_normal_startup_uses_portable_store_and_discards_stale_remembered_roots(self):
        root, _, _, _ = make_fixture('app-portable-storage-')
        portable = root / 'local-app-data' / 'CopilotLocalAgent' / 'Discoveries knowledge'
        stale = root.parent / (root.name + '-old-laptop-storage')
        allowed_child = portable / 'operator-workspace'
        events, config = await self.run_flow(
            ['', ':exit'], portable_storage=portable, no_share=True,
            remembered_roots=[str(stale), str(allowed_child)], capture_config=True)

        self.assertTrue(config._portable_storage_verified)
        self.assertFalse(config._s_storage_verified)
        self.assertEqual(portable.resolve(), config.storage_dir.resolve())
        self.assertEqual(portable.resolve(), config.knowledge_directory.resolve())
        roots = [Path(value).resolve() for value in config.allowed_roots]
        self.assertIn(portable.resolve(), roots)
        self.assertIn(allowed_child.resolve(), roots)
        self.assertTrue(all(path == portable.resolve() or portable.resolve() in path.parents
                            for path in roots))
        self.assertFalse(stale.exists())
        self.assertTrue(allowed_child.exists())

    async def test_alternate_choice_changes_model_once_after_default_preselection(self):
        events = await self.run_flow(['2', ':exit'])

        self.assertEqual(1, events.count('browser:select:GPT-6 Sol'))
        self.assertEqual(1, events.count('browser:select:Alternate model'))
        self.assertLess(events.index('browser:select:GPT-6 Sol'),
                        events.index('browser:select:Alternate model'))
        self.assertLess(events.index('browser:select:Alternate model'),
                        events.index('orchestrator:initialize'))
        self.assertLess(events.index('orchestrator:initialize'),
                        events.index('browser:ready:Alternate model'))

    async def test_legacy_empty_saved_model_migrates_to_product_default(self):
        events = await self.run_flow(['', ':exit'], configured_model='')

        self.assertEqual(1, events.count('browser:select:GPT-6 Sol'))

    async def test_resuming_existing_conversation_does_not_reinitialize_or_send(self):
        events = await self.run_flow([':exit'], explicit_model='GPT-6 Sol', resume=True)

        self.assertIn('browser:start:prior-request', events)
        self.assertNotIn('orchestrator:preload', events)
        self.assertNotIn('orchestrator:initialize', events)
        self.assertNotIn('browser:exchange', events)
        self.assertIn('browser:ready:GPT-6 Sol', events)

    async def test_resume_recovers_closed_capture_failure_without_initializing(self):
        events = await self.run_flow([':exit'], explicit_model='GPT-6 Sol', resume=True,
                                     resume_capture=True)

        self.assertIn('orchestrator:recover_capture', events)
        self.assertIn('browser:start:prior-request', events)
        self.assertNotIn('orchestrator:preload', events)
        self.assertNotIn('orchestrator:initialize', events)
        self.assertNotIn('browser:exchange', events)

    async def test_resume_resends_only_hash_matched_draft_confirmed_not_sent(self):
        events = await self.run_flow([':exit'], explicit_model='GPT-6 Sol', resume=True,
                                     resume_unsent=True)

        self.assertIn('browser:read-draft:reconciled-draft', events)
        self.assertIn('browser:exchange:reconciled-draft', events)
        self.assertIn('orchestrator:resume-draft', events)
        self.assertLess(events.index('browser:read-draft:reconciled-draft'),
                        events.index('browser:exchange:reconciled-draft'))
        self.assertLess(events.index('browser:exchange:reconciled-draft'),
                        events.index('orchestrator:resume-draft'))
        self.assertLess(events.index('orchestrator:resume-draft'), events.index('browser:ready:GPT-6 Sol'))


if __name__ == '__main__':
    unittest.main()
