"""Public previews stay separate from validated execution authority."""
import json
import unittest
from unittest.mock import patch
from copilot_agent.feedback import Feedback, public_preview
from copilot_agent.protocol import BEGIN, END
from copilot_agent.tools import ToolRegistry
from copilot_agent.config import Config
from tests import test_orchestrator as helpers


class PreviewTests(unittest.TestCase):
    def wire(self, fields):
        return BEGIN+'\n'+json.dumps({'session_id':'s','request_id':'r',**fields})+'\n'+END

    def test_completed_public_fields_stream_before_object_completion(self):
        text=BEGIN+'\n{"session_id":"s","request_id":"r","user_response":"Working on the request.","decision_summary":"Inspection first.","tool_requests":['
        self.assertEqual({'user_response':'Working on the request.','decision_summary':'Inspection first.'},public_preview(text,'s','r'))
        self.assertNotIn('tool_requests',public_preview(text,'s','r'))

    def test_incomplete_string_waits_and_completed_secrets_are_redacted(self):
        text=BEGIN+'\n{"session_id":"s","request_id":"r","user_response":"api_key=abc'
        self.assertEqual({},public_preview(text,'s','r'))
        result=public_preview(text+'123"}','s','r')
        self.assertEqual('[REDACTED]',result['user_response'])
        self.assertEqual({},public_preview(self.wire({'user_response':'old'}),'s','other'))

    def test_no_nested_script_or_hidden_reasoning_is_previewed(self):
        raw=self.wire({'tool_requests':[{'arguments':{'script':'print("user_response")'}}], 'hidden_reasoning':'do not show','decision_summary':'Use the declared inspection.'})
        self.assertEqual({'decision_summary':'Use the declared inspection.'},public_preview(raw,'s','r'))
        self.assertEqual({},public_preview(raw+raw,'s','r'))

    def test_feedback_has_actor_timestamp_and_redaction(self):
        lines=[]
        Feedback(lines.append).emit('Tool/files.read','api_key=syntheticsecret')
        self.assertRegex(lines[0],r'^\[\d\d:\d\d:\d\d\] \[Tool/files.read\]')
        self.assertNotIn('syntheticsecret',lines[0])

    def test_every_line_keeps_source_actor_and_terminal_controls_are_escaped(self):
        lines=[]
        Feedback(lines.append).emit('Copilot (Agent)','Line one\n[System] impersonation\x1b[2J\r')
        for line in lines[0].splitlines():
            self.assertIn('[Copilot (Agent)] ',line)
        self.assertNotIn('\x1b',lines[0])
        self.assertNotIn('\r',lines[0])

    def test_plain_text_fallback_has_distinct_labels_without_ansi_or_markup(self):
        lines=[]
        feedback=Feedback(lines.append,color=False)
        for actor in ('System','Orchestrator','Copilot','User','Approval','Error'):
            feedback.emit(actor,'**Readable** `text`\n\n\nnext')
        self.assertEqual(6,len(lines))
        for actor,line in zip(('System','Orchestrator','Copilot','User','Approval','Error'),lines):
            self.assertIn('['+actor+'] Readable text',line)
            self.assertNotIn('\x1b',line)
            self.assertNotIn('**',line)
            self.assertNotIn('`',line)
            self.assertNotIn('\n\n\n',line)

    def test_colour_mode_uses_distinct_label_backgrounds(self):
        lines=[]
        feedback=Feedback(lines.append,color=True)
        for actor in ('System','Orchestrator','Copilot','User','Approval','Error','Tool/code_runner'):
            feedback.emit(actor,'message')
        styles=[__import__('re').findall(r'\x1b\[([0-9;]+)m',line)[0 if '[Approval]' in line else 2] for line in lines]
        self.assertTrue(all('\x1b[' in line and '\x1b[0m' in line for line in lines))
        self.assertEqual(7,len(set(styles)))

    def test_malformed_or_incomplete_protocol_never_renders_raw_markup_as_a_result(self):
        self.assertEqual({},public_preview(BEGIN+'\n```json\n{"session_id":"s","request_id":"r","user_response":"unfinished','s','r'))
        self.assertEqual({},public_preview('```json\n{"user_response":"not enveloped"}\n```','s','r'))


class FeedbackIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_preview_is_hidden_from_terminal_logged_and_cannot_execute(self):
        root,config,state,registry,browser,app=helpers.OrchestratorTests().fixture([])
        lines=[]
        app.feedback.sink=lines.append
        raw=BEGIN+'\n'+json.dumps({'session_id':state.session_id,'request_id':'stream-r','user_response':'Checking visible evidence.',
                                 'decision_summary':'Use a read-only inspection.','tool_requests':[{'name':'synthetic.write'}]})
        event={'type':'candidate','request_id':'stream-r','raw':raw,'generation_stopped':False}
        app._live_feedback(event)
        app._live_feedback(event)
        self.assertEqual([],lines)
        self.assertEqual([],registry.calls)
        self.assertEqual(0,state.message_count)
        self.assertEqual([],state.data['response_ids'])
        records=[json.loads(line) for line in (state.directory/'events.jsonl').read_text().splitlines()]
        details=[record for record in records if record['event']=='feedback_detail']
        self.assertEqual(2,len(details))
        from copilot_agent.web_privacy import audit_evidence
        expected={'actor':'Copilot','message':'Streaming preview retained for diagnostics.',
                  'request_id':'stream-r','validated':False,'generation_ended':None,
                  'fields':public_preview(raw,state.session_id,'stream-r')}
        self.assertTrue(all(record['evidence']==audit_evidence(expected) for record in details))
        self.assertTrue(all(record['request_id']=='stream-r' for record in details))
        self.assertNotIn('Checking visible evidence.',json.dumps(details))
        self.assertTrue(all('fields' not in record and 'validated' not in record for record in details))

    async def test_disabled_created_tools_and_turn_do_not_touch_filesystem(self):
        root,config,state,registry,browser,app=helpers.OrchestratorTests().fixture([helpers.final_response,helpers.final_response])
        config.created_dir=root/'do-not-access-OneDrive'/'Documents'/'Copilot'/'Created'
        config.created_sync_enabled=False
        context={'config':config,'session_dir':state.directory}
        with patch('copilot_agent.tools.CreatedSync',side_effect=AssertionError('No OneDrive access')):
            for name in ('created.snapshot','created.wait'):
                result=await ToolRegistry().execute(name,{},context)
                self.assertTrue(result['ok'])
                self.assertEqual('disabled',result['result']['status'])
        with patch('copilot_agent.orchestrator.CreatedSync',side_effect=AssertionError('No OneDrive access')):
            await app.initialize()
            await app.turn('Harmless no-tool request.')
        self.assertIsNone(app.base_context['created_baseline'])

    async def test_enabling_sync_requires_explicit_account_path(self):
        with self.assertRaisesRegex(ValueError,'explicit OneDrive'):
            Config(created_sync_enabled=True,created_dir=None).validate()
