import unittest
from types import SimpleNamespace
from pathlib import Path
from tests import test_site_knowledge as fixtures
from copilot_agent.knowledge_notes import execute_note
from copilot_agent.procedure_memory import matching_procedures, reusable_plan_template
from copilot_agent.site_knowledge import knowledge_session_grant


class ProcedureMemoryTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.SiteKnowledgeTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.context = self.fx.context
        self.context.update(config={'_knowledge_session_confirmed': True, 'allowed_domains': ['example.com']},
                            approved=True, knowledge_session_authorized=True, approval_hash='a' * 64)
        self.context['knowledge_session_grant'] = knowledge_session_grant(self.context)
        self.args = {'title': 'Create synthetic patient and start consultation',
                     'content': 'Input slots: {input_name}. Procedure: open /patients/new, fill the name, '
                                'start consultation once and verify the displayed identity. Stop before finishing.'}
        self.note = execute_note('knowledge.note', self.args, self.context)
        self.request = 'At https://example.com create a synthetic patient and start consultation.'

    def test_fresh_session_retrieves_verified_procedure_without_an_owned_page(self):
        fresh = dict(self.context, session_dir=self.fx.root / 'session-b', browser=None)
        fresh['knowledge_session_grant'] = knowledge_session_grant(fresh)
        result = matching_procedures(self.request, fresh)
        self.assertEqual([self.note['note_id']], [item['note_id'] for item in result])
        self.assertTrue(result[0]['requires_live_verification'])

    def test_wrong_origin_missing_scope_and_unrelated_task_do_not_reuse_note(self):
        self.assertEqual([], matching_procedures(self.request.replace('example.com', 'elsewhere.test'), self.context))
        self.assertEqual([], matching_procedures('Create a synthetic patient and start consultation.', self.context))
        self.assertEqual([], matching_procedures('At https://example.com export inventory totals.', self.context))
        self.assertEqual([], matching_procedures(self.request, dict(self.context, knowledge_session_authorized=False)))

    def test_explicit_tenant_does_not_reuse_automatic_namespace_note(self):
        self.fx.bind()
        self.assertEqual([], matching_procedures(self.request, self.context))

    def test_changed_note_is_not_reused(self):
        path = Path(self.note['directory']) / (self.note['note_id'] + '.json')
        path.write_text('changed', encoding='utf-8')
        self.assertEqual([], matching_procedures(self.request, self.context))

    def test_known_procedure_completion_requires_a_verified_update(self):
        from copilot_agent.orchestrator import Orchestrator
        agent = object.__new__(Orchestrator)
        agent.prompts = SimpleNamespace(procedure_references=[{'note_id': 'prior'}])
        calls = {'plan': {'request': {'name': 'browser.plan'},
                          'result': {'ok': True, 'result': {'status': 'verified'}}}}
        agent.state = SimpleNamespace(data={'calls': calls})
        self.assertTrue(agent._procedure_update_missing({'plan'}))
        calls['note'] = {'request': {'name': 'knowledge.note'},
                         'result': {'ok': False, 'result': {'verified': False}}}
        self.assertTrue(agent._procedure_update_missing({'plan', 'note'}))
        calls['note']['result'] = {'ok': True, 'result': {'verified': True}}
        self.assertFalse(agent._procedure_update_missing({'plan', 'note'}))
        self.assertTrue(agent._procedure_update_missing({'plan'}), 'Old-turn updates cannot satisfy this run.')
        calls['plan']['result']['result']['status'] = 'interrupted'
        self.assertFalse(agent._procedure_update_missing({'plan'}), 'Partial runs must not be promoted.')

    def test_template_preserves_exact_arrays_and_separates_equal_date_inputs(self):
        from copilot_agent.web_navigation import validate_navigation
        source = {'task_id': 'synthetic-task', 'steps': [
            {'id': 'name', 'op': 'fill', 'locator': {'id': 'name'}, 'value': 'Synthetic Alpha'},
            {'id': 'day', 'op': 'fill', 'locator': {'id': 'day'}, 'value': '01',
             'expect': [{'kind': 'text', 'locator': {'id': 'day'}, 'value': '01'}]},
            {'id': 'month', 'op': 'fill', 'locator': {'id': 'month'}, 'value': '01',
             'expect': [{'kind': 'text', 'locator': {'id': 'month'}, 'value': '01'}]},
            {'id': 'submit', 'op': 'click', 'locator': {'id': 'submit'}, 'effect': 'consequential',
             'expect': [{'kind': 'visible', 'locator': {'text': 'Ficha'}}]}],
             'success': [{'kind': 'text', 'locator': {'id': 'patient'}, 'value': 'Paciente: Synthetic Alpha'}]}
        template = reusable_plan_template(source)
        self.assertIsNotNone(template)
        plan = template['arguments']
        self.assertEqual('{{input_2}}', plan['steps'][1]['expect'][0]['value'])
        self.assertEqual('{{input_3}}', plan['steps'][2]['expect'][0]['value'])
        self.assertEqual('Paciente: {{input_1}}', plan['success'][0]['value'])
        self.assertNotIn('Synthetic Alpha', str(template))
        validate_navigation('browser.plan', plan)
        self.assertIsNone(reusable_plan_template(dict(source, customer_key='different-record')))
        dynamic = dict(source, success=[{'kind': 'url', 'value': 'https://example.com/consultations/{id}/ficha'}])
        self.assertIsNone(reusable_plan_template(dynamic))
