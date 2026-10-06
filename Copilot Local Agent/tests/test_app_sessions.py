"""Independent session lifecycle, without real UI messages or deletion."""
import json
import unittest
from unittest.mock import patch

from copilot_agent.app import start_new_session
from copilot_agent.orchestrator import Orchestrator
from tests.test_orchestrator import MockBrowser, final_response
from tests.test_protocol_state import make_fixture


class SessionBrowser(MockBrowser):
    async def start(self):
        return self

    async def discover_models(self):
        return [{'label': 'Synthetic model', 'enabled': True}]

    async def select_model(self, label):
        self.model_label = label
        return {'label': label, 'checked': True}


class NewSessionTests(unittest.IsolatedAsyncioTestCase):
    def previous(self):
        root, config, state, registry = make_fixture('independent-session-')
        old_browser = SessionBrowser([final_response])
        old = Orchestrator(config, old_browser, registry, state, display=lambda text: None)
        return root, config, state, registry, old_browser, old

    async def test_new_ui_adapter_and_state_exclude_previous_context_and_authority(self):
        root, config, state, registry, old_browser, old = self.previous()
        await old.initialize()
        state.data['requirements'].append('OLD_TOPIC_UNIQUE_DATA')
        state.data['approvals']['old-grant'] = {'decision': 'plan'}
        state.data['unresolved_questions'].append('OLD_TOPIC_UNIQUE_QUESTION')
        old.findings.accept([{'key': 'old', 'content': 'OLD_TOPIC_UNIQUE_FINDING', 'provenance': 'synthetic'}], 'old')
        state.save()
        fresh_browser = SessionBrowser([final_response])
        with patch('copilot_agent.app.BrowserAdapter', return_value=fresh_browser) as factory, patch('builtins.print'):
            new = await start_new_session(config, old, 'Synthetic model', registry)
        self.assertTrue(old_browser.closed)
        self.assertEqual('closed', state.data['status'])
        self.assertTrue(state.path.exists())
        self.assertNotEqual(state.session_id, new.state.session_id)
        self.assertIs(new.browser, fresh_browser)
        self.assertEqual('Synthetic model', fresh_browser.model_label)
        self.assertTrue(factory.call_args.args[0].attach_existing)
        self.assertEqual([], new.state.data['requirements'])
        self.assertEqual([], new.state.data['unresolved_questions'])
        self.assertEqual({}, new.state.data['approvals'])
        self.assertEqual({}, new.state.data['calls'])
        self.assertEqual([], new.findings.data['findings'])
        self.assertEqual(1, new.state.message_count)
        self.assertEqual(8, len(fresh_browser.sent[0]['attachments']))
        self.assertNotIn('OLD_TOPIC_UNIQUE', json.dumps(fresh_browser.sent[0]['message']))
        await new.close()

    async def test_uncertainty_cannot_be_erased_through_new_session(self):
        root, config, state, registry, old_browser, old = self.previous()
        state.data['calls']['uncertain'] = {'status': 'uncertain', 'state_changing': True}
        with patch('copilot_agent.app.BrowserAdapter') as factory:
            with self.assertRaisesRegex(RuntimeError, 'Reconcile'):
                await start_new_session(config, old, 'Synthetic model', registry)
            factory.assert_not_called()
        self.assertFalse(old_browser.closed)
        state.data['calls'].clear()
        state.begin_submission('uncertain-send', 'synthetic')
        with self.assertRaisesRegex(RuntimeError, 'Reconcile'):
            await start_new_session(config, old, 'Synthetic model', registry)
        self.assertFalse(old_browser.closed)

    async def test_failed_new_setup_archives_previous_and_closes_new_adapter(self):
        root, config, state, registry, old_browser, old = self.previous()
        fresh_browser = SessionBrowser([])
        async def failed_start():
            raise RuntimeError('synthetic unavailable UI')
        fresh_browser.start = failed_start
        with patch('copilot_agent.app.BrowserAdapter', return_value=fresh_browser):
            with self.assertRaisesRegex(RuntimeError, 'New session setup stopped'):
                await start_new_session(config, old, 'Synthetic model', registry)
        self.assertTrue(old_browser.closed)
        self.assertTrue(fresh_browser.closed)
        self.assertEqual('closed', state.data['status'])
        saved = list((root / 'runtime' / 'sessions').glob('*/session.json'))
        self.assertEqual(1, len(saved))
        self.assertEqual('blocked', json.loads(saved[0].read_text())['status'])
