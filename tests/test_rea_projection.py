"""Large Node observations retain honest coverage and bounded chat output."""
import copy
import json
import unittest

from copilot_agent.rea_projection import compact_node_result


def evidence():
    findings = {'kind': 'rea.web-page-inspection',
                'dom': {'total_nodes': 9980, 'complete': True,
                        'nodes': [{'id': index, 'text': 'x' * 1000}
                                  for index in range(9980)]},
                'accessibility': {'total_nodes': 5825, 'complete': True},
                'coverage': {'status': 'completed'}}
    return {'backend': 'node_cli', 'status': 'completed', 'tool': 'rea.inspect_page',
            'execution_id': 'fixture', 'observation_verified': True,
            'coverage_complete': True, 'side_effects_uncertain': False,
            'target': 'https://studio.example.test/page',
            'provenance': {'interface': 'REA fixed CLI', 'version': '6.5.0'},
            'confidence': 'observed', 'findings': findings,
            'limitations': ['Passive observation only.'], 'unknowns': ['Future state.'],
            'evidence': {'evidence_id': 'ev_fixture',
                         'provider': {'id': 'rea', 'version': '6.5.0'},
                         'operation': 'inspect-web-page', 'normalized_result': findings},
            'process_diagnostics': {'phase': 'analysis', 'stdout_bytes': 4008122,
                                    'stderr_bytes': 0, 'returncode': 0}}


def project(result, limit=16384, **changes):
    arguments = {'full_evidence_path': r'S:\evidence\fixture.json',
                 'full_evidence_sha256': 'a' * 64,
                 'full_evidence_bytes': 4008122, 'limit': limit}
    arguments.update(changes)
    return compact_node_result(result, **arguments)


class REAProjectionTests(unittest.TestCase):
    def test_large_completed_evidence_keeps_actual_counts_and_status(self):
        original = evidence()
        projected = project(original)
        self.assertIsNotNone(projected)
        self.assertLessEqual(len(json.dumps(projected, ensure_ascii=True).encode()), 16384)
        self.assertEqual('completed', projected['status'])
        self.assertTrue(projected['coverage_complete'])
        self.assertTrue(projected['observation_verified'])
        self.assertTrue(projected['response_truncated'])
        self.assertEqual(9980, projected['findings']['dom']['total_nodes'])
        self.assertEqual(5825, projected['findings']['accessibility']['total_nodes'])
        self.assertEqual(9980, projected['findings']['dom']['nodes']['total_items'])
        self.assertGreater(projected['findings']['dom']['nodes']['omitted_items'], 9000)
        self.assertEqual('ev_fixture', projected['evidence']['evidence_id'])
        self.assertEqual('rea', projected['evidence']['provider']['id'])
        self.assertEqual('observed', projected['confidence'])
        self.assertEqual('a' * 64, projected['evidence_sha256'])
        self.assertEqual(projected['evidence_path'], projected['full_evidence_path'])
        self.assertEqual(projected['evidence_sha256'], projected['full_evidence_sha256'])
        self.assertEqual(4008122, projected['process_diagnostics']['stdout_bytes'])
        self.assertEqual(9980, len(original['findings']['dom']['nodes']))

    def test_partial_remains_partial_and_explicit_gaps_survive(self):
        result = evidence()
        result.update(status='partial', coverage_complete=False)
        result['findings']['coverage'] = {'status': 'partial', 'reason': 'DOM budget'}
        projected = project(result)
        self.assertEqual('partial', projected['status'])
        self.assertFalse(projected['coverage_complete'])
        self.assertEqual('DOM budget', projected['findings']['coverage']['reason'])
        self.assertIn('Passive observation only.', projected['limitations'])
        self.assertIn('Future state.', projected['unknowns'])

    def test_fallback_attempt_diagnostics_cannot_be_dropped_by_large_findings(self):
        result = evidence()
        result.update(degraded=True, fallback_used=True, intended_backend_succeeded=False,
                      prior_backend_attempt={'backend': 'node_cli', 'status': 'timeout',
                                             'execution_id': 'previous',
                                             'error': {'code': 'analysis_timeout'},
                                             'stderr': 'x' * 100000})
        projected = project(result)
        self.assertTrue(projected['degraded'])
        self.assertTrue(projected['fallback_used'])
        self.assertFalse(projected['intended_backend_succeeded'])
        self.assertEqual('timeout', projected['prior_backend_attempt']['status'])
        self.assertEqual('node_cli', projected['prior_backend_attempt']['backend'])
        self.assertEqual('analysis_timeout', projected['prior_backend_attempt']['error']['code'])
        self.assertLessEqual(len(json.dumps(projected).encode()), 16384)

    def test_failure_or_unverified_observation_is_never_projected_as_success(self):
        for changes in ({'backend': 'python_native'}, {'status': 'failed'},
                        {'status': 'timeout'}, {'status': 'output_limit'},
                        {'observation_verified': False}, {'side_effects_uncertain': True},
                        {'error': {'code': 'failed'}}):
            with self.subTest(changes=changes):
                result = evidence()
                result.update(changes)
                self.assertIsNone(project(result))

    def test_huge_required_identity_cannot_exceed_budget(self):
        result = evidence()
        result['target'] = 'x' * 20000
        self.assertIsNone(project(result))
        self.assertIsNone(project(evidence(), full_evidence_path='x' * 20000))
        self.assertIsNone(project(evidence(), limit=16000))

    def test_deep_or_wide_findings_have_bounded_projection(self):
        result = evidence()
        nested = {}
        current = nested
        for unused in range(1000):
            current['child'] = {}
            current = current['child']
        result['findings'] = {'nested': nested, 'wide': {str(i): i for i in range(10000)}}
        projected = project(result)
        self.assertIsNotNone(projected)
        self.assertLessEqual(len(json.dumps(projected).encode()), 16384)
        self.assertEqual('retained_container',
                         projected['findings']['nested']['child']['child']['child']['child']
                         ['child']['child']['child']['child']['child']['child']['child']['child']
                         ['projection_kind'])

    def test_input_is_not_mutated(self):
        result = evidence()
        snapshot = copy.deepcopy(result)
        project(result)
        self.assertEqual(snapshot, result)

    def test_invalid_json_and_invalid_reference_decline_projection(self):
        result = evidence()
        result['findings'] = {'not_finite': float('nan')}
        self.assertIsNone(project(result))
        self.assertIsNone(project(evidence(), full_evidence_sha256='not-a-digest'))


if __name__ == '__main__':
    unittest.main()
