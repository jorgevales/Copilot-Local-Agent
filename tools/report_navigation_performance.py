"""Summarize content-free runtime traces without inventing model/token timings."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_agent.performance import PHASES


def summarize(records):
    requests, spans, seen = defaultdict(dict), defaultdict(list), set()
    for row in records:
        identity = (row['run_id'], row['sequence'])
        if identity in seen:
            continue
        seen.add(identity)
        if row['phase'] not in PHASES:
            raise ValueError('Unknown trace phase')
        if 'duration_ms' in row:
            spans[row['phase']].append(row['duration_ms'])
        if row.get('request_id_sha256'):
            requests[(row['run_id'], row['request_id_sha256'])].setdefault(row['phase'], row['monotonic_ms'])
    intervals = {
        'observed_response_to_first_useful_ms': ('request_committed', 'first_useful_output'),
        'observed_response_to_capture_ms': ('request_committed', 'capture_complete'),
        'observed_response_to_generation_end_ms': ('request_committed', 'generation_ended'),
        'capture_tail_proxy_ms': ('generation_ended', 'capture_complete'),
        'exchange_preparation_ms': ('exchange_start', 'preparation_complete')}
    per_request = []
    for (run, request), marks in requests.items():
        row = {'run_id': run, 'request_id_sha256': request}
        for name, (start, finish) in intervals.items():
            row[name] = round(marks[finish]-marks[start], 3) if start in marks and finish in marks and marks[finish] >= marks[start] else None
        per_request.append(row)
    return {'note': 'Observed UI response includes service/network/frontend buffering. Capture tail is a proxy. '
                    'Stage durations can overlap and must not be summed as a critical path. Missing intervals are null.',
            'unique_events': len(seen), 'reasoning_tokens': None, 'inference_cost': None,
            'phase_durations': {phase: {'samples': len(values), 'median_ms': statistics.median(values),
                                      'max_ms': max(values)} for phase, values in sorted(spans.items())},
            'requests': per_request}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    result = summarize(json.loads(line) for line in options.input.read_text(encoding='utf-8').splitlines() if line.strip())
    # Create-only output preserves prior evidence; caller chooses its destination.
    with options.output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['phase_durations'], indent=2))
