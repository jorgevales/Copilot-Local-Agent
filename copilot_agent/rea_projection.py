"""Bounded chat projections of successfully retained, sanitized Node evidence.

The caller persists and hashes the full evidence before using this helper. This
module never changes upstream observation status or claims sampled data is the
complete observation. It accepts sanitized JSON values only.
"""
from __future__ import annotations

import json
import re


_IDENTITY_KEYS = (
    'execution_id', 'backend', 'tool', 'operation', 'target', 'target_type',
    'target_identity_sha256', 'started_at', 'finished_at', 'execution_started',
    'side_effects_uncertain', 'status', 'observation_verified', 'coverage_complete',
    'confidence', 'exit_status', 'stdout_bytes', 'stderr_bytes',
    'degraded', 'fallback_used', 'requested_backend', 'intended_backend',
    'intended_backend_succeeded',
)
_PRIORITY = (
    'status', 'complete', 'coverage', 'coverage_complete', 'truncated',
    'total_nodes', 'total_items', 'count', 'total', 'node_count',
    'backend', 'execution_id', 'phase', 'failure_class', 'exit_status',
    'returncode', 'stdout_bytes', 'stderr_bytes', 'elapsed_seconds',
    'error', 'code', 'message', 'diagnostic',
)


def _size(value):
    return len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode('utf-8'))


class _Summary:
    def __init__(self, *, nodes, text, items, keys, depth):
        self.remaining = nodes
        self.text = text
        self.items = items
        self.keys = keys
        self.depth = depth

    @staticmethod
    def omitted(value):
        if isinstance(value, (list, dict)):
            return {'projection_kind': 'retained_container',
                    'total_items': len(value), 'see_full_evidence': True}
        return {'projection_kind': 'retained_value', 'see_full_evidence': True}

    def __call__(self, value, depth=0):
        if self.remaining <= 0 or depth > self.depth:
            return self.omitted(value)
        self.remaining -= 1
        if isinstance(value, str):
            if len(value) <= self.text:
                return value
            return {'projection_kind': 'text_excerpt', 'text': value[:self.text],
                    'original_characters': len(value), 'see_full_evidence': True}
        if value is None or type(value) in {bool, int, float}:
            return value
        if isinstance(value, list):
            sample_count = min(len(value), self.items)
            return {'projection_kind': 'array_sample', 'total_items': len(value),
                    'sample': [self(item, depth + 1) for item in value[:sample_count]],
                    'omitted_items': len(value) - sample_count,
                    'see_full_evidence': True}
        if isinstance(value, dict):
            # Inspect a bounded prefix, prioritizing coverage/count metadata.
            # No sorting/traversal of a possibly enormous tree is necessary.
            selected = []
            for key in _PRIORITY:
                if key in value:
                    selected.append(key)
            for key in value:
                if len(selected) >= self.keys:
                    break
                if key not in _PRIORITY:
                    selected.append(key)
            # Retain structural metadata before spending the shared budget on
            # potentially large child trees. Output ordering is unimportant.
            selected.sort(key=lambda key: isinstance(value[key], (dict, list)))
            result = {key: self(value[key], depth + 1) for key in selected}
            if len(selected) < len(value):
                marker = '_response_projection'
                while marker in result:
                    marker += '_'
                result[marker] = {'omitted_fields': len(value) - len(selected),
                                  'see_full_evidence': True}
            return result
        raise ValueError('REA projection accepts sanitized JSON values only')


def compact_node_result(result, *, full_evidence_path, full_evidence_sha256,
                        full_evidence_bytes, limit=1048576):
    """Return a byte-bounded projection, or ``None`` if it cannot fit safely.

    ``coverage_complete`` describes the retained upstream observation, whereas
    ``response_truncated`` describes this response. Array samples explicitly
    report their original size. The caller must not treat this as the complete
    retained Evidence object or discard the persisted full evidence.
    """
    if (type(limit) is not int or limit < 16384
            or result.get('backend') != 'node_cli'
            or result.get('status') not in {'completed', 'partial'}
            or result.get('observation_verified') is not True
            or result.get('side_effects_uncertain') or result.get('error')
            or not isinstance(result.get('findings'), dict)
            or not isinstance(full_evidence_path, str)
            or not isinstance(full_evidence_sha256, str)
            or re.fullmatch(r'[a-fA-F0-9]{64}', full_evidence_sha256) is None
            or type(full_evidence_bytes) is not int or full_evidence_bytes < 0):
        return None
    base = {key: result[key] for key in _IDENTITY_KEYS if key in result}
    base.update(
        response_truncated=True,
        evidence_path=full_evidence_path,
        evidence_sha256=full_evidence_sha256,
        full_evidence_path=full_evidence_path,
        full_evidence_sha256=full_evidence_sha256,
        full_evidence_bytes=full_evidence_bytes,
        projection_notice=(
            'This response is a bounded projection. The complete sanitized REA '
            'evidence is retained at evidence_path with the stated SHA-256. '
            'Observation status and coverage describe that full evidence; '
            'samples and omitted values are not the complete observation.'),
    )
    try:
        if _size(base) > limit:
            return None
        # Each retry is bounded independently; never recurse through the full
        # observation just to estimate how much of it could fit in chat.
        for text, items, keys, depth, nodes in (
                (512, 3, 64, 12, 4096), (256, 2, 48, 10, 2048),
                (128, 1, 32, 8, 768), (64, 1, 24, 6, 256)):
            summary = _Summary(nodes=nodes, text=text, items=items,
                               keys=keys, depth=depth)
            projected = dict(base)
            # Diagnostics and fallback identity get their own bounded summary
            # budget, so large findings cannot consume their allowance.
            for key in ('prior_backend_attempt', 'process_diagnostics',
                        'provenance', 'limitations', 'unknowns', 'redactions',
                        'fallback', 'fallback_reason'):
                if key in result:
                    diagnostic = _Summary(nodes=256, text=text, items=items,
                                          keys=keys, depth=6)
                    if key in {'limitations', 'unknowns', 'redactions'} and isinstance(result[key], list):
                        # These public fields are lists throughout the existing
                        # tool contract. Keep that shape for downstream callers.
                        values = result[key]
                        projected[key] = [diagnostic(item) for item in values[:32]]
                        if len(values) > 32:
                            projected[key].append(
                                f'{len(values) - 32} additional entries retained in full evidence.')
                    else:
                        projected[key] = diagnostic(result[key])
            projected['findings'] = summary(result['findings'])
            evidence = result.get('evidence')
            if isinstance(evidence, dict):
                # normalized_result is identical to findings and already saved
                # in full. Preserve producer identity without duplicating it.
                projected['evidence'] = {
                    key: _Summary(nodes=128, text=text, items=items,
                                  keys=keys, depth=4)(evidence[key])
                    for key in ('evidence_id', 'provider', 'operation', 'confidence')
                    if key in evidence}
                projected['evidence']['normalized_result_retained'] = True
            if _size(projected) <= limit:
                return projected
    except (ValueError, TypeError, RecursionError, OverflowError):
        return None
    return None
