import json
from pathlib import Path
import tempfile
import unittest

from copilot_agent.performance import PerformanceTrace


class PerformanceTests(unittest.TestCase):
    def test_private_transport_cannot_spill_live_content_to_disk(self):
        from copilot_agent.outbound_results import pack_outbound
        from copilot_agent.policy import PolicyError
        root = Path(tempfile.mkdtemp(prefix='private-transport-')) / 'not-created'
        message = {'session_id': 'fixture', 'request_id': 'fixture', 'kind': 'user_turn',
                   'content': 'private sentinel ' * 2000}
        with self.assertRaises(PolicyError):
            pack_outbound(json.dumps(message), [], root, allow_content_attachments=False)
        self.assertFalse(root.exists())

    def test_numeric_spans_have_private_correlations_and_monotonic_durations(self):
        ticks = iter([10, 11, 12, 13])
        root = Path(tempfile.mkdtemp(prefix='performance-fixture-'))
        trace = PerformanceTrace(root, clock=lambda: next(ticks))
        with trace.span('tool', request_id='private task identifier', call_id='customer-specific-id'):
            pass
        trace.flush()
        text = trace.path.read_text(encoding='utf-8')
        self.assertNotIn('private task identifier', text)
        self.assertNotIn('customer-specific-id', text)
        row = json.loads(text)
        self.assertEqual(1000, row['duration_ms'])
        self.assertTrue(row['ok'])
        self.assertEqual(64, len(row['request_id_sha256']))

    def test_failure_spans_and_strict_metrics(self):
        trace = PerformanceTrace()
        with self.assertRaises(RuntimeError), trace.span('tool'):
            raise RuntimeError('private exception')
        self.assertFalse(trace.records[-1]['ok'])
        self.assertNotIn('private exception', json.dumps(list(trace.records)))
        for metrics in ({'duration_ms': float('nan')}, {'bytes': 'secret'}, {'title': 'private'}):
            with self.subTest(metrics=metrics), self.assertRaises(ValueError):
                trace.record('tool', **metrics)

    def test_bounded_queue_reports_drops_and_storage_failure_is_optional(self):
        root = Path(tempfile.mkdtemp(prefix='performance-fixture-'))
        blocked = root / 'file'; blocked.write_text('fixture')
        trace = PerformanceTrace(blocked, capacity=2)
        for _ in range(4):
            trace.record('tool', actions=1)
        self.assertEqual(2, trace.dropped)
        trace.flush()
        self.assertEqual(1, trace.write_failures)
        self.assertEqual(2, len(trace.records))

    def test_disabled_trace_has_no_artifacts(self):
        trace = PerformanceTrace(enabled=False)
        with trace.span('tool'):
            pass
        self.assertFalse(trace.records)

    def test_report_deduplicates_and_marks_unobservable_intervals_unknown(self):
        from tools.report_navigation_performance import summarize
        rows = [dict(run_id='run', sequence=n, phase=phase, monotonic_ms=at, request_id_sha256='a'*64)
                for n, phase, at in [(1, 'request_committed', 10), (2, 'generation_ended', 40),
                                     (3, 'capture_complete', 45)]]
        report = summarize([*rows, rows[0]])
        self.assertEqual(3, report['unique_events'])
        self.assertEqual(35, report['requests'][0]['observed_response_to_capture_ms'])
        self.assertEqual(5, report['requests'][0]['capture_tail_proxy_ms'])
        self.assertIsNone(report['requests'][0]['observed_response_to_first_useful_ms'])
        self.assertIsNone(report['reasoning_tokens'])
