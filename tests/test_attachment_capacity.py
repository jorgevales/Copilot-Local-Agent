"""Offline assembled attachment boundary, using actual prompt and send logic.

Mock transport verifies ordering/commit accounting; this is not a live UI upload
test. Synthetic source and staged files are retained under COPILOT_TEST_ROOT.
"""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from copilot_agent.orchestrator import Orchestrator
from copilot_agent.policy import PolicyError
from tests.test_orchestrator import MockBrowser, final_response
from tests.test_protocol_state import make_fixture


class AssembledCapacityTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, extra_count):
        root, config, state, registry = make_fixture('attachment-capacity-')
        config.max_context_chars = 300
        browser = MockBrowser([final_response])
        engine = Orchestrator(config,browser,registry,state,display=lambda message:None)
        # Force due findings plus private context overflow alongside all eight
        # startup references. Private context stays inline, adding no file.
        state.data['message_count'] = 9
        state.data['requirements'] = ['Synthetic durable capacity context. ' * 40]
        state.save()
        engine.findings.accept([{'key':'capacity-context','content':'Retained synthetic capacity fixture.',
                                 'provenance':'Offline controlled test.'}],'prior-synthetic-request')
        extras = []
        for ordinal in range(extra_count):
            path = root / 'workspace' / ('extra-'+str(ordinal).zfill(2)+'.txt')
            path.write_text('Approved synthetic user context '+str(ordinal),encoding='utf-8')
            extras.append(path)
            engine.approved_attachment_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return root,state,browser,engine,extras

    async def test_twenty_includes_eight_guidance_eleven_reviewed_files_and_findings(self):
        root,state,browser,engine,extras = self.fixture(11)
        with patch('builtins.print'):
            response = await engine._validated_exchange('initialize','Synthetic assembled capacity boundary.',extras)
        self.assertEqual(response['completion_status'],'complete')
        self.assertEqual(len(browser.sent),1)
        sent = browser.sent[0]
        attachments = sent['attachments']
        self.assertEqual(len(attachments),20)
        expected_guidance = {path.name for path in engine.prompts.initial_attachments()}
        self.assertEqual(len(expected_guidance),8)
        self.assertTrue(expected_guidance.issubset({path.name for path in attachments}))
        self.assertIn(engine.findings.attachment,attachments)
        self.assertNotIn(engine.prompts.context_file,attachments)
        self.assertFalse(engine.prompts.context_file.exists())
        self.assertEqual(sent['message']['copilot_message_number'],10)
        self.assertTrue(sent['message']['useful_findings_file_attached'])
        self.assertEqual(len(sent['message']['user_attachment_manifest']),11)
        self.assertTrue(sent['message']['context']['private_context_omitted'])
        self.assertNotIn('reference_attachment',sent['message']['context'])
        # Actual send staging preserves exactly all reviewed input files.
        for source in extras:
            uploaded = next(path for path in attachments if path.name==source.name)
            self.assertNotEqual(uploaded,source)
            self.assertEqual(uploaded.read_bytes(),source.read_bytes())
        self.assertEqual(state.message_count,10)
        self.assertIsNone(state.data['pending_submission'])
        self.assertEqual(len(state.data['attachments']),20)
        self.assertEqual([entry['ordinal'] for entry in state.data['findings_sync']],[10])
        self.assertEqual(len({path.name.casefold() for path in attachments}),20)
        self.assertTrue(all(path.is_file() for path in attachments))
        saved = json.loads(state.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['message_count'],10)

    async def test_twenty_first_file_blocks_before_transport_intent_or_count(self):
        root,state,browser,engine,extras = self.fixture(12)
        with patch('builtins.print'),self.assertRaisesRegex(PolicyError,'20-attachment limit'):
            await engine._send('initialize','Synthetic oversized assembled boundary.',extras)
        self.assertEqual(browser.sent,[])
        self.assertEqual(state.message_count,9)
        self.assertIsNone(state.data['pending_submission'])
        self.assertEqual(state.data['attachments'],[])
        self.assertEqual(state.data['findings_sync'],[])
        self.assertFalse((state.directory / 'approved_uploads').exists())
        self.assertTrue(all(path.is_file() for path in extras))


if __name__=='__main__':
    unittest.main()
