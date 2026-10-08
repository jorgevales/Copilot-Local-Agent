"""NOT RUN. Future mocked scheduler/transport/store/privacy tests; no real egress."""
import asyncio
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from copilot_agent.discovery_contracts import DiscoveryError, compile_manifest
from copilot_agent.discovery_engine import Engine, prepare_discovery, execute_discovery, project_result
from copilot_agent.discovery_http import Response, ReadFailure, TLSStream
from copilot_agent.discovery_store import Store, alias, digest
from copilot_agent.tools import ToolRegistry
from tests.discovery_fixtures import ORIGIN, manifest, workspace, task


async def static_response(reader, url, deadline, method='GET'):
    body = (b'<html><nav><a href="/documents">Documents</a></nav><main>SECRET_CANARY</main></html>'
            if url == ORIGIN + '/' else b'<html><main><h1>Documents</h1></main></html>')
    return Response(url, 200, 'text/html', b'' if method == 'HEAD' else body, ())


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, context, m=None):
        m = manifest() if m is None else m
        args = {'manifest': m}
        reviewed = prepare_discovery(args, context)
        with patch('copilot_agent.discovery_http.PublicReader.fetch', new=static_response):
            return await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))

    async def test_unexpected_scheduler_failure_fences_tasks_and_records_terminal_run(self):
        with workspace() as (_, context):
            engine = Engine(compile_manifest(manifest()), context)
            run_id = engine.run_id
            with patch.object(engine, 'dependency', side_effect=RuntimeError('synthetic scheduler fault')):
                with self.assertRaisesRegex(RuntimeError, 'scheduler fault'):
                    await engine.run()
            store = Store(context, persistent=True, readonly=True)
            try:
                record = store.run(run_id)
                self.assertEqual('TERMINAL', record['state'])
                self.assertEqual('failed', json.loads(record['result'])['outcome'])
                self.assertTrue(all(store.task(run_id, task_id)['state'] in {'FAILED', 'SKIPPED'}
                                    for task_id in engine.graph.order))
            finally:
                store.close()

    async def test_disabled_flag_rejects_and_live_gate_accepts_preparation(self):
        with workspace() as (_, context):
            context['config']['manifest_path'] = False
            with patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
                result = await ToolRegistry().execute('discovery.manifest', {'manifest': manifest()}, context)
            self.assertFalse(result['ok']); self.assertEqual(result['error']['code'], 'feature_disabled')
            context['config']['manifest_path'] = True
            with patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'live'}):
                self.assertIsNotNone(prepare_discovery({'manifest': manifest()}, context))

    async def test_missing_exact_preparation_rejects_before_engine(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            with patch('copilot_agent.discovery_engine.Engine') as engine:
                with self.assertRaises(DiscoveryError):
                    await execute_discovery('discovery.manifest', {'manifest': manifest()}, context)
                engine.assert_not_called()

    async def test_shadow_no_network_no_persistence(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            with patch('copilot_agent.discovery_engine.Engine') as engine:
                result = await execute_discovery('discovery.shadow', {'manifest': manifest()}, context)
                self.assertEqual(result['network_requests'], 0)
                self.assertFalse(result['persistent_records_written']); engine.assert_not_called()

    async def test_end_to_end_static_graph_and_expansion_no_secrets(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            result = await self.execute(context)
            self.assertEqual(result['outcome'], 'complete')
            self.assertEqual(result['terminal_reason'], 'queue_exhausted')
            cache = context['discovery_runs'][result['run_id']]
            pages = [m for m, a in cache['artifacts'] if m['type'] == 'page']
            self.assertEqual({m['source_url'] for m in pages}, {ORIGIN + '/', ORIGIN + '/documents'})
            self.assertNotIn('SECRET_CANARY', json.dumps(cache['artifacts']))
            self.assertTrue(all(t['state'] == 'SUCCEEDED' for t in result['tasks']))

    async def test_partial_sibling_diagnostics_and_terminal_merge(self):
        m = manifest()
        m['tasks'].insert(2, task('failed', 'http', ['bootstrap'], ['bootstrap'], [ORIGIN + '/help']))
        m['tasks'][3]['depends_on'].append({'task_id': 'failed', 'accept': 'terminal'})
        m['tasks'][3]['inputs']['evidence_from'].append('failed')
        async def response(reader, url, deadline, method='GET'):
            if url.endswith('/help'): raise ReadFailure('access_denied')
            return await static_response(reader, url, deadline, method)
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            args = {'manifest': m}; reviewed = prepare_discovery(args, context)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=response):
                result = await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))
            self.assertEqual(result['outcome'], 'partial')
            self.assertTrue(any(e['type'] == 'page' for e in result['evidence']))
            self.assertEqual(next(t for t in result['tasks'] if t['id'] == alias('failed'))['state'], 'FAILED')
            self.assertTrue(result['gaps'])

    async def test_parallel_dependencies_no_early_merge(self):
        m = manifest(); m['budgets']['concurrency'] = 2
        m['tasks'][1]['expand_urls'] = False
        m['tasks'].insert(2, task('other', 'http', ['bootstrap'], ['bootstrap'], [ORIGIN + '/help']))
        m['tasks'][3]['depends_on'].append({'task_id': 'other', 'accept': 'usable'})
        m['tasks'][3]['inputs']['evidence_from'].append('other')
        waiting, overlap = set(), asyncio.Event()
        async def response(reader, url, deadline, method='GET'):
            if method == 'GET':
                waiting.add(url)
                if len(waiting) == 2: overlap.set()
                await asyncio.wait_for(overlap.wait(), 1)
            return await static_response(reader, url, deadline, method)
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            context['config']['bounded_parallelism'] = True
            args = {'manifest': m}; reviewed = prepare_discovery(args, context)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=response):
                result = await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))
            self.assertTrue(overlap.is_set()); self.assertEqual(result['outcome'], 'complete')

    async def test_cancel_generation_keeps_cancelled_outcome(self):
        with workspace() as (_, context), patch.dict(os.environ, {'COPILOT_AGENT_EXECUTION_MODE': 'testing'}):
            async def stop(reader, url, deadline, method='GET'):
                if method == 'GET':
                    context['cancel_event'].set(); await asyncio.sleep(.1)
                return await static_response(reader, url, deadline, method)
            args = {'manifest': manifest()}; reviewed = prepare_discovery(args, context)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=stop):
                result = await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))
            self.assertEqual(result['outcome'], 'cancelled'); self.assertEqual(result['terminal_reason'], 'cancelled')

    async def test_budget_atomic_byte_reservations_and_settlement(self):
        with workspace() as (_, context):
            store = Store(context)
            try:
                graph = compile_manifest(manifest()); store.create_run('run', graph, 'partition', 'owner')
                first = store.reserve_bytes('run', 8, 10)
                second = store.reserve_bytes('run', 8, 10)
                self.assertEqual((first, second), (8, 2))
                with self.assertRaises(DiscoveryError): store.reserve_bytes('run', 1, 10)
                store.settle_bytes('run', first, 4); store.settle_bytes('run', second, 2)
                self.assertEqual(store.counters('run')['bytes'], 6)
                self.assertEqual(store.counters('run')['bytes_reserved'], 0)
            finally: store.close()

    async def test_stale_fence_terminal_immutability_and_cancel_commit(self):
        with workspace() as (_, context):
            store = Store(context)
            try:
                graph = compile_manifest(manifest()); store.create_run('run', graph, 'partition', 'owner')
                store.transition('run', 'bootstrap', 'READY', 'ready')
                fence, deadline = store.lease('run', 'bootstrap', 'owner', 20, 40)
                with self.assertRaises(DiscoveryError): store.commit('run', 'bootstrap', 'other', fence, 'SUCCEEDED', 'done', [])
                with self.assertRaises(DiscoveryError): store.commit('run', 'bootstrap', 'owner', fence - 1, 'SUCCEEDED', 'done', [])
                store.cancel('run')
                with self.assertRaises(DiscoveryError): store.commit('run', 'bootstrap', 'owner', fence, 'SUCCEEDED', 'done', [])
                with self.assertRaises(DiscoveryError): store.transition('run', 'bootstrap', 'READY', 'reopen')
            finally: store.close()

    async def test_canary_dom_values_never_become_artifacts(self):
        from copilot_agent.discovery_engine import extract
        from copilot_agent.discovery_scope import Scope
        r = Response(ORIGIN + '/', 200, 'text/html', b'<input value="SECRET_CANARY"><a href="/documents?token=SECRET_CANARY">SECRET_CANARY</a>', ())
        artifact = extract(r, Scope(manifest()['scope']))
        self.assertNotIn('SECRET_CANARY', json.dumps(artifact)); self.assertEqual(artifact['blocked_links'], 1)

    async def test_login_form_is_boundary_not_trusted_page(self):
        from copilot_agent.discovery_engine import extract
        from copilot_agent.discovery_scope import Scope
        r = Response(ORIGIN + '/', 200, 'text/html', b'<input type="password" value="CANARY">', ())
        with self.assertRaises(ReadFailure): extract(r, Scope(manifest()['scope']))
