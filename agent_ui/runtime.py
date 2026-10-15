"""Thread-safe bridge from the local workspace to the existing agent runtime."""
from __future__ import annotations

import asyncio
from queue import Empty, Queue
import re
import threading
import time
import uuid
from collections import deque
from types import SimpleNamespace


class PromptBroker:
    """Deliver UI input only when the existing agent is explicitly waiting."""

    def __init__(self, emit):
        self.emit = emit
        self.prompts = Queue()
        self.lock = threading.RLock()
        self.active_reply = None
        self.active_prompt = None
        self.previous_completion = None
        self._interrupted_replies = set()
        self.generation = 0
        self.closed = False

    def ask(self, prompt):
        with self.lock:
            if self.previous_completion is not None:
                self.previous_completion.set()
                self.previous_completion = None
            if self.closed:
                return ':exit'
            reply = Queue(maxsize=1)
            self.active_reply = reply
            self.active_prompt = str(prompt)
            self.emit('status', {'state': 'awaiting_input', 'summary': prompt})
            self.prompts.put(reply)
        text, completed = reply.get()
        with self.lock:
            if self.active_reply is reply:
                self.active_reply = None
                self.active_prompt = None
            if reply in self._interrupted_replies:
                self._interrupted_replies.discard(reply)
                completed.set()
            else:
                self.previous_completion = completed
        return text

    def submit(self, text, *, generation=None):
        generation = self.generation if generation is None else generation
        completed = threading.Event()
        while not self.closed:
            if generation != self.generation:
                return
            try:
                reply = self.prompts.get(timeout=0.2)
                break
            except Empty:
                continue
        else:
            raise RuntimeError('The agent session has ended; restart the UI launcher.')
        if reply is None:
            raise RuntimeError('The agent session has ended; restart the UI launcher.')
        with self.lock:
            if generation != self.generation:
                # A fresh prompt belongs to the new session, never this stale action.
                if self.active_reply is reply:
                    self.prompts.put(reply)
                return
            reply.put((text, completed))
        while not completed.wait(.05):
            if generation != self.generation or self.closed:
                return

    def submit_if_waiting(self, text, before_reply=None):
        """Answer the currently displayed prompt, without waiting for a future one."""
        with self.lock:
            reply = self.active_reply
            if reply is None or reply.full():
                return False
            if before_reply is not None:
                before_reply(self.active_prompt)
            completed = threading.Event()
            reply.put((text, completed))
        completed.wait()
        return True

    def close(self):
        with self.lock:
            self.closed = True
            if self.active_reply is not None:
                try:
                    self.active_reply.put_nowait((':exit', threading.Event()))
                except Exception:
                    pass
            if self.previous_completion is not None:
                self.previous_completion.set()
                self.previous_completion = None
            self.prompts.put(None)

    def interrupt(self):
        """Release an abandoned prompt without delivering a command to approval UI."""
        with self.lock:
            self.generation += 1
            if self.active_reply is not None:
                self._interrupted_replies.add(self.active_reply)
            if self.active_reply is not None and not self.active_reply.full():
                self.active_reply.put_nowait((':exit', threading.Event()))
            if self.previous_completion is not None:
                self.previous_completion.set()
                self.previous_completion = None
            while True:
                try:
                    self.prompts.get_nowait()
                except Empty:
                    break


class AgentRuntime:
    def __init__(self, emit, request_approval):
        self.emit = emit
        self.action_busy = threading.Event()
        self.broker = PromptBroker(self._emit)
        self.request_approval = request_approval
        self.thread = None
        self.closed = False
        self.cancel_event = threading.Event()
        self.action_lock = threading.Lock()
        self.action_queue = Queue()
        self._steering_lock = threading.RLock()
        self._steering_queue = deque()
        self._steering_attachment_ids = {}
        self._steering_sequence = 0
        self._run_state_lock = threading.RLock()
        self._active_user_turn = False
        self._user_turn_generation = 0
        self._active_user_turn_generation = 0
        self._active_run_id = None
        self._submitted_attachments_lock = threading.Lock()
        self._submitted_attachments = deque()
        self.action_thread = threading.Thread(target=self._dispatch_actions, daemon=True)
        self.action_thread.start()
        self.capabilities = {'stop': True, 'new_session': True, 'attach': True,
                             'set_model': False, 'resume': False}
        self._start_agent()

    def _start_agent(self):
        self.thread = threading.Thread(target=self._run_agent, name='copilot-agent-runtime', daemon=False)
        self.thread.start()

    def _run_agent(self):
        from copilot_agent import app
        from copilot_agent.feedback import Feedback

        old_terminal, old_ask = app._TERMINAL, app._UI_ASK
        old_approval, old_events = app._UI_APPROVAL_DECIDER, app._UI_EVENT_SINK
        old_cancel = app._UI_CANCEL_EVENT
        old_steering_poll = getattr(app, '_UI_STEERING_POLL', None)
        old_take_attachments = getattr(app, '_UI_TAKE_ATTACHMENTS', None)
        old_steering_complete = getattr(app, '_UI_STEERING_COMPLETE', None)
        old_active_run_id = getattr(app, '_UI_ACTIVE_RUN_ID', None)
        old_upload_root = getattr(app, '_UI_UPLOAD_ROOT', None)

        def terminal_sink(message):
            text = str(message)
            match = re.search(r'\]\s+\[([^]]+)\]\s*', text)
            actor = match.group(1) if match else 'System'
            if actor in {'Copilot','Action'} or actor.startswith('Tool/'):
                return  # Structured, validated UI events are emitted by the orchestrator.
            if actor == 'Orchestrator' and 'MESSAGE TO COPILOT /' in text:
                return  # The complete delivered exchange has its own labelled event.
            kind = {'Copilot': 'copilot', 'User': 'user', 'Error': 'error',
                    'Warning': 'warning', 'Tool': 'tool', 'Approval': 'status'}.get(actor, 'system')
            self.emit(kind, {'text': text})

        async def ask(prompt):
            return await asyncio.to_thread(self.broker.ask, prompt)

        async def approve(preview):
            return await asyncio.to_thread(self.request_approval, preview)

        app._TERMINAL = Feedback(sink=terminal_sink, color=False)
        app._UI_ASK = ask
        app._UI_APPROVAL_DECIDER = approve
        app._UI_EVENT_SINK = self.emit
        app._UI_CANCEL_EVENT = self.cancel_event
        app._UI_STEERING_POLL = self.poll_steering
        app._UI_TAKE_ATTACHMENTS = self.take_submitted_attachments
        app._UI_STEERING_COMPLETE = self.complete_steering
        app._UI_ACTIVE_RUN_ID = self.active_run_id
        workspace = getattr(self.emit, '__self__', None)
        upload_store = getattr(workspace, 'uploads', None)
        app._UI_UPLOAD_ROOT = getattr(upload_store, 'storage_root', None)
        args = SimpleNamespace(config=None, resume=None, attach_existing=False, port=None,
                               profile=None, model=None, yes_setup=False, setup_only=False)
        try:
            asyncio.run(app.run(args))
        except Exception:
            self.emit('error', {'summary': 'Agent startup or session stopped.',
                                'details': 'Review the retained local diagnostic report. No automatic replay was attempted.'})
        finally:
            self.broker.close()
            app._TERMINAL, app._UI_ASK = old_terminal, old_ask
            app._UI_APPROVAL_DECIDER, app._UI_EVENT_SINK = old_approval, old_events
            app._UI_CANCEL_EVENT = old_cancel
            app._UI_STEERING_POLL = old_steering_poll
            app._UI_TAKE_ATTACHMENTS = old_take_attachments
            app._UI_STEERING_COMPLETE = old_steering_complete
            app._UI_ACTIVE_RUN_ID = old_active_run_id
            app._UI_UPLOAD_ROOT = old_upload_root
            self.emit('connection', {'state': 'disconnected', 'summary': 'Agent session ended.'})

    def submit(self, text, attachments=()):
        """Answer a live prompt, or queue the text as steering for the active turn."""
        attachments = tuple(attachments or ())
        submitted_generation = []

        def attach_to_prompt(prompt):
            is_user_prompt = isinstance(prompt, str) and re.search(r'\]\s*You:\s*$', prompt)
            if attachments and not is_user_prompt:
                raise ValueError('Attachments can only be submitted with a new user request.')
            with self._submitted_attachments_lock:
                self._submitted_attachments.append(attachments)
            with self._run_state_lock:
                self._active_user_turn = bool(is_user_prompt)
                if is_user_prompt:
                    self._user_turn_generation += 1
                    self._active_user_turn_generation = self._user_turn_generation
                    self._active_run_id = uuid.uuid4().hex
                    submitted_generation.append(self._user_turn_generation)

        if self.broker.submit_if_waiting(text, attach_to_prompt):
            with self._run_state_lock:
                if (submitted_generation and self._active_user_turn_generation == submitted_generation[0]):
                    self._active_user_turn = False
                    self._active_run_id = None
            return {'status': 'submitted'}
        return self.steer(text, attachments)

    def take_submitted_attachments(self):
        """Return file paths delivered with the current normal user prompt, once."""
        with self._submitted_attachments_lock:
            return list(self._submitted_attachments.popleft()) if self._submitted_attachments else []

    def active_run_id(self):
        with self._run_state_lock:
            return self._active_run_id

    def steer(self, text, attachments=(), *, attachment_ids=()):
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise ValueError('Enter a request of at most 100,000 characters')
        if not isinstance(attachments, (list, tuple)) or len(attachments) > 20:
            raise ValueError('A steering message can contain at most 20 uploaded files')
        if not isinstance(attachment_ids, (list, tuple)) or len(attachment_ids) > 20:
            raise ValueError('Invalid steering attachment references')
        if self.closed:
            raise RuntimeError('The agent session has ended; restart the UI launcher.')
        if self.cancel_event.is_set():
            raise RuntimeError('The active run is cancelling; this message was not queued.')
        with self._run_state_lock:
            if not self._active_user_turn:
                raise RuntimeError('There is no active user request to steer.')
            active_run_id = self._active_run_id
        with self._steering_lock:
            if self.closed or self.cancel_event.is_set():
                raise RuntimeError('The active run is ending; this message was not queued.')
            with self._run_state_lock:
                if not self._active_user_turn or self._active_run_id != active_run_id:
                    raise RuntimeError('The active user request has finished; this message was not queued.')
            self._steering_sequence += 1
            item = {
                'message_id': uuid.uuid4().hex,
                'text': text,
                'attachments': tuple(attachments or ()),
                'attachment_ids': tuple(attachment_ids or ()),
                'submitted_at': time.time(),
                'sequence': self._steering_sequence,
                'active_run_id': active_run_id,
            }
            # Publish the accepted receipt before making the item visible to a
            # polling checkpoint. If event persistence fails, no work is queued.
            self.emit('steering', {'message_id': item['message_id'],
                                   'sequence': item['sequence'],
                                   'active_run_id': active_run_id,
                                   'status': 'queued'})
            self._steering_queue.append(item)
            self._steering_attachment_ids[item['message_id']] = item['attachment_ids']
        return {'status': 'queued', 'message_id': item['message_id'],
                'sequence': item['sequence'], 'active_run_id': active_run_id}

    def complete_steering(self, message_ids):
        """Release staged files when orchestration reaches a terminal item state."""
        if isinstance(message_ids, str):
            message_ids = [message_ids]
        if not isinstance(message_ids, (list, tuple)):
            return
        attachment_ids = []
        with self._steering_lock:
            for message_id in message_ids:
                attachment_ids.extend(self._steering_attachment_ids.pop(message_id, ()))
        workspace = getattr(self.emit, '__self__', None)
        upload_store = getattr(workspace, 'uploads', None)
        if upload_store is not None and attachment_ids:
            upload_store.discard(attachment_ids)

    def poll_steering(self):
        """Atomically consume queued steering in submission order at a safe point."""
        with self._steering_lock:
            if self.cancel_event.is_set():
                self._cancel_pending_steering_locked('Run cancelled before incorporation')
                return []
            items = list(self._steering_queue)
            self._steering_queue.clear()
        return items

    def _cancel_pending_steering_locked(self, reason):
        while self._steering_queue:
            item = self._steering_queue.popleft()
            attachment_ids = self._steering_attachment_ids.pop(item['message_id'], ())
            workspace = getattr(self.emit, '__self__', None)
            upload_store = getattr(workspace, 'uploads', None)
            if upload_store is not None and attachment_ids:
                upload_store.discard(attachment_ids)
            self.emit('steering', {'message_id': item['message_id'],
                                   'sequence': item['sequence'],
                                   'active_run_id': item['active_run_id'],
                                   'status': 'cancelled', 'summary': reason})

    def _cancel_pending_steering(self, reason):
        with self._steering_lock:
            self._cancel_pending_steering_locked(reason)

    def permission_context(self):
        from copilot_agent import app
        context=app._UI_PERMISSION_CONTEXT
        if context is None: raise ValueError('Wait for the agent session to initialise')
        return context

    def permission_snapshot(self):
        from copilot_agent.research_permissions import list_grants, CAPABILITIES
        return {'grants':list_grants(self.permission_context()),'capabilities':list(CAPABILITIES)}

    def manage_permission(self, action, grant_id, changes=None):
        from copilot_agent.research_permissions import manage, prepare_permissions, execute_permissions
        from copilot_agent.state import canonical_hash
        context=dict(self.permission_context())
        if action in {'pause','revoke'}: return manage(context,grant_id,action)
        if action not in {'edit','renew'}: raise ValueError('Unsupported grant operation')
        name='permissions.'+action
        args=dict(changes or {},grant_id=grant_id)
        prepared=prepare_permissions(name,args,context)
        call={'name':name,'version':'1.0','call_id':'manage-'+grant_id,'arguments':args}
        plan={'tool_requests':[call],'risk_summary':'Review the changed durable read grant; no write/download permission.'}
        plan_hash=canonical_hash({'plan':plan,'prepared':prepared})
        decision=self.request_approval({'plan_hash':plan_hash,'call_hash':canonical_hash(call),
            'current_call_id':call['call_id'],'complete_pending_plan':plan,'prepared_code':prepared,
            'approval_scope':'This exact revised durable research grant','choices':['deny','once','plan']})
        if decision not in {'once','plan'}: return {'status':'denied'}
        context.update(approved=True,approval_hash=plan_hash,permission_reviewed=prepared)
        return asyncio.run(execute_permissions(name,args,context))

    def action(self, name, value=None):
        if name == 'new_session':
            from copilot_agent import app
            self.cancel_event.set()
            self._cancel_pending_steering('New session requested before incorporation')
            with self._submitted_attachments_lock:
                self._submitted_attachments.clear()
            app._NEW_SESSION_REQUESTED.set()
            self.broker.interrupt()
            shutdown = False
            while True:
                try:
                    shutdown = self.action_queue.get_nowait() is None or shutdown
                except Empty:
                    break
            if shutdown:
                self.action_queue.put(None)
            self.action_busy.clear()
            workspace = getattr(self.request_approval, '__self__', None)
            if workspace is not None and hasattr(workspace, 'pending'):
                with workspace.lock:
                    for item in workspace.pending.values():
                        if item['decision'] is None:
                            item['decision'] = 'deny'
                            item['gate'].set()
            self.emit('status', {'state': 'action_active', 'summary': 'Cancelling the previous run and opening a fresh session.'})
            return
        if name == 'stop':
            self.cancel_event.set()
            self._cancel_pending_steering('Run cancelled before incorporation')
            self.emit('status', {'state': 'cancelling', 'summary': 'Cancellation requested; already submitted effects are preserved.'})
            return
        if name not in {'new_session', 'attach'}:
            raise ValueError('This action is not supported by the connected runtime')
        command = ':new' if name == 'new_session' else ':attach'
        if value:
            command += ' ' + str(value)
        self.action_busy.set()
        self.action_queue.put((self.broker.generation, command))
        self.emit('status', {'state': 'action_active', 'summary': 'Waiting for the agent to finish the requested action.'})

    def _dispatch_actions(self):
        while True:
            command = self.action_queue.get()
            if command is None:
                return
            try:
                generation, command = command
                self.broker.submit(command, generation=generation)
            except Exception:
                self.emit('error', {'summary': 'The requested UI action could not be completed.'})
            finally:
                self.action_busy.clear()
                self.emit('status', {'state': 'awaiting_input', 'summary': 'Ready for the next request.'})

    def _emit(self, kind, payload):
        if kind == 'status' and payload.get('state') == 'awaiting_input' and self.action_busy.is_set():
            payload = dict(payload, state='action_active', summary='Completing the requested agent action.')
        self.emit(kind, payload)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_event.set()
        self._cancel_pending_steering('Agent session closed before incorporation')
        self.action_queue.put(None)
        self.broker.close()
        if self.thread is not None:
            self.thread.join(timeout=8)
        self.complete_steering(list(self._steering_attachment_ids))


def create_runtime(emit, request_approval):
    return AgentRuntime(emit, request_approval)


def main():
    from agent_ui.workspace import main as workspace_main
    import sys
    sys.argv = [sys.argv[0], '--runtime', 'agent_ui.runtime']
    workspace_main()


if __name__ == '__main__':
    main()
