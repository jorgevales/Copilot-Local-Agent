"""NOT RUN. Future consent/CAS/independent-proof/static-intent tests, mocked egress."""
from copy import deepcopy
import os
import unittest
from unittest.mock import patch

from copilot_agent.discovery_contracts import DiscoveryError
from copilot_agent.discovery_engine import prepare_discovery, execute_discovery
from copilot_agent.discovery_knowledge import (prepare_knowledge_tool, execute_knowledge_tool,
                                              compile_intent, check_plan, reliable_route)
from tests.discovery_fixtures import ORIGIN, manifest, intent, workspace
from tests.test_discovery_engine import static_response


class KnowledgeTests(unittest.IsolatedAsyncioTestCase):
    async def observe_and_save(self, context, expected):
        args = {'manifest': manifest()}
        reviewed = prepare_discovery(args, context)
        with patch('copilot_agent.discovery_http.PublicReader.fetch', new=static_response):
            result = await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))
        save = {'run_id': result['run_id'], 'origin': ORIGIN, 'expected_revision': expected}
        consent = prepare_knowledge_tool('discovery.knowledge_save', save, context)
        saved = await execute_knowledge_tool('discovery.knowledge_save', save,
                    dict(context, discovery_reviewed=consent, discovery_save_consent=consent))
        return saved, save, consent

    async def test_one_observation_candidate_two_independent_runs_trusted(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            first, _, _ = await self.observe_and_save(context, 0)
            self.assertEqual(first['trusted_routes'], 0)
            second, _, _ = await self.observe_and_save(context, 1)
            self.assertEqual(second['trusted_routes'], 2)
            self.assertEqual(second['revision'], 2)

    async def test_save_requires_separate_exact_consent_and_cas(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            _, save, consent = await self.observe_and_save(context, 0)
            save['expected_revision'] = 1
            consent = prepare_knowledge_tool('discovery.knowledge_save', save, context)
            with self.assertRaises(DiscoveryError):
                await execute_knowledge_tool('discovery.knowledge_save', save, dict(context, discovery_reviewed=consent))
            stale = dict(save, expected_revision=0)
            with self.assertRaises(DiscoveryError): prepare_knowledge_tool('discovery.knowledge_save', stale, context)

    async def test_namespace_switch_cannot_reassign_source_run(self):
        from copilot_agent.site_knowledge import prepare_knowledge, execute_knowledge
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            _, save, _ = await self.observe_and_save(context, 0)
            binding = {'origin': ORIGIN, 'tenant': 'other-tenant', 'user_scope': 'private-user', 'environment': 'test'}
            reviewed = prepare_knowledge(binding, context, name='site_knowledge.bind')
            execute_knowledge('site_knowledge.bind', binding, dict(context, site_knowledge_reviewed=reviewed))
            save['expected_revision'] = 0
            with self.assertRaises(DiscoveryError): prepare_knowledge_tool('discovery.knowledge_save', save, context)

    async def test_locally_compiled_static_intent_and_zero_action_observation(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            await self.observe_and_save(context, 0); await self.observe_and_save(context, 1)
            args = {'intent': intent(manifest()['scope'])}
            plan, knowledge = compile_intent(args, context)
            self.assertEqual(len(plan['steps']), 1)
            self.assertEqual(plan['steps'][0]['effect'], 'read')
            reviewed = prepare_knowledge_tool('navigation.intent', args, context)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=static_response):
                result = await execute_knowledge_tool('navigation.intent', args, dict(context, discovery_reviewed=reviewed))
            self.assertEqual(result['status'], 'verified_static_target'); self.assertFalse(result['browser_navigated'])
            zero = {'intent': intent(manifest()['scope'], 'landing')}
            plan, _ = compile_intent(zero, context); self.assertEqual(plan['steps'], [])
            reviewed = prepare_knowledge_tool('navigation.intent', zero, context)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=static_response):
                result = await execute_knowledge_tool('navigation.intent', zero, dict(context, discovery_reviewed=reviewed))
            self.assertTrue(result['zero_action_verified']); self.assertTrue(result['evidence_ids'])

    async def test_step_chain_and_revision_poisoning_rejected(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            await self.observe_and_save(context, 0); await self.observe_and_save(context, 1)
            plan, knowledge = compile_intent({'intent': intent(manifest()['scope'])}, context)
            for mutate in (lambda p: p.update(knowledge_revision=999),
                           lambda p: p['steps'][0].update(effect='consequential'),
                           lambda p: p['steps'][0].update(from_route=p['target_route'])):
                bad = deepcopy(plan); mutate(bad)
                with self.assertRaises(DiscoveryError): check_plan(bad, knowledge)

    async def test_fingerprint_drift_stops_before_later_reads(self):
        from copilot_agent.discovery_http import Response
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            await self.observe_and_save(context, 0); await self.observe_and_save(context, 1)
            args = {'intent': intent(manifest()['scope'])}
            reviewed = prepare_knowledge_tool('navigation.intent', args, context)
            calls = []
            async def changed(reader, url, deadline, method='GET'):
                calls.append((method, url))
                if method == 'GET' and url == ORIGIN + '/':
                    return Response(url, 200, 'text/html', b'<html><article><h2>Changed</h2></article></html>', ())
                return await static_response(reader, url, deadline, method)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=changed):
                with self.assertRaises(DiscoveryError):
                    await execute_knowledge_tool('navigation.intent', args, dict(context, discovery_reviewed=reviewed))
            self.assertNotIn(('GET', ORIGIN + '/documents'), calls)

    async def test_invalidation_cas_read_disables_new_namespace(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            await self.observe_and_save(context, 0)
            args = {'origin': ORIGIN, 'expected_revision': 1}
            reviewed = prepare_knowledge_tool('discovery.knowledge_invalidate', args, context)
            result = await execute_knowledge_tool('discovery.knowledge_invalidate', args, dict(context, discovery_reviewed=reviewed))
            self.assertEqual(result['status'], 'invalidated')
            lookup = await execute_knowledge_tool('discovery.knowledge_lookup', {'origin': ORIGIN}, context)
            self.assertEqual(lookup['status'], 'knowledge_invalidated')
            self.assertEqual(lookup['revision'], 1)
