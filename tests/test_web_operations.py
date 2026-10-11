import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from copilot_agent.discovery_contracts import DiscoveryError
from copilot_agent.discovery_http import Response
from copilot_agent.discovery_store import Store
from copilot_agent.web_operations import (_partition, execute_operation,
                                           _decode, _failure_class, _shape,
                                           validate_operation)


ORIGIN = 'https://fixture.example'


class OperationTests(unittest.IsolatedAsyncioTestCase):
    def context(self, root, enabled=True):
        return {'config': {'root': root / 'source', 'storage_dir': root / 'onedrive',
                           'persistent_graph': True, 'operation_reuse': enabled,
                           'max_output_chars': 12000},
                'session_dir': root / 'session',
                'knowledge_directory': root / 'device',
                'cancel_event': threading.Event(), 'operation_cache': {}}

    def learn_args(self):
        return {'origin': ORIGIN, 'name': 'search',
                'intent': 'Return public search results',
                'example_url': ORIGIN + '/search?q=alpha',
                'example_args': {'query': 'alpha'},
                'example2_url': ORIGIN + '/search?q=bravo',
                'example2_args': {'query': 'bravo'},
                'validation_args': {'query': 'charlie'},
                'response': {'extract': ['results'], 'pick': ['title', 'url']},
                'expected_revision': 0}

    async def fake(self, context, origin, url, query_keys):
        query = parse_qs(urlsplit(url).query)['q'][0]
        body = json.dumps({'results': [{'title': query.title(),
                                       'url': ORIGIN + '/items/' + query}]}).encode()
        return Response(url, 200, 'application/json', body, ())

    async def learn(self, context):
        with patch('copilot_agent.web_operations._request', new=self.fake):
            return await execute_operation('operation.learn', self.learn_args(),
                                           dict(context, approved=True))

    async def test_two_examples_unseen_validation_and_restart_persistence(self):
        with tempfile.TemporaryDirectory(prefix='operation-test-') as temporary:
            root = Path(temporary)
            context = self.context(root)
            result = await self.learn(context)
            self.assertEqual(result['status'], 'validated_and_promoted')
            self.assertEqual(result['validation']['http_calls'], 3)
            self.assertEqual(result['copilot_ui_round_trips'], 0)
            restarted = self.context(root)
            listed = await execute_operation('operation.list', {'origin': ORIGIN}, restarted)
            self.assertEqual(listed['operations'][0]['name'], 'search')
            self.assertEqual(listed['operations'][0]['revision'], 1)
            store = Store(restarted, persistent=True)
            try:
                payload = store.operation(_partition(ORIGIN), 'search')['payload']
            finally:
                store.close()
            for example in ('alpha', 'bravo', 'charlie'):
                self.assertNotIn(example, payload)

    async def test_batch_deduplicates_and_cache_avoids_http(self):
        with tempfile.TemporaryDirectory(prefix='operation-test-') as temporary:
            context = self.context(Path(temporary))
            await self.learn(context)
            args = {'origin': ORIGIN, 'calls': [
                {'name': 'search', 'arguments': {'query': 'delta'}},
                {'name': 'search', 'arguments': {'query': 'delta'}}]}
            requests = []
            async def counted(*values):
                requests.append(values[2])
                return await self.fake(*values)
            with patch('copilot_agent.web_operations._request', new=counted):
                first = await execute_operation('operation.call', args, context)
                second = await execute_operation('operation.call', args, context)
            self.assertEqual(first['metrics']['duplicates_avoided'], 1)
            self.assertEqual(first['metrics']['http_calls'], 1)
            self.assertEqual(second['metrics']['http_calls'], 0)
            self.assertEqual(len(requests), 1)
            self.assertTrue(second['results'][0]['cache_hit'])
            self.assertEqual(first['metrics']['copilot_ui_round_trips'], 0)
            self.assertEqual(first['metrics']['browser_launches'], 0)

    async def test_shape_drift_is_classified_and_previous_version_retained(self):
        with tempfile.TemporaryDirectory(prefix='operation-test-') as temporary:
            context = self.context(Path(temporary))
            await self.learn(context)

            async def drift(*unused):
                return Response(ORIGIN + '/search?q=echo', 200, 'application/json',
                                b'{"renamed":[]}', ())

            call = {'origin': ORIGIN, 'calls': [
                {'name': 'search', 'arguments': {'query': 'echo'}}]}
            with patch('copilot_agent.web_operations._request', new=drift):
                result = await execute_operation('operation.call', call, context)
            self.assertEqual(result['results'][0]['class'], 'drift')
            self.assertFalse(result['results'][0]['automatic_retry'])
            listed = await execute_operation('operation.list', {'origin': ORIGIN}, context)
            self.assertEqual(listed['operations'][0]['status'], 'degraded')
            self.assertEqual(listed['operations'][0]['revision'], 1)

    async def test_feature_flag_inputs_and_credentials_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix='operation-test-') as temporary:
            root = Path(temporary)
            with self.assertRaises(DiscoveryError) as disabled:
                validate_operation('operation.list', {'origin': ORIGIN},
                                   self.context(root, enabled=False))
            self.assertEqual(disabled.exception.code, 'feature_disabled')
            unsafe = self.learn_args()
            unsafe['example_args'] = {'auth_token': 'public-example'}
            unsafe['example2_args'] = {'auth_token': 'another-example'}
            unsafe['validation_args'] = {'auth_token': 'third-example'}
            with self.assertRaises(DiscoveryError) as rejected:
                validate_operation('operation.learn', unsafe, self.context(root))
            self.assertEqual(rejected.exception.code, 'validation_input')

    async def test_compare_and_swap_preserves_prior_working_version(self):
        with tempfile.TemporaryDirectory(prefix='operation-test-') as temporary:
            context = self.context(Path(temporary))
            await self.learn(context)
            stale = self.learn_args()
            with patch('copilot_agent.web_operations._request', new=self.fake):
                with self.assertRaises(DiscoveryError) as rejected:
                    await execute_operation('operation.learn', stale,
                                            dict(context, approved=True))
            self.assertEqual(rejected.exception.code, 'stale_knowledge_revision')
            store = Store(context, persistent=True)
            try:
                rows = store.db.execute(
                    'SELECT revision,status FROM operations WHERE partition=? AND name=?',
                    (_partition(ORIGIN), 'search')).fetchall()
            finally:
                store.close()
            self.assertEqual([(row['revision'], row['status']) for row in rows], [(1, 'active')])

    def test_nonstandard_json_and_heterogeneous_arrays_fail_closed(self):
        response = Response(ORIGIN + '/search', 200, 'application/json',
                            b'{"results":[NaN]}', ())
        with self.assertRaises(DiscoveryError) as invalid:
            _decode(response)
        self.assertEqual(invalid.exception.code, 'invalid_json')
        with self.assertRaises(DiscoveryError) as unstable:
            _shape([{'title': 'one'}, {'renamed': 'two'}])
        self.assertEqual(unstable.exception.code, 'unexpected_transition')

    def test_recovery_classes_do_not_blur_policy_boundaries(self):
        expected = {'authentication_required': 'auth', 'rate_limited': 'rate',
                    'access_denied': 'blocked', 'route_missing': 'drift',
                    'validation_input': 'input', 'transport_error': 'error'}
        for code, classification in expected.items():
            self.assertEqual(_failure_class(DiscoveryError(code)), classification)


if __name__ == '__main__':
    unittest.main()
