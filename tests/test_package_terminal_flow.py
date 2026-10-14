"""Real terminal routing and ZIP execution with an offline Copilot transport."""
import asyncio
import hashlib
from pathlib import Path
import queue
import threading
import unittest
from unittest.mock import patch

from copilot_agent import app as app_module
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.terminal_input import TerminalInputBroker
from copilot_agent.tools import ToolRegistry
from tests.test_automation_packages import write_python_package
from tests.test_orchestrator import MockBrowser, final_response, tool_response
from tests.test_protocol_state import make_fixture


class PackageTerminalFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_terminal_choices_and_local_execution_before_returning_to_copilot(self):
        for choice in ('1', '2', '3', '4'):
            with self.subTest(choice=choice):
                root, config, state, _ = make_fixture('package-terminal-')
                config._automation_test_mode = True
                archive = write_python_package(root / 'workspace' / 'approved.zip',
                    "import sys\nfrom pathlib import Path\n"
                    "Path(sys.argv[-1], 'result.txt').write_text('approved package completed')\n")
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                lines = queue.Queue()
                def read(_prompt):
                    line = lines.get()
                    if line is None:
                        raise EOFError
                    return line
                broker = TerminalInputBroker(input_fn=read, output=lambda *args, **kwargs: None)
                broker.set_active('package-test', threading.Event())

                async def decide(preview):
                    pending = asyncio.create_task(app_module._terminal_approval_decider(preview))
                    for _ in range(100):
                        if broker._approval_prompt_active:
                            break
                        await asyncio.sleep(.01)
                    lines.put(choice)
                    return await asyncio.wait_for(pending, 2)

                def after_local_results(message):
                    runs = [record for record in state.data['calls'].values()
                            if record.get('request', {}).get('name') == 'automation.run']
                    self.assertEqual(1, len(runs), 'Execution must finish before the next Copilot message')
                    result = runs[0]['result']
                    if choice == '1':
                        self.assertFalse(result['ok'])
                        self.assertEqual('approval_denied', result['error']['code'])
                        self.assertEqual([], list(config.workspace_dir.glob('automation-packages/runs/*/outputs/result.txt')))
                        return final_response(message, completion_status='blocked', continuation_state='blocked',
                                              user_response='Package execution declined.')
                    self.assertTrue(result['ok'], result)
                    self.assertEqual('completed', result['result']['status'])
                    self.assertTrue(result['result']['validation']['ok'])
                    outputs = list(config.workspace_dir.glob('automation-packages/runs/*/outputs/result.txt'))
                    self.assertEqual(1, len(outputs))
                    self.assertEqual('approved package completed', outputs[0].read_text())
                    return final_response(message)

                browser = MockBrowser([final_response,
                    lambda message: tool_response(message, 'inspect-zip', 'automation.inspect',
                        {'path': str(archive), 'expected_sha256': digest}), after_local_results])
                engine = Orchestrator(config, browser, ToolRegistry(), state,
                                      approval_decider=decide, display=lambda text: None)
                try:
                    with patch.object(app_module, '_TERMINAL_INPUT', broker):
                        await engine.initialize()
                        await engine.turn('Create a workflow that takes 30 minutes with dependencies, checkpoints, retries, recovery and validation.')
                    self.assertEqual(['initialize', 'user_turn', 'tool_results'],
                                     [record['message']['kind'] for record in browser.sent])
                    self.assertEqual([], broker.poll_steering())
                finally:
                    broker.set_active()
                    broker.close()
                    lines.put(None)
