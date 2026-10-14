"""Real offline Crawl4AI + synthetic pinned transport; no VDI/shared-drive proof."""
import asyncio
import json
import unittest
from unittest.mock import patch

from copilot_agent.discovery_contracts import DiscoveryError, compile_manifest
from copilot_agent.discovery_engine import Engine, extract, prepare_discovery, execute_discovery
from copilot_agent.discovery_http import ReadFailure, Response
from copilot_agent.discovery_scope import Scope
from copilot_agent.discovery_knowledge import prepare_knowledge_tool, execute_knowledge_tool
from tests.discovery_fixtures import ORIGIN, manifest, workspace


class Crawl4AITests(unittest.IsolatedAsyncioTestCase):
    def test_real_extraction_observed_base_and_privacy_without_extra_network(self):
        from copilot_agent.crawl4ai_adapter import strategy_type
        strategy_type()
        body = b'''<html><head><base href="/help/"></head><body>
        <a href="documents">SECRET_CANARY</a><a href="https://outside.example/help">out</a>
        <a href="/help?token=SECRET_CANARY">secret</a><img src="https://outside.example/private">
        <script>SECRET_CANARY</script><input value="SECRET_CANARY"></body></html>'''
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network')):
            result = extract(Response(ORIGIN+'/', 200, 'text/html', body, ()),
                             Scope(manifest()['scope']), 'crawl4ai')
        self.assertEqual([ORIGIN+'/help/documents'], result['links'])
        self.assertEqual(2, result['blocked_links'])
        self.assertEqual('crawl4ai', result['extractor'])
        self.assertNotIn('SECRET_CANARY', json.dumps(result))

    def test_authentication_stops_before_upstream_extraction(self):
        from copilot_agent.discovery_scope import Scope
        with patch('copilot_agent.crawl4ai_adapter.extract_links') as upstream:
            with self.assertRaises(ReadFailure) as caught:
                extract(Response(ORIGIN+'/', 200, 'text/html', b'<input type="password">', ()),
                        Scope(manifest()['scope']), 'crawl4ai')
        self.assertEqual('authentication_required', caught.exception.code)
        upstream.assert_not_called()

    def test_missing_dependency_rejects_before_network_or_store(self):
        with workspace() as (_, context):
            context['config']['discovery_extractor'] = 'crawl4ai'
            with patch('copilot_agent.crawl4ai_adapter.strategy_type', side_effect=ReadFailure('capability_unavailable')):
                with self.assertRaises(ReadFailure):
                    prepare_discovery({'manifest': manifest()}, context)
            self.assertFalse(context['discovery_runs'])

    def test_deep_resource_ceiling_still_rejects_unbounded_reads(self):
        m = manifest()
        m['budgets'].update(pages=1000, tasks=5000, requests=5000, bytes=512*1024*1024,
                            concurrency=8, per_origin_concurrency=4, depth=10)
        compile_manifest(m)
        m['budgets']['concurrency'] = 9
        with self.assertRaises(DiscoveryError):
            compile_manifest(m)

    async def test_parallel_deep_crawl_save_read_all_routes_and_resume_frontier(self):
        routes = ['/help/page-' + chr(97+i//26) + chr(97+i%26) for i in range(125)]
        active, peak = 0, 0
        async def response(reader, url, deadline, method='GET'):
            nonlocal active, peak
            if method == 'HEAD':
                return Response(url, 200, 'text/html', b'', ())
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.001)
                body = ('<nav>' + ''.join('<a href="'+p+'">navigation</a>' for p in routes) + '</nav>'
                        if url == ORIGIN+'/' else '<main><h1>Help</h1></main>')
                return Response(url, 200, 'text/html', body.encode(), ())
            finally:
                active -= 1
        with workspace() as (_, context):
            context['config'].update(discovery_extractor='crawl4ai', bounded_parallelism=True)
            m = manifest()
            m['budgets'].update(pages=150, tasks=200, requests=500, concurrency=4,
                                per_origin_concurrency=2)
            args = {'manifest': m}
            reviewed = prepare_discovery(args, context)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=response):
                result = await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))
            self.assertEqual('complete', result['outcome'])
            self.assertGreater(peak, 1)
            self.assertLessEqual(peak, 4)
            run = context['discovery_runs'][result['run_id']]
            self.assertEqual(126, len([a for meta,a in run['artifacts'] if meta['type']=='page']))
            save = {'origin': ORIGIN, 'run_id': result['run_id'], 'expected_revision': 0}
            consent = prepare_knowledge_tool('discovery.knowledge_save', save, context)
            receipt = await execute_knowledge_tool('discovery.knowledge_save', save,
                dict(context, discovery_reviewed=consent, discovery_save_consent=consent))
            self.assertEqual(126, receipt['route_count'])
            seen, offset = [], 0
            while offset is not None:
                page = await execute_knowledge_tool('discovery.knowledge_lookup',
                    {'origin': ORIGIN, 'offset': offset, 'limit': 40}, context)
                seen.extend(r['url'] for r in page['routes'])
                offset = page['next_offset']
            self.assertEqual(126, len(set(seen)))
            # A new run may reuse only consented, bound, verified observations.
            engine = Engine(compile_manifest(m), context)
            try:
                self.assertEqual([], engine.saved_frontier())
            finally:
                engine.store.fail_run(engine.run_id)
                engine.store.close()

    async def test_partial_saved_frontier_is_revisited_and_cancel_stops_children(self):
        from tests.test_discovery_engine import static_response
        with workspace() as (_, context):
            context['config']['bounded_parallelism'] = True
            m = manifest()
            m['tasks'][1]['expand_urls'] = False
            args = {'manifest': m}
            reviewed = prepare_discovery(args, context)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=static_response):
                result = await execute_discovery('discovery.manifest', args, dict(context, discovery_reviewed=reviewed))
            save = {'origin': ORIGIN, 'run_id': result['run_id'], 'expected_revision': 0}
            consent = prepare_knowledge_tool('discovery.knowledge_save', save, context)
            await execute_knowledge_tool('discovery.knowledge_save', save,
                dict(context, discovery_reviewed=consent, discovery_save_consent=consent))
            m['tasks'][1]['expand_urls'] = True
            m['budgets'].update(concurrency=2, per_origin_concurrency=2)
            engine = Engine(compile_manifest(m), context)
            self.assertEqual([(ORIGIN+'/documents', 1, ORIGIN+'/')], engine.saved_frontier())
            started, active = asyncio.Event(), set()
            async def waiting(reader, url, deadline, method='GET'):
                if method == 'HEAD':
                    return await static_response(reader, url, deadline, method)
                active.add(url)
                started.set()
                try:
                    await asyncio.sleep(30)
                finally:
                    active.remove(url)
            with patch('copilot_agent.discovery_http.PublicReader.fetch', new=waiting):
                run = asyncio.create_task(engine.run())
                await asyncio.wait_for(started.wait(), 2)
                context['cancel_event'].set()
                result = await asyncio.wait_for(run, 2)
            self.assertEqual('cancelled', result['outcome'])
            self.assertFalse(active)


class SharedMappingTests(unittest.TestCase):
    def test_s_alias_and_explicit_knowledge_path_use_verified_share_identity(self):
        from copilot_agent.storage import discoveries_storage
        from copilot_agent.site_knowledge import knowledge_directory
        with workspace() as (root, _):
            share = root/'share'
            project = share/'Projects'/'Agent'
            project.mkdir(parents=True)
            expected = (share/'Projects'/'Discoveries knowledge').resolve()
            config = {'root': 'S:\\Projects\\Agent', 'knowledge_directory': 'S:\\Projects\\Discoveries knowledge'}
            with patch('copilot_agent.policy.mapped_s_drive_root', return_value=share), patch('copilot_agent.site_knowledge.mapped_s_drive_root', return_value=share):
                self.assertEqual(expected, discoveries_storage(config['root']))
                self.assertEqual(expected, knowledge_directory({'config': config}))

    def test_direct_mapping_keeps_provider_fallback_unused(self):
        from copilot_agent.policy import mapped_s_drive_root
        with patch('copilot_agent.policy.os.name', 'nt'), patch('copilot_agent.policy._final_s_path', return_value=r'\\server\share'), patch('copilot_agent.policy._mapped_s_provider_root') as fallback:
            self.assertEqual(r'\\server\share', str(mapped_s_drive_root()).rstrip('\\'))
        fallback.assert_not_called()

    def test_provider_fallback_tries_later_live_unc_and_stops_without_mapping(self):
        from types import SimpleNamespace
        from copilot_agent.policy import _mapped_s_provider_root, PolicyError
        result = SimpleNamespace(returncode=0, stdout=json.dumps([r'\\stale\share', r'\\server\share']))
        with patch('subprocess.run', return_value=result) as process, patch('copilot_agent.policy._final_s_path', side_effect=[PolicyError('unavailable'), r'\\server\share']), patch('pathlib.Path.is_dir', return_value=True), patch('copilot_agent.policy.reject_path_redirection'):
            self.assertEqual(r'\\server\share', _mapped_s_provider_root())
            self.assertEqual(10, process.call_args.kwargs['timeout'])
        result.stdout = '[]'
        with patch('subprocess.run', return_value=result), self.assertRaises(PolicyError):
            _mapped_s_provider_root()
