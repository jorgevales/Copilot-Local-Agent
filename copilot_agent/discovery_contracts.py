"""Strict package contracts and a capability-checked, immutable graph compiler."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

MAX_INPUT_BYTES = 256 * 1024
MAX_DEPTH = 32
KINDS = {
    'discovery_manifest': 'discovery-manifest', 'discovery_result': 'discovery-result',
    'website_knowledge': 'website-knowledge', 'navigation_intent': 'navigation-intent',
    'navigation_plan': 'navigation-plan', 'replanning_checkpoint': 'replanning-checkpoint',
    'graph_amendment': 'graph-amendment',
}
MAPPING = {
    'bootstrap': ('bootstrap', 'scope_evidence'), 'http': ('fetch', 'page_evidence'),
    'browser': ('observe_navigation', 'page_evidence'),
    'network': ('observe_network', 'network_evidence'),
    'structure': ('map_structure', 'structure_evidence'),
    'validate': ('validate_evidence', 'validated_evidence'),
    'aggregate': ('aggregate_evidence', 'result'),
}
INSTALLED_WORKERS = frozenset({'bootstrap', 'http', 'structure', 'validate', 'aggregate'})

DISCOVERY_ERROR_CODES = (
    'aggregate_input', 'aggregate_sink', 'ambiguous_response', 'ambiguous_target',
    'approval_required', 'attempt_limit', 'authentication_required', 'authentication_unavailable',
    'body_limit', 'bootstrap_ancestry', 'bootstrap_seed_mismatch', 'budget_nesting',
    'cancelled', 'capability_unavailable', 'capture_unavailable', 'clock_anomaly',
    'compressed_content_unavailable', 'connection_mismatch', 'consequential_path', 'dependency_cycle',
    'dependency_reference', 'duplicate_key', 'duplicate_origin', 'duplicate_task',
    'encoding_unavailable', 'evidence_integrity', 'evidence_reference', 'evidence_unavailable',
    'expansion_worker', 'feature_disabled', 'finalisation_reserve', 'graph_roots',
    'header_limit', 'incomplete_response', 'input_limit', 'invalid_chunk',
    'invalid_contract', 'invalid_json', 'invalid_redirect', 'invalid_response',
    'invalid_transition', 'invalid_utf8', 'knowledge_capability_unavailable', 'knowledge_confidence',
    'knowledge_integrity', 'knowledge_invalidated', 'knowledge_limit', 'knowledge_missing',
    'knowledge_partition', 'knowledge_reference', 'knowledge_stale', 'knowledge_timestamp',
    'knowledge_unusable', 'local_ceiling', 'local_url_input', 'local_worker_approval',
    'missing_url', 'navigation_budget', 'navigation_chain', 'navigation_revision',
    'navigation_serial_only', 'navigation_unreachable', 'navigation_verification', 'nesting_limit',
    'operation_mapping', 'parallelism_disabled', 'persistent_evidence_required', 'privacy_path',
    'private_destination', 'query_capability_unavailable', 'rate_limited', 'recovery_policy',
    'redirect_cycle', 'redirect_limit', 'replanning_unavailable', 'request_unavailable',
    'resource_limit', 'route_missing', 'route_reference_unavailable', 'route_trap',
    'run_unavailable', 'runtime_limit', 'save_consent_required', 'scope_mismatch',
    'server_error', 'stale_commit', 'stale_knowledge_revision', 'stale_lease',
    'stale_request', 'stale_task_revision', 'store_unavailable', 'store_version',
    'synced_store_unavailable', 'task_limit', 'testing_only', 'timeout',
    'transport_error', 'unexpected_transition', 'unsafe_origin', 'unsafe_path',
    'unsafe_url', 'unsupported_content', 'unsupported_kind', 'unsupported_navigation_check',
    'unsupported_protocol', 'unsupported_status', 'unsupported_trailer', 'unsupported_transfer',
    'unverified_knowledge', 'validation_input', 'write_unavailable',
)


class DiscoveryError(ValueError):
    def __init__(self, code, field='$', message='The local discovery contract was rejected'):
        self.code, self.field, self.message = code, field, message
        super().__init__(message)

    def rejection(self, request_id=None, executed=False):
        return {'status': 'failed' if executed else 'rejected', 'code': self.code, 'field': self.field,
                'message': self.message, 'request_id': request_id, 'executed': executed}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise DiscoveryError('duplicate_key', '$', 'Duplicate JSON keys are not accepted')
        result[key] = value
    return result


def bounded_shape(value, depth=0):
    if depth > MAX_DEPTH:
        raise DiscoveryError('nesting_limit')
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise DiscoveryError('invalid_json')
        if any(any(0xD800 <= ord(c) <= 0xDFFF for c in key) for key in value):
            raise DiscoveryError('invalid_utf8')
        for child in value.values():
            bounded_shape(child, depth + 1)
    elif type(value) is list:
        for child in value:
            bounded_shape(child, depth + 1)
    elif type(value) is str and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise DiscoveryError('invalid_utf8')
    elif type(value) not in (str, int, float, bool, type(None)):
        raise DiscoveryError('invalid_json')
    elif type(value) is float and not math.isfinite(value):
        raise DiscoveryError('invalid_json')


def parse_contract(raw):
    if type(raw) is not str:
        raise DiscoveryError('input_limit')
    try:
        if len(raw.encode('utf-8')) > MAX_INPUT_BYTES:
            raise DiscoveryError('input_limit')
    except UnicodeError as error:
        raise DiscoveryError('invalid_utf8') from error
    # Pre-scan depth before the JSON decoder allocates a deeply nested tree.
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > MAX_DEPTH:
                raise DiscoveryError('nesting_limit')
        elif char in ']}':
            depth -= 1
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(DiscoveryError('invalid_json')))
    except (ValueError, RecursionError, UnicodeError) as error:
        if isinstance(error, DiscoveryError):
            raise
        raise DiscoveryError('invalid_json') from error
    bounded_shape(value)
    return value


@lru_cache(maxsize=7)
def _schema(kind):
    if kind not in KINDS:
        raise DiscoveryError('unsupported_kind')
    path = Path(__file__).resolve().parents[1] / 'schemas' / 'discovery' / (KINDS[kind] + '.schema.json')
    return parse_contract(path.read_text(encoding='utf-8'))


def schema(kind):
    return deepcopy(_schema(kind))


def format_valid(value, name):
    if name == 'uri':
        try:
            parsed = urlsplit(value)
            return (bool(parsed.scheme) and not any(ord(c) < 33 or c == '\\' for c in value)
                    and (' ' not in value) and (parsed.scheme not in ('http', 'https') or bool(parsed.netloc)))
        except (ValueError, TypeError):
            return False
    if name == 'date-time':
        if not re.fullmatch(r'\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)', value):
            return False
        try:
            parsed = datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
            return parsed.tzinfo is not None
        except ValueError:
            return False
    return False


def validate_contract(value, kind, request_id=None):
    bounded_shape(value)
    if len(canonical(value).encode('utf-8')) > MAX_INPUT_BYTES:
        raise DiscoveryError('input_limit')
    from .protocol import validate_schema
    errors = validate_schema(value, _schema(kind))
    if errors:
        # Schema paths may include attacker-chosen property names. Do not echo them.
        raise DiscoveryError('invalid_contract', '$', 'Use the exact installed kind/version schema; unknown fields and invalid formats fail')
    if request_id is not None and value.get('request_id') != request_id:
        raise DiscoveryError('stale_request', '$.request_id', 'Contract identity must match the current locally supplied request')
    return deepcopy(value)


def validate_budgets(b):
    if not b['task_seconds'] <= b['branch_seconds'] <= b['run_seconds']:
        raise DiscoveryError('budget_nesting', '$.budgets')
    if b['per_origin_concurrency'] > b['concurrency'] or b['browser_contexts'] > b['concurrency']:
        raise DiscoveryError('budget_nesting', '$.budgets')
    if b['run_seconds'] < 3:
        raise DiscoveryError('finalisation_reserve', '$.budgets.run_seconds', 'At least three seconds are required including local finalisation')
    if b['pages'] > 100 or b['tasks'] > 200 or b['requests'] > 500 or b['bytes'] > 20 * 1024 * 1024:
        raise DiscoveryError('local_ceiling', '$.budgets', 'Testing v1 caps are 100 pages, 200 tasks, 500 requests and 20 MiB')
    if b['concurrency'] > 4 or b['per_origin_concurrency'] > 2 or b['attempts'] > 3:
        raise DiscoveryError('local_ceiling', '$.budgets', 'Testing v1 permits at most four workers, two per origin and three attempts')
    if b['browser_contexts'] or b['browser_restarts'] or b['replans']:
        raise DiscoveryError('capability_unavailable', '$.budgets', 'Browser/authentication and autonomous replanning are unavailable in this adapter')


@dataclass(frozen=True)
class CompiledGraph:
    manifest_json: str
    order: tuple[str, ...]
    ancestors: tuple[tuple[str, tuple[str, ...]], ...]
    digest: str

    @property
    def manifest(self):
        return json.loads(self.manifest_json)


def compile_manifest(value, request_id=None):
    import hashlib
    from .discovery_scope import Scope
    m = validate_contract(value, 'discovery_manifest', request_id)
    validate_budgets(m['budgets'])
    scope = Scope(m['scope'])
    if m['authentication'] != {'mode': 'public', 'context_ref': None}:
        raise DiscoveryError('authentication_unavailable', '$.authentication', 'Only credential-free public HTTP is installed; session references cannot grant access')
    if not set(m['permitted_workers']) <= INSTALLED_WORKERS:
        raise DiscoveryError('capability_unavailable', '$.permitted_workers', 'Autonomous browser and passive network workers are not installed')
    if 'network' in m['evidence_requirements']['required_types']:
        raise DiscoveryError('capability_unavailable', '$.evidence_requirements.required_types', 'Required browser-network evidence cannot be produced by the installed public static workers')
    if m['evidence_requirements']['retain_screenshots']:
        raise DiscoveryError('capture_unavailable', '$.evidence_requirements.retain_screenshots')
    if m['replanning_triggers']:
        raise DiscoveryError('replanning_unavailable', '$.replanning_triggers')
    for url in m['seed_urls']:
        scope.resolve(url)
    tasks = {task['id']: task for task in m['tasks']}
    if len(tasks) != len(m['tasks']):
        raise DiscoveryError('duplicate_task', '$.tasks')
    if len(tasks) > m['budgets']['tasks']:
        raise DiscoveryError('task_limit', '$.tasks')
    boot = [t for t in tasks.values() if t['worker'] == 'bootstrap']
    aggregates = [t for t in tasks.values() if t['worker'] == 'aggregate']
    if len(boot) != 1 or len(aggregates) != 1:
        raise DiscoveryError('graph_roots', '$.tasks', 'Exactly one bootstrap and one aggregate are required')
    for t in tasks.values():
        worker = t['worker']
        if worker not in m['permitted_workers'] or worker not in INSTALLED_WORKERS:
            raise DiscoveryError('capability_unavailable', '$.tasks.worker')
        if (t['operation'], t['output_type']) != MAPPING[worker]:
            raise DiscoveryError('operation_mapping', '$.tasks.operation')
        if t['auth_requirement'] != 'public':
            raise DiscoveryError('authentication_unavailable', '$.tasks.auth_requirement')
        if (t['timeout_seconds'] > m['budgets']['task_seconds']
                or t['max_attempts'] > m['budgets']['attempts']):
            raise DiscoveryError('budget_nesting', '$.tasks')
        if worker in {'bootstrap', 'http'} and t['approval_requirement'] != 'existing_read_approval':
            raise DiscoveryError('approval_required', '$.tasks.approval_requirement', 'Installed reads require the exact current manifest read grant; per-action task grants and approval-free remote work are unavailable')
        if worker not in {'bootstrap', 'http'} and t['approval_requirement'] != 'none':
            raise DiscoveryError('local_worker_approval', '$.tasks.approval_requirement')
        if t['expand_urls'] and worker != 'http':
            raise DiscoveryError('expansion_worker', '$.tasks.expand_urls')
        if t['recovery_policy'] == 'observe_only_v1':
            raise DiscoveryError('recovery_policy', '$.tasks.recovery_policy')
        if t['inputs']['route_ids']:
            raise DiscoveryError('route_reference_unavailable', '$.tasks.inputs.route_ids')
        if worker not in {'bootstrap', 'http'} and t['inputs']['urls']:
            raise DiscoveryError('local_url_input', '$.tasks.inputs.urls')
        if worker == 'bootstrap' and t['inputs']['urls'] and set(t['inputs']['urls']) != set(m['seed_urls']):
            raise DiscoveryError('bootstrap_seed_mismatch', '$.tasks.inputs.urls')
        if worker == 'http' and not t['inputs']['urls']:
            raise DiscoveryError('missing_url', '$.tasks.inputs.urls')
        for url in t['inputs']['urls']:
            scope.resolve(url)
        parents = [d['task_id'] for d in t['depends_on']]
        if len(parents) != len(set(parents)) or t['id'] in parents or not set(parents) <= set(tasks):
            raise DiscoveryError('dependency_reference', '$.tasks.depends_on')
        if worker == 'bootstrap' and parents or worker != 'bootstrap' and not parents:
            raise DiscoveryError('graph_roots', '$.tasks.depends_on')
    remaining, order, ancestors = set(tasks), [], {}
    while remaining:
        ready = sorted(i for i in remaining if all(d['task_id'] in ancestors for d in tasks[i]['depends_on']))
        if not ready:
            raise DiscoveryError('dependency_cycle', '$.tasks.depends_on')
        for i in ready:
            parents = {d['task_id'] for d in tasks[i]['depends_on']}
            ancestors[i] = parents | set().union(*(ancestors[p] for p in parents))
            if i != boot[0]['id'] and boot[0]['id'] not in ancestors[i]:
                raise DiscoveryError('bootstrap_ancestry', '$.tasks.depends_on')
            remaining.remove(i)
            order.append(i)
    consumers = {d['task_id'] for t in tasks.values() for d in t['depends_on']}
    if set(tasks) - consumers != {aggregates[0]['id']}:
        raise DiscoveryError('aggregate_sink', '$.tasks', 'Every branch must reach the single aggregate sink')
    allowed_inputs = {
        'bootstrap': set(), 'http': {'scope_evidence', 'page_evidence'},
        'structure': {'scope_evidence', 'page_evidence', 'network_evidence'},
        'validate': {'scope_evidence', 'page_evidence', 'network_evidence', 'structure_evidence'},
        'aggregate': {'validated_evidence'},
    }
    for t in tasks.values():
        refs = t['inputs']['evidence_from']
        if any(ref not in ancestors[t['id']] or tasks[ref]['output_type'] not in allowed_inputs[t['worker']] for ref in refs):
            raise DiscoveryError('evidence_reference', '$.tasks.inputs.evidence_from')
        if t['worker'] == 'structure' and not refs:
            raise DiscoveryError('evidence_reference', '$.tasks.inputs.evidence_from', 'Structure requires at least one ancestor scope/page producer')
        if t['worker'] == 'validate' and not any(tasks[r]['worker'] == 'structure' for r in refs):
            raise DiscoveryError('validation_input', '$.tasks.inputs.evidence_from')
        if t['worker'] == 'aggregate' and not any(tasks[r]['worker'] == 'validate' for r in refs):
            raise DiscoveryError('aggregate_input', '$.tasks.inputs.evidence_from')
    encoded = canonical(m)
    return CompiledGraph(encoded, tuple(order), tuple((i, tuple(sorted(ancestors[i]))) for i in order),
                         hashlib.sha256(encoded.encode()).hexdigest())
