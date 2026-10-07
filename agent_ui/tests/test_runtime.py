import threading
import time
import unittest

from agent_ui.runtime import PromptBroker


class PromptBrokerTests(unittest.TestCase):
    def test_submission_is_delivered_only_at_prompt_and_completes_at_next_prompt(self):
        events=[]
        broker=PromptBroker(lambda kind,payload:events.append((kind,payload)))
        answers=[]
        agent=threading.Thread(target=lambda: answers.append(broker.ask('Choose startup option')))
        agent.start()
        submitted=[]
        user=threading.Thread(target=lambda: (broker.submit('1'), submitted.append(True)))
        user.start()
        deadline=time.monotonic()+2
        while not any(item[0]=='status' for item in events) and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertFalse(submitted)  # The UI submission stays busy until the agent reaches its next prompt.
        agent.join(2)
        self.assertEqual(['1'],answers)
        next_prompt=threading.Thread(target=lambda: broker.ask('Next request'))
        next_prompt.start();user.join(2)
        self.assertEqual([True],submitted)
        broker.close();next_prompt.join(2)

    def test_shutdown_releases_waiting_prompt(self):
        broker=PromptBroker(lambda *_:None)
        answers=[]
        agent=threading.Thread(target=lambda: answers.append(broker.ask('Waiting')))
        agent.start()
        deadline=time.monotonic()+2
        while not broker.active_reply and time.monotonic()<deadline: time.sleep(.01)
        broker.close();agent.join(2)
        self.assertEqual([':exit'],answers)


if __name__=='__main__': unittest.main()
