"""Fresh-chat cancellation preserves the archived operation ledger."""
import asyncio
import threading
import unittest
from unittest.mock import patch

from copilot_agent import app
from tests import test_app_sessions as fixtures
from tests.test_orchestrator import final_response


class RestartCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        app._NEW_SESSION_REQUESTED.clear()

    async def test_interrupt_cancels_and_awaits_active_work(self):
        finished = asyncio.Event()
        async def work():
            try:
                await asyncio.sleep(300)
            finally:
                finished.set()
        task = asyncio.create_task(app._interruptible_session(work()))
        await asyncio.sleep(.01)
        app._NEW_SESSION_REQUESTED.set()
        with self.assertRaises(app.SessionRestartRequested):
            await asyncio.wait_for(task, 1)
        self.assertTrue(finished.is_set())

    async def test_explicit_restart_keeps_uncertainty_only_in_old_records(self):
        fixture = fixtures.NewSessionTests()
        _, config, state, registry, _, old = fixture.previous()
        state.data['calls']['unresolved'] = {'status': 'uncertain', 'state_changing': True}
        state.data['calls']['executing'] = {'status': 'executing', 'state_changing': True}
        state.begin_submission('old-pending', 'test')
        old.cancel_event.set()
        with patch('copilot_agent.app.BrowserAdapter', return_value=fixtures.SessionBrowser([final_response])), \
                patch('copilot_agent.app.check_knowledge_health', return_value={'available': False, 'statement': 'Test disabled'}), \
                patch('copilot_agent.app.ask', unittest.mock.AsyncMock(return_value='yes')):
            fresh = await app.start_new_session(config, old, 'Synthetic model', registry,
                                                user_requested=True)
        self.assertEqual(state.data['calls']['unresolved']['status'], 'uncertain')
        self.assertEqual(state.data['calls']['executing']['status'], 'uncertain')
        self.assertIsNotNone(state.data['pending_submission'])
        self.assertEqual(fresh.state.data['calls'], {})
        self.assertIsNone(fresh.state.data['pending_submission'])
        self.assertFalse(fresh.cancel_event.is_set())
        await fresh.close()

    async def test_close_cancels_background_attachment_preparation(self):
        _, _, _, _, _, old = fixtures.NewSessionTests().previous()
        prep = asyncio.create_task(asyncio.sleep(300))
        old._next_turn_preparation = prep
        await old.close()
        self.assertTrue(prep.cancelled())
        self.assertIsNone(old._next_turn_preparation)


class PromptRestartTests(unittest.TestCase):
    def test_stale_action_waiting_for_prompt_cannot_answer_new_session_prompt(self):
        from agent_ui.runtime import PromptBroker
        broker = PromptBroker(lambda *args: None)
        stale = threading.Thread(target=lambda: broker.submit(':attach'))
        stale.start()
        threading.Event().wait(.03)
        broker.interrupt()
        result = []
        fresh = threading.Thread(target=lambda: result.append(broker.ask('Fresh access approval')))
        fresh.start()
        stale.join(1)
        self.assertFalse(stale.is_alive())
        self.assertEqual(result, [])
        self.assertIsNotNone(broker.active_reply)
        self.assertTrue(broker.active_reply.empty())
        broker.close()
        fresh.join(1)
        self.assertEqual(result, [':exit'])

    def test_interrupted_ui_prompt_releases_blocked_reader(self):
        from agent_ui.runtime import PromptBroker
        broker = PromptBroker(lambda *args: None)
        result = []
        worker = threading.Thread(target=lambda: result.append(broker.ask('Old prompt')))
        worker.start()
        for _ in range(100):
            if broker.active_reply is not None:
                break
            threading.Event().wait(.005)
        broker.interrupt()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [':exit'])
        self.assertTrue(broker.prompts.empty())
        broker.close()

    def test_terminal_new_chat_interrupts_running_work_instead_of_steering(self):
        import queue
        from copilot_agent.terminal_input import TerminalInputBroker
        lines = queue.Queue()
        broker = TerminalInputBroker(input_fn=lambda *_: lines.get(), output=lambda *args, **kw: None)
        cancelled = threading.Event()
        broker.set_active('old-run', cancelled)
        try:
            lines.put(':new')
            self.assertTrue(cancelled.wait(1))
            self.assertTrue(app._NEW_SESSION_REQUESTED.is_set())
            self.assertEqual(broker.poll_steering(), [])
        finally:
            broker.close()
            app._NEW_SESSION_REQUESTED.clear()
