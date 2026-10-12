import threading
import time
import unittest
from collections import deque
from unittest.mock import Mock

from agent_ui.runtime import AgentRuntime, PromptBroker
from agent_ui.workspace import Workspace


class PromptBrokerTests(unittest.TestCase):
    def test_submission_only_targets_an_already_waiting_prompt(self):
        broker = PromptBroker(Mock())
        self.assertFalse(broker.submit_if_waiting('too early'))

        answer = {}
        first = threading.Thread(target=lambda: answer.setdefault('first', broker.ask('[User] You:')))
        first.start()
        deadline = time.monotonic() + 2
        while broker.active_reply is None and time.monotonic() < deadline:
            time.sleep(.005)
        submitted = {}
        sender = threading.Thread(target=lambda: submitted.setdefault(
            'result', broker.submit_if_waiting('normal request')))
        sender.start()
        deadline = time.monotonic() + 2
        while broker.active_reply is not None and not broker.active_reply.empty() and time.monotonic() < deadline:
            time.sleep(.005)
        second = threading.Thread(target=lambda: answer.setdefault('second', broker.ask('[User] You:')))
        second.start()
        sender.join(2)
        broker.close()
        first.join(2)
        second.join(2)
        self.assertEqual(answer.get('first'), 'normal request')
        self.assertFalse(first.is_alive())
        self.assertFalse(sender.is_alive())
        self.assertTrue(submitted.get('result'))


class SteeringQueueTests(unittest.TestCase):
    def runtime(self):
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.emit = Mock()
        runtime.closed = False
        runtime.cancel_event = threading.Event()
        runtime._steering_lock = threading.RLock()
        runtime._steering_queue = deque()
        runtime._steering_attachment_ids = {}
        runtime._steering_sequence = 0
        runtime._run_state_lock = threading.RLock()
        runtime._active_user_turn = True
        runtime._active_run_id = 'run-1'
        return runtime

    def test_steering_is_acknowledged_queued_and_consumed_once_in_order(self):
        runtime = self.runtime()
        first = runtime.steer('Add the missing result column')
        second = runtime.steer('Keep the current task and finish its validation')
        queued = runtime.poll_steering()
        self.assertEqual([item['sequence'] for item in queued], [1, 2])
        self.assertEqual([item['message_id'] for item in queued],
                         [first['message_id'], second['message_id']])
        self.assertEqual([item['text'] for item in queued],
                         ['Add the missing result column', 'Keep the current task and finish its validation'])
        self.assertEqual(runtime.poll_steering(), [])

    def test_finished_or_cancelled_turn_rejects_new_steering(self):
        runtime = self.runtime()
        runtime._active_user_turn = False
        with self.assertRaisesRegex(RuntimeError, 'no active user request'):
            runtime.steer('Start a different task')
        runtime._active_user_turn = True
        runtime.cancel_event.set()
        with self.assertRaisesRegex(RuntimeError, 'cancelling'):
            runtime.steer('Continue despite cancellation')

    def test_cancelled_queue_is_not_returned_as_steering(self):
        runtime = self.runtime()
        runtime.steer('Do not lose this silently')
        runtime.cancel_event.set()
        self.assertEqual(runtime.poll_steering(), [])
        runtime.emit.assert_any_call('steering', unittest.mock.ANY)


class WorkspaceSteeringTests(unittest.TestCase):
    def test_busy_submit_routes_to_steering_without_starting_another_run(self):
        runtime = Mock()
        runtime.steer.return_value = {'status': 'queued', 'sequence': 1, 'message_id': 'm1'}
        workspace = Workspace()
        workspace.runtime = runtime
        workspace.busy = True

        result = workspace.submit('Keep working on the existing request')

        self.assertEqual(result, {'status': 'queued', 'sequence': 1, 'message_id': 'm1'})
        runtime.steer.assert_called_once_with('Keep working on the existing request', [], attachment_ids=[])
        runtime.submit.assert_not_called()

    def test_idle_submit_remains_a_normal_prompt(self):
        done = threading.Event()

        class FakeRuntime:
            def submit(self, text, attachments=()):
                self.received = (text, attachments)
                done.set()

        runtime = FakeRuntime()
        workspace = Workspace()
        workspace.runtime = runtime
        workspace.submit('Start the requested task')
        self.assertTrue(done.wait(2))
        self.assertEqual(runtime.received, ('Start the requested task', []))

    def test_steering_retry_is_idempotent_and_conflicting_reuse_is_rejected(self):
        runtime = Mock()
        runtime.steer.return_value = {'status':'queued', 'message_id':'steer-1'}
        workspace = Workspace()
        workspace.runtime = runtime
        workspace.busy = True
        first = workspace.submit('Continue the current goal', client_message_id='stable-1')
        retry = workspace.submit('Continue the current goal', client_message_id='stable-1')
        self.assertEqual(first, retry)
        runtime.steer.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'reused for different'):
            workspace.submit('Start an unrelated goal', client_message_id='stable-1')
        workspace.close()

    def test_normal_submit_releases_staged_uploads_after_runtime_returns(self):
        import base64
        done = threading.Event()
        finish = threading.Event()

        class FakeRuntime:
            def submit(self, text, attachments=()):
                self.paths = attachments
                done.set()
                finish.wait(2)

        runtime = FakeRuntime()
        workspace = Workspace()
        workspace.runtime = runtime
        content = b'upload fixture'
        uploaded = workspace.upload({
            'name':'fixture.txt', 'type':'text/plain', 'size':len(content),
            'content_base64':base64.b64encode(content).decode(),
            'client_message_id':'upload-message:0'})
        workspace.submit('Read the attached fixture', [uploaded['attachment_id']], 'turn-1')
        self.assertTrue(done.wait(2))
        self.assertEqual(runtime.paths[0].read_bytes(), content)
        finish.set()
        deadline = time.monotonic() + 2
        while workspace.busy and time.monotonic() < deadline:
            time.sleep(.005)
        with self.assertRaises(Exception):
            workspace.uploads.resolve_paths([uploaded['attachment_id']])
        workspace.close()

    def test_local_attachment_paths_are_private_in_user_events_and_approval_snapshot(self):
        workspace = Workspace()
        workspace.emit('user', {'text':'Review these files', 'attachments':[
            {'path':r'C:\private\secret.txt', 'name':'secret.txt', 'size':12,
             'sha256':'a' * 64}]})
        self.assertNotIn('path', workspace.snapshot()['events'][0]['payload']['attachments'][0])

        preview = {'plan_hash':'plan', 'call_hash':'call', 'files':[
            {'path':r'C:\private\secret.txt', 'name':'secret.txt', 'size':12,
             'sha256':'a' * 64}]}
        decision = []
        worker = threading.Thread(target=lambda: decision.append(workspace.request_approval(preview)))
        worker.start()
        deadline = time.monotonic() + 2
        while not workspace.snapshot()['approvals'] and time.monotonic() < deadline:
            time.sleep(.005)
        approval = workspace.snapshot()['approvals'][0]
        file_record = approval['preview']['files'][0]
        self.assertNotIn('path', file_record)
        self.assertEqual((file_record['name'], file_record['size'], file_record['sha256']),
                         ('secret.txt', 12, 'a' * 64))
        workspace.decide(approval['ticket'], 'once', 'plan', 'call')
        worker.join(2)
        self.assertEqual(decision, ['once'])
        workspace.close()


if __name__ == '__main__':
    unittest.main()
