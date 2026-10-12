"""Synthetic terminal input routing tests; never access a real terminal."""
import asyncio
import queue
import threading
import time
import unittest

from copilot_agent.terminal_input import TerminalInputBroker


class TerminalInputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lines = queue.Queue()
        self.output = []

        def read(_prompt=''):
            return self.lines.get()

        self.broker = TerminalInputBroker(input_fn=read,
                                          output=lambda *args, **kwargs: self.output.append(' '.join(map(str, args))))
        self.addCleanup(self.broker.close)

    async def test_active_plain_input_and_explicit_steering_are_queued_in_order(self):
        self.broker.set_active('run-1', threading.Event())
        self.lines.put('First steering message')
        self.lines.put('/steer Please prioritize the correction')
        items = await asyncio.to_thread(self._wait_for_items, 2)
        self.assertEqual(['First steering message', 'Please prioritize the correction'],
                         [item['text'] for item in items])
        self.assertEqual([1, 2], [item['sequence'] for item in items])
        self.assertTrue(all(item['parent_run_id'] == 'run-1' for item in items))

    async def test_active_attachment_command_preserves_windows_paths_with_spaces(self):
        self.broker.set_active('run-2', threading.Event())
        self.lines.put('/attach "C:\\Users\\Jorge Vales\\S Drive\\mañana.py" "S:\\Folder Name\\evidence.txt"')
        items = await asyncio.to_thread(self._wait_for_items, 1)
        self.assertEqual(['C:\\Users\\Jorge Vales\\S Drive\\mañana.py',
                          'S:\\Folder Name\\evidence.txt'], items[0]['attachments'])
        self.assertIn('Do not execute', items[0]['text'])

    async def test_colon_commands_match_idle_terminal_conventions(self):
        self.broker.set_active('run-2b', threading.Event())
        self.lines.put(':steer Preserve the current objective')
        self.lines.put(':attach "S:\\Reviewed documents\\proof.py"')
        items = await asyncio.to_thread(self._wait_for_items, 2)
        self.assertEqual('Preserve the current objective', items[0]['text'])
        self.assertEqual(['S:\\Reviewed documents\\proof.py'], items[1]['attachments'])

    async def test_attach_without_paths_opens_multi_file_picker_for_active_run(self):
        self.broker.attach_picker = lambda: [r'C:\Selected files\proof.py', r'S:\Evidence\report.txt']
        self.broker.set_active('run-picker', threading.Event())
        self.lines.put('/attach')
        items = await asyncio.to_thread(self._wait_for_items, 1)
        self.assertEqual([r'C:\Selected files\proof.py', r'S:\Evidence\report.txt'],
                         items[0]['attachments'])

    async def test_twenty_one_attachments_are_rejected_without_queueing(self):
        self.broker.set_active('run-3', threading.Event())
        self.lines.put('/attach ' + ' '.join(f'"C:\\folder\\file {n}.txt"' for n in range(21)))
        await asyncio.sleep(.1)
        self.assertEqual([], self.broker.poll_steering())
        self.assertTrue(any('Selected 21 files' in line and 'Remove 1' in line for line in self.output))

    async def test_input_arriving_after_active_run_finishes_becomes_normal_answer(self):
        self.broker.set_active('run-4', threading.Event())
        self.broker.set_active()
        self.lines.put('Next ordinary request')
        answer = await asyncio.wait_for(self.broker.ask('[User] You:'), timeout=2)
        self.assertEqual('Next ordinary request', answer)
        self.assertEqual([], self.broker.poll_steering())

    def _wait_for_items(self, count):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            items = self.broker.poll_steering()
            if len(items) >= count:
                return items
            if items:
                # Preserve the items while the second line is consumed.
                with self.broker._lock:
                    self.broker._steering.extendleft(reversed(items))
            time.sleep(.01)
        raise AssertionError('Timed out waiting for terminal input routing')
