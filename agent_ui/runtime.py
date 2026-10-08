"""Thread-safe bridge from the local workspace to the existing agent runtime."""
from __future__ import annotations

import asyncio
from queue import Empty, Queue
import re
import threading
from types import SimpleNamespace


class PromptBroker:
    """Deliver UI input only when the existing agent is explicitly waiting."""

    def __init__(self, emit):
        self.emit = emit
        self.prompts = Queue()
        self.lock = threading.RLock()
        self.active_reply = None
        self.previous_completion = None
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
            self.emit('status', {'state': 'awaiting_input', 'summary': prompt})
            self.prompts.put(reply)
        text, completed = reply.get()
        with self.lock:
            self.active_reply = None
            self.previous_completion = completed
        return text

    def submit(self, text):
        completed = threading.Event()
        while not self.closed:
            try:
                reply = self.prompts.get(timeout=0.2)
                break
            except Empty:
                continue
        else:
            raise RuntimeError('The agent session has ended; restart the UI launcher.')
        if reply is None:
            raise RuntimeError('The agent session has ended; restart the UI launcher.')
        reply.put((text, completed))
        completed.wait()

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

        def terminal_sink(message):
            text = str(message)
            match = re.search(r'\]\s+\[([^]]+)\]\s*', text)
            actor = match.group(1) if match else 'System'
            if actor == 'Copilot' or actor.startswith('Tool/'):
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
            self.emit('connection', {'state': 'disconnected', 'summary': 'Agent session ended.'})

    def submit(self, text):
        self.broker.submit(text)

    def action(self, name, value=None):
        if name == 'stop':
            self.cancel_event.set()
            self.emit('status', {'state': 'cancelling', 'summary': 'Cancellation requested; already submitted effects are preserved.'})
            return
        if name not in {'new_session', 'attach'}:
            raise ValueError('This action is not supported by the connected runtime')
        command = ':new' if name == 'new_session' else ':attach'
        if value:
            command += ' ' + str(value)
        self.action_busy.set()
        self.action_queue.put(command)
        self.emit('status', {'state': 'action_active', 'summary': 'Waiting for the agent to finish the requested action.'})

    def _dispatch_actions(self):
        while True:
            command = self.action_queue.get()
            if command is None:
                return
            try:
                self.broker.submit(command)
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
        self.action_queue.put(None)
        self.broker.close()
        if self.thread is not None:
            self.thread.join(timeout=8)


def create_runtime(emit, request_approval):
    return AgentRuntime(emit, request_approval)


def main():
    from agent_ui.workspace import main as workspace_main
    import sys
    sys.argv = [sys.argv[0], '--runtime', 'agent_ui.runtime']
    workspace_main()


if __name__ == '__main__':
    main()
