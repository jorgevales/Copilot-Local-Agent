"""Offline contracts for session grants, concise intake and method evolution."""
from copy import deepcopy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from copilot_agent.discovery_store import Store
from copilot_agent.knowledge_notes import execute_note
from copilot_agent.knowledge_views import site_folder, evidence_folder
from copilot_agent.policy import PolicyError
from copilot_agent.site_knowledge import (execute_knowledge, knowledge_session_grant,
    prepare_knowledge, session_knowledge_authorized)
import tests.test_site_knowledge as fixtures


class CentralizedKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.SiteKnowledgeTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.context = self.fx.context
        self.fx.bind()

    def grant(self):
        self.context['config'] = {'_knowledge_session_confirmed': True}
        self.context['knowledge_session_authorized'] = True
        self.context['knowledge_session_grant'] = knowledge_session_grant(self.context)

    def save(self, args):
        reviewed = prepare_knowledge(args, self.context, name='site_knowledge.save')
        self.context['site_knowledge_reviewed'] = reviewed
        return execute_knowledge('site_knowledge.save', args, self.context)

    def test_session_grant_replaces_extra_consent_but_cannot_cross_sessions(self):
        self.grant()
        self.assertTrue(session_knowledge_authorized(self.context))
        result = self.save(self.fx.save_args)
        self.assertEqual(result['status'], 'saved')
        self.assertNotIn('site_knowledge_consent', self.context)
        self.context['session_dir'] = self.fx.root / 'new-session'
        self.assertFalse(session_knowledge_authorized(self.context))
        self.context['session_dir'] = self.fx.root / 'session-a'
        self.context['config']['_knowledge_session_confirmed'] = False
        with self.assertRaises(PolicyError):
            self.save(self.fx.save_args)

    def test_explicit_tenant_binding_wins_over_automatic_fast_namespace(self):
        first = self.fx.retrieve()['namespace_id']
        self.context['config'] = {'_permissive_session': True}
        self.assertEqual(self.fx.retrieve()['namespace_id'], first)
        self.fx.bind(tenant='distinct-tenant')
        self.assertNotEqual(self.fx.retrieve()['namespace_id'], first)
        tenant = self.fx.retrieve()['namespace_id']
        self.fx.bind(tenant='distinct-tenant', application='operations')
        self.assertNotEqual(self.fx.retrieve()['namespace_id'], tenant)

    def test_raw_evidence_shares_site_root_but_never_merges_explicit_apps(self):
        first = evidence_folder(self.context, 'https://example.com/home?transient=yes', 'browser', root=self.fx.root)
        self.fx.bind(application='distinct-app')
        second = evidence_folder(self.context, 'https://example.com/documents', 'browser', root=self.fx.root)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parents[3], second.parents[3])
        self.assertNotIn('?', str(first))
        self.assertNotIn('transient', str(first))

    def test_duplicate_save_has_one_revision_and_one_stable_readable_view(self):
        self.grant()
        first = self.save(self.fx.save_args)
        second = self.save(self.fx.save_args)
        self.assertEqual(second['status'], 'unchanged')
        self.assertEqual(second['revision'], first['revision'])
        self.assertEqual(second['readable_view']['status'], 'verified')
        store = Store(self.context, persistent=True, readonly=True)
        try:
            self.assertEqual(len(store.site_knowledge_history(first['namespace_id'])), 1)
        finally:
            store.close()
        folder = site_folder(self.context, 'https://example.com')
        self.assertEqual(len(list(folder.rglob('current.md'))), 1)
        self.assertNotIn('?', str(folder))

    def method(self, identifier, paths, milliseconds):
        request = {'name': 'browser.plan', 'arguments': {'steps': [
            {'id': 'step' + str(index), 'op': 'navigate', 'url': 'https://example.com' + path}
            for index, path in enumerate(paths)]}}
        call = {'status': 'completed', 'request': request,
                'result': {'ok': True, 'result': {'status': 'verified',
                    'last_verified_state': {'url': 'https://example.com/documents'},
                    'results': [{'step_id': 'step' + str(index), 'verification': 'passed',
                                 'url': 'https://example.com' + path} for index, path in enumerate(paths)]}},
                'started_at': '2026-10-07T12:00:00+00:00',
                'finished_at': f'2026-10-07T12:00:0{milliseconds / 1000:.3f}+00:00'}
        calls = self.context.setdefault('session_state', SimpleNamespace(data={'calls': {}})).data['calls']
        calls[identifier] = call
        method = {'path': '/documents', 'purpose': 'documents', 'label': 'Documents navigation',
                  'steps': [{'path': path, 'strategy': 'navigate'} for path in paths],
                  'source_call_ids': [identifier], 'duration_ms': 1}
        return {'origin': 'https://example.com', 'categories': ['navigation_methods'],
                'knowledge': {'navigation_methods': [method]}}

    def test_faster_verified_method_is_recommended_and_previous_remains_labeled(self):
        self.grant()
        first = self.save(self.method('slow', ['/home', '/documents'], 2000))
        second = self.save(self.method('fast', ['/documents'], 500))
        self.assertEqual(second['revision'], first['revision'] + 1)
        from pathlib import Path
        text = Path(second['readable_view']['methods_path']).read_text()
        methods = json.loads(text[text.index('[\n'):])
        self.assertEqual([method['status'] for method in methods], ['recommended_verified', 'previous_verified'])
        self.assertEqual(methods[0]['duration_ms'], 500)
        self.assertEqual(len(methods[0]['steps']), 1)
        self.assertEqual(len(methods[1]['steps']), 2)
        self.assertNotIn('"source_call_ids": [\n      "fast"', text)
        fresh = self.fx.retrieve()
        self.assertEqual(len(fresh['knowledge']['navigation_methods']), 1)
        self.assertEqual(fresh['previous_methods_retained'], 1)

    def test_unobserved_method_and_unconfirmed_destination_are_rejected(self):
        self.grant()
        args = self.method('observed', ['/documents'], 500)
        self.context['session_state'].data['calls']['observed']['status'] = 'uncertain'
        with self.assertRaisesRegex(ValueError, 'completed successful'):
            self.save(args)
        self.context['session_state'].data['calls']['observed']['status'] = 'completed'
        self.context['session_state'].data['calls']['observed']['result']['result']['last_verified_state']['url'] = 'https://example.com/home'
        with self.assertRaisesRegex(ValueError, 'destination'):
            self.save(args)

    def test_note_is_centralized_deduplicated_and_strips_url_parameters(self):
        args = {'title': 'Documents route', 'content': 'Open https://example.com/documents?token=ephemeral#section'}
        first = execute_note('knowledge.note', args, self.context)
        second = execute_note('knowledge.note', dict(args, title='A different title'), self.context)
        self.assertEqual(second['status'], 'unchanged')
        self.assertEqual(first['note_id'], second['note_id'])
        self.assertTrue(first['directory'].startswith(str(site_folder(self.context, 'https://example.com'))))
        read = execute_note('knowledge.lookup', {'note_id': first['note_id']}, self.context)
        self.assertEqual(read['knowledge']['content'], 'Open https://example.com/documents')

    def test_note_rejects_secrets_contacts_and_customer_record_fields(self):
        for content in ('password: example-value', 'Contact jane@example.com', 'SSN 123-45-6789'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                execute_note('knowledge.note', {'title': 'Unsafe', 'content': content}, self.context)
        args = deepcopy(self.fx.save_args)
        args['categories'] = ['workflow']
        args['knowledge'] = {'workflow': [{'customer_name': 'Jane Example'}]}
        with self.assertRaises(ValueError):
            prepare_knowledge(args, self.context, name='site_knowledge.save')


class DiscoveryKnowledgeNoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_save_promotes_independent_proofs_then_skips_equivalent_third_run(self):
        from copilot_agent.discovery_engine import prepare_discovery, execute_discovery
        from copilot_agent.discovery_knowledge import prepare_knowledge_tool, execute_knowledge_tool
        from tests.discovery_fixtures import workspace, manifest, ORIGIN
        from tests.test_discovery_engine import static_response
        with workspace() as (root, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            context['config']['_knowledge_session_confirmed'] = True
            context['knowledge_session_authorized'] = True
            context['knowledge_session_grant'] = knowledge_session_grant(context)
            statuses = []
            for expected in (0, 1, 2):
                args = {'manifest': manifest()}
                reviewed = prepare_discovery(args, context)
                with patch('copilot_agent.discovery_http.PublicReader.fetch', new=static_response):
                    observed = await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))
                args = {'run_id': observed['run_id'], 'origin': ORIGIN, 'expected_revision': expected}
                reviewed = prepare_knowledge_tool('discovery.knowledge_save', args, context)
                result = await execute_knowledge_tool('discovery.knowledge_save', args,
                    dict(context, discovery_reviewed=reviewed))
                statuses.append(result['status'])
                self.assertEqual(result['readable_view']['status'], 'verified')
            self.assertEqual(statuses, ['saved', 'saved', 'unchanged'])
            self.assertEqual(result['revision'], 2)
            store = Store(context, persistent=True, readonly=True)
            try:
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM knowledge').fetchone()[0], 2)
            finally:
                store.close()
            self.assertEqual(sum(path.is_file() for path in (root / 'device' / 'sites').rglob('public-static-map.md')), 1)


if __name__ == '__main__':
    unittest.main()
