"""Content-free, bounded latency evidence. Never records prompts or website data."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import uuid

from .persistence import io_path


PHASES = frozenset({
    'exchange_start', 'prompt_assembly', 'attachment_preparation', 'upload', 'browser_exchange',
    'preparation_complete', 'send_attempted', 'request_committed', 'first_useful_output',
    'generation_ended', 'capture_complete', 'validation', 'tool', 'action',
    'screenshot', 'structure', 'visual_packaging', 'goal_observation', 'target_verification',
    'goal_slice', 'goal_total', 'task_total',
})
METRICS = frozenset({'duration_ms', 'bytes', 'characters', 'pictures', 'actions',
                     'candidates', 'matched', 'ok', 'repeated', 'dropped'})


class PerformanceTrace:
    """Small numeric-only interface; monotonic spans and hashed correlation IDs.

    Optional telemetry cannot fail an action. Writes are batched at exchange/tool
    boundaries; interrupted partial writes are deduplicable by run/sequence ID.
    """
    def __init__(self, directory=None, *, enabled=True, clock=time.monotonic, capacity=4096):
        self.enabled = enabled
        self.clock = clock
        self.started = clock()
        self.run_id = uuid.uuid4().hex
        self.path = Path(directory) / 'performance.jsonl' if directory is not None else None
        self.records = deque(maxlen=capacity)
        self.dropped = self.write_failures = self.sequence = 0
        self._lock = threading.RLock()

    def record(self, phase, *, request_id=None, call_id=None, **metrics):
        if not self.enabled:
            return
        if phase not in PHASES or set(metrics) - METRICS:
            raise ValueError('Performance telemetry accepts only known phases and numeric metrics')
        if any(type(v) not in (bool, int, float) or not math.isfinite(v) or v < 0 for v in metrics.values()):
            raise ValueError('Performance metrics must be finite nonnegative numbers')
        with self._lock:
            self.sequence += 1
            record = {'run_id': self.run_id, 'sequence': self.sequence, 'phase': phase,
                      'monotonic_ms': round((self.clock() - self.started) * 1000, 3), **metrics}
            for key, value in (('request_id', request_id), ('call_id', call_id)):
                if value is not None:
                    record[key + '_sha256'] = hashlib.sha256(str(value).encode('utf-8')).hexdigest()
            if len(self.records) == self.records.maxlen:
                self.dropped += 1
            self.records.append(record)

    @contextmanager
    def span(self, phase, *, request_id=None, call_id=None, **metrics):
        started = self.clock()
        ok = False
        try:
            yield
            ok = True
        finally:
            self.record(phase, request_id=request_id, call_id=call_id, ok=ok,
                        duration_ms=round(max(0, self.clock() - started) * 1000, 3), **metrics)

    def flush(self):
        if not self.enabled or self.path is None:
            return
        with self._lock:
            if not self.records:
                return
            payload = ''.join(json.dumps(dict(row, dropped=self.dropped), separators=(',', ':')) + '\n'
                              for row in self.records)
            try:
                target = io_path(self.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('a', encoding='utf-8') as handle:
                    handle.write(payload)
                self.records.clear()
            except OSError:
                self.write_failures += 1


NULL_TRACE = PerformanceTrace(enabled=False)


def trace(context):
    return context.get('performance_trace', NULL_TRACE)
