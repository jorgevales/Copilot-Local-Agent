"""Opt-in, public read-only website operations backed by the discovery ledger.

This is a deliberately small adapter inspired by API Anything.  It does not
copy browser sessions, store examples, execute writes, or introduce a second
orchestrator.  Two observed GETs establish parameter positions, a third unseen
input validates the operation, and later calls use the existing pinned public
HTTPS transport without a Copilot or browser round trip.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import re
import time
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from .discovery_contracts import DiscoveryError, canonical
from .discovery_http import PublicReader
from .discovery_scope import origin as checked_origin
from .discovery_store import Store, digest
from .policy import config_value

NAME = {'type': 'string', 'pattern': r'^[a-z][a-z0-9._-]{0,63}$'}
ORIGIN = {'type': 'string', 'format': 'uri', 'maxLength': 280}
VALUE = {'type': 'string', 'minLength': 1, 'maxLength': 500}
ARGS = {'type': 'object', 'additionalProperties': VALUE}
PATH_ITEM = {'anyOf': [{'type': 'string', 'minLength': 1, 'maxLength': 100},
                       {'type': 'integer', 'minimum': 0, 'maximum': 10000}]}
RESPONSE = {'type': 'object', 'properties': {
    'extract': {'type': 'array', 'items': PATH_ITEM, 'maxItems': 16},
    'pick': {'type': 'array', 'items': {'type': 'string', 'minLength': 1,
                                       'maxLength': 100}, 'maxItems': 30,
             'uniqueItems': True}}, 'required': ['extract'], 'additionalProperties': False}


def _obj(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties if required is None else required),
            'additionalProperties': False}


OPERATION_SPECS = {
    'operation.learn': (_obj({
        'origin': ORIGIN, 'name': NAME,
        'intent': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'example_url': {'type': 'string', 'format': 'uri', 'maxLength': 2048},
        'example_args': ARGS,
        'example2_url': {'type': 'string', 'format': 'uri', 'maxLength': 2048},
        'example2_args': ARGS,
        'validation_args': ARGS,
        'response': RESPONSE,
        'expected_revision': {'type': 'integer', 'minimum': 0, 'maximum': 99999},
    }), 'user_approval',
        'Learn one public read-only GET from two observed URLs, validate it with unseen inputs, and promote a sanitized versioned operation. Performs exactly three public GETs; no cookies, headers, browser, writes, or automatic fallback.'),
    'operation.list': (_obj({'origin': ORIGIN}), 'read_only',
        'List compact current public operations retained for one exact origin. No network or browser use.'),
    'operation.call': (_obj({
        'origin': ORIGIN,
        'calls': {'type': 'array', 'minItems': 1, 'maxItems': 8,
                  'items': _obj({'name': NAME, 'arguments': ARGS})},
    }), 'read_only',
        'Execute up to eight retained public GET operations locally, deduplicating identical calls and using bounded concurrency. No Copilot UI or browser round trip; failures are classified and never trigger a write or blind replay.'),
}

OPERATION_EXAMPLES = {
    'operation.learn': {'origin': 'https://example.com', 'name': 'search',
        'intent': 'Return public search results',
        'example_url': 'https://example.com/search?q=alpha',
        'example_args': {'query': 'alpha'},
        'example2_url': 'https://example.com/search?q=bravo',
        'example2_args': {'query': 'bravo'},
        'validation_args': {'query': 'charlie'},
        'response': {'extract': ['results'], 'pick': ['title', 'url']},
        'expected_revision': 0},
    'operation.list': {'origin': 'https://example.com'},
    'operation.call': {'origin': 'https://example.com',
                       'calls': [{'name': 'search', 'arguments': {'query': 'charlie'}}]},
}

_PARAM = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
_CREDENTIAL = re.compile(r'(auth|token|secret|password|passwd|cookie|session|csrf|xsrf|api.?key)', re.I)


def _enabled(context):
    return config_value(context.get('config', {}), 'operation_reuse', False) is True


def _partition(site_origin):
    return digest({'origin': checked_origin(site_origin), 'auth_partition': 'public',
                   'contract': 'operation-v1'})


def _entropy(value):
    counts = {c: value.count(c) for c in set(value)}
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())


def _safe_arguments(value, field='arguments'):
    if type(value) is not dict or not value or len(value) > 12:
        raise DiscoveryError('validation_input', '$.' + field,
                             'One to twelve explicit string parameters are required')
    result = {}
    for key, item in value.items():
        if type(key) is not str or not _PARAM.fullmatch(key) or _CREDENTIAL.search(key):
            raise DiscoveryError('validation_input', '$.' + field,
                                 'Parameter names must be generic and must not name credentials')
        if type(item) is not str or not 1 <= len(item) <= 500 or any(ord(c) < 32 for c in item):
            raise DiscoveryError('validation_input', '$.' + field + '.' + key)
        if (_CREDENTIAL.search(item) or
                len(item) >= 24 and not any(c.isspace() for c in item) and _entropy(item) >= 3.5):
            raise DiscoveryError('validation_input', '$.' + field + '.' + key,
                                 'Credential-like or high-entropy values are unavailable to public operation learning')
        result[key] = item
    return result


def _parts(url, site_origin):
    if type(url) is not str or len(url) > 2048 or url != url.strip():
        raise DiscoveryError('unsafe_url')
    try:
        parsed = urlsplit(url)
        actual = checked_origin(parsed.scheme + '://' + parsed.netloc)
    except (ValueError, UnicodeError) as error:
        raise DiscoveryError('unsafe_url') from error
    if actual != site_origin or parsed.fragment or parsed.username or parsed.password:
        raise DiscoveryError('scope_mismatch')
    path = [unquote(item) for item in parsed.path.split('/')]
    query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    literals = [item for item in path if item] + [value for _, value in query]
    if (len(query) > 30 or any(_CREDENTIAL.search(key) for key, _ in query)
            or any(_CREDENTIAL.search(item) or
                   len(item) >= 24 and not any(c.isspace() for c in item)
                   and _entropy(item) >= 3.5 for item in literals)):
        raise DiscoveryError('validation_input', '$.example_url',
                             'Credential-like, high-entropy, or excessive URL fields are unavailable')
    return path, query


def _infer(args):
    site_origin = checked_origin(args['origin'])
    first, second = (_safe_arguments(args['example_args'], 'example_args'),
                     _safe_arguments(args['example2_args'], 'example2_args'))
    validation = _safe_arguments(args['validation_args'], 'validation_args')
    if set(first) != set(second) or set(first) != set(validation):
        raise DiscoveryError('validation_input', '$.validation_args',
                             'Both examples and the unseen validation input need the same parameter names')
    if any(first[key] == second[key] or validation[key] in {first[key], second[key]} for key in first):
        raise DiscoveryError('validation_input', '$.validation_args',
                             'Each parameter needs two distinct examples and a third unseen value')
    path1, query1 = _parts(args['example_url'], site_origin)
    path2, query2 = _parts(args['example2_url'], site_origin)
    if len(path1) != len(path2) or [k for k, _ in query1] != [k for k, _ in query2]:
        raise DiscoveryError('ambiguous_target', '$.example2_url',
                             'Examples do not describe one stable request shape')
    hits = {key: 0 for key in first}

    def slot(a, b):
        matches = [key for key in first if a == first[key] and b == second[key]]
        if len(matches) > 1:
            raise DiscoveryError('ambiguous_target')
        if matches:
            hits[matches[0]] += 1
            return {'param': matches[0]}
        if a != b:
            raise DiscoveryError('ambiguous_target', '$.example2_url',
                                 'A non-parameter request component changed between examples')
        return {'literal': a}

    path = [slot(a, b) for a, b in zip(path1, path2)]
    query = [{'key': k1, 'value': slot(v1, v2)}
             for (k1, v1), (k2, v2) in zip(query1, query2) if k1 == k2]
    if any(not count for count in hits.values()):
        raise DiscoveryError('validation_input', '$.example_args',
                             'Every parameter must occupy a whole path segment or query value')
    return site_origin, first, second, validation, {'path': path, 'query': query}


def _materialize(site_origin, template, arguments):
    values = _safe_arguments(arguments)
    required = {item['param'] for item in template['path'] if 'param' in item}
    required.update(item['value']['param'] for item in template['query']
                    if 'param' in item['value'])
    if set(values) != required:
        raise DiscoveryError('validation_input', '$.arguments',
                             'Arguments must exactly match the learned parameter set')

    def value(item):
        return values[item['param']] if 'param' in item else item['literal']

    route = '/'.join(quote(value(item), safe='') for item in template['path']) or '/'
    if not route.startswith('/'):
        route = '/' + route
    query = urlencode([(item['key'], value(item['value'])) for item in template['query']],
                      doseq=True)
    return site_origin + route + (('?' + query) if query else '')


@dataclass(frozen=True)
class _URL:
    url: str
    origin: str
    host: str
    path: str


class _OperationScope:
    redirect_limit = 3

    def __init__(self, site_origin, query_keys):
        self.site_origin = checked_origin(site_origin)
        self.query_keys = tuple(query_keys)

    def resolve(self, value):
        parsed = urlsplit(value)
        actual = checked_origin(parsed.scheme + '://' + parsed.netloc)
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (actual != self.site_origin or parsed.fragment or parsed.username or parsed.password
                or tuple(key for key, _ in query) != self.query_keys):
            raise DiscoveryError('scope_mismatch')
        route = parsed.path or '/'
        if any(part in {'.', '..'} for part in route.split('/')):
            raise DiscoveryError('unsafe_path')
        return _URL(value, actual, parsed.hostname, route + (('?' + parsed.query) if parsed.query else ''))


def _graph(site_origin, query_keys):
    budgets = {'run_seconds': 30, 'requests': 8, 'bytes': 2 * 1024 * 1024,
               'per_origin_rps': 4, 'per_origin_concurrency': 4}
    manifest = {'request_id': 'operation-' + uuid.uuid4().hex,
                'budgets': budgets, 'tasks': [],
                'scope': {'origins': [site_origin]}}
    return SimpleNamespace(manifest=manifest, digest=digest(manifest)), budgets


async def _request(context, site_origin, url, query_keys):
    graph, budgets = _graph(site_origin, query_keys)
    store, run = Store(context, persistent=False), 'r' + uuid.uuid4().hex
    store.create_run(run, graph, _partition(site_origin), 'operation', time.time())
    scope = _OperationScope(site_origin, query_keys)
    reader = PublicReader(scope, store, run, budgets,
                          lambda: bool(getattr(context.get('cancel_event'), 'is_set', lambda: False)()),
                          content_types={'application/json'})
    try:
        return await reader.fetch(url, time.time() + 25)
    finally:
        await reader.close()
        store.close()


def _invalid_constant(value):
    raise ValueError(value)


def _decode(response):
    try:
        text = response.body.decode('utf-8', errors='strict')
        return json.loads(text, object_pairs_hook=_unique_pairs,
                          parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise DiscoveryError('invalid_json', '$.response',
                             'The learned operation did not return strict UTF-8 JSON') from error


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise DiscoveryError('duplicate_key')
        result[key] = value
    return result


def _extract(value, response):
    current = value
    for step in response.get('extract', []):
        try:
            if type(step) is int and type(current) is list:
                current = current[step]
            elif type(step) is str and type(current) is dict:
                current = current[step]
            else:
                raise KeyError(step)
        except (KeyError, IndexError) as error:
            raise DiscoveryError('unexpected_transition', '$.response.extract',
                                 'The learned extraction path is missing') from error
    pick = response.get('pick') or []
    if pick:
        rows = current if type(current) is list else [current]
        if any(type(row) is not dict for row in rows):
            raise DiscoveryError('unexpected_transition', '$.response.pick')
        current = [{key: row[key] for key in pick if key in row} for row in rows]
        if any(not row for row in current):
            raise DiscoveryError('unexpected_transition', '$.response.pick')
    return current


def _shape(value, depth=0):
    if depth >= 3:
        return type(value).__name__
    if type(value) is list:
        shapes = [_shape(item, depth + 1) for item in value[:50]]
        if shapes and any(item != shapes[0] for item in shapes[1:]):
            raise DiscoveryError('unexpected_transition', '$.response',
                                 'Operation arrays must have one stable item shape')
        return {'type': 'list', 'item': shapes[0] if shapes else 'empty'}
    if type(value) is dict:
        return {'type': 'object', 'fields': {key: _shape(item, depth + 1)
                                             for key, item in sorted(value.items())[:50]}}
    return type(value).__name__


def _compact(value, limit=9000):
    if len(canonical(value)) <= limit:
        if type(value) is list and len(value) > 1 and all(type(row) is dict for row in value):
            columns = sorted({key for row in value for key in row})
            return {'columns': columns, 'rows': [[row.get(key) for key in columns] for row in value]}
        return value
    if type(value) is list:
        kept = []
        for row in value:
            if len(canonical(kept + [row])) > limit:
                break
            kept.append(row)
        return {'items': kept, 'truncated': True, 'omitted': len(value) - len(kept)}
    raise DiscoveryError('resource_limit', '$.response', 'Operation result exceeds the bounded output limit')


def validate_operation(name, args, context=None):
    if name not in OPERATION_SPECS:
        raise DiscoveryError('operation_mapping')
    if context is not None and not _enabled(context):
        raise DiscoveryError('feature_disabled', '$',
                             'Public operation reuse is disabled by configuration')
    site_origin = checked_origin(args['origin'])
    if name == 'operation.learn':
        _infer(args)
        if args['expected_revision'] < 0:
            raise DiscoveryError('stale_knowledge_revision')
    elif name == 'operation.call':
        for call in args['calls']:
            _safe_arguments(call['arguments'])
    return site_origin


async def _learn(args, context):
    site_origin, first, second, validation, template = _infer(args)
    partition = _partition(site_origin)
    store = Store(context, persistent=True)
    try:
        if store.operation_revision(partition, args['name']) != args['expected_revision']:
            raise DiscoveryError('stale_knowledge_revision')
    finally:
        store.close()
    query_keys = [item['key'] for item in template['query']]
    shapes = []
    started = time.monotonic()
    for values in (first, second, validation):
        url = _materialize(site_origin, template, values)
        response = await _request(context, site_origin, url, query_keys)
        shapes.append(_shape(_extract(_decode(response), args['response'])))
    if shapes[0] != shapes[1] or shapes[0] != shapes[2]:
        raise DiscoveryError('unexpected_transition', '$.response',
                             'Example and unseen validation outputs do not share one stable shape')
    store = Store(context, persistent=True)
    try:
        graph_partition = None
        graph_revision = 0
        try:
            from .discovery_knowledge import namespace
            graph_partition = namespace(context, site_origin)
            graph_revision = store.knowledge_revision(graph_partition)
        except (DiscoveryError, ValueError, RuntimeError):
            pass
        payload = {'version': '1.0', 'kind': 'public_web_operation',
                   'name': args['name'], 'intent': args['intent'], 'origin': site_origin,
                   'revision': args['expected_revision'] + 1,
                   'request': {'method': 'GET', 'template': template,
                               'parameters': sorted(first)},
                   'response': args['response'], 'shape': shapes[2],
                   'knowledge_link': {'partition': graph_partition,
                                      'revision': graph_revision},
                   'provenance': {'source': 'two_observed_urls_plus_unseen_validation',
                                  'external_pattern': 'API Anything capture-learn-validate; reimplemented locally',
                                  'examples_retained': False},
                   'safety': {'public_only': True, 'read_only': True,
                              'credentials_retained': False, 'automatic_replay': False}}
        store.save_operation(partition, args['name'], args['expected_revision'], payload)
        stored = store.operation(partition, args['name'])
        if stored is None or stored['hash'] != digest(payload):
            raise DiscoveryError('knowledge_integrity')
    finally:
        store.close()
    return {'status': 'validated_and_promoted', 'name': args['name'],
            'revision': payload['revision'], 'operation_sha256': digest(payload),
            'parameters': sorted(first), 'output_shape': shapes[2],
            'validation': {'examples': 2, 'unseen_inputs': 1, 'http_calls': 3,
                           'elapsed_ms': round((time.monotonic() - started) * 1000, 1)},
            'storage': 'existing local discovery ledger; prior versions retained',
            'copilot_ui_round_trips': 0, 'browser_launches': 0}


def _list(args, context):
    partition = _partition(args['origin'])
    store = Store(context, persistent=True)
    try:
        rows = store.operations(partition)
        return {'origin': checked_origin(args['origin']), 'operations': [
            {'name': row['name'], 'revision': row['revision'], 'status': row['status'],
             'intent': row['value']['intent'],
             'parameters': row['value']['request']['parameters'],
             'last_success': row['last_success'], 'failure_count': row['failure_count'],
             'last_failure_class': row['last_failure_class']}
            for row in rows]}
    finally:
        store.close()


def _failure_class(error):
    code = error.code if isinstance(error, DiscoveryError) else 'error'
    if code == 'authentication_required':
        return 'auth'
    if code == 'access_denied':
        return 'blocked'
    if code == 'rate_limited':
        return 'rate'
    if code in {'route_missing', 'unexpected_transition', 'invalid_json', 'unsupported_content'}:
        return 'drift'
    if code in {'validation_input', 'unsafe_url', 'scope_mismatch'}:
        return 'input'
    return 'error'


async def _one_call(site_origin, call, context):
    partition = _partition(site_origin)
    store = Store(context, persistent=True)
    try:
        row = store.operation(partition, call['name'])
    finally:
        store.close()
    if row is None:
        raise DiscoveryError('request_unavailable', '$.calls.name', 'No retained operation has this name')
    payload = row['value']
    if row['status'] == 'degraded':
        raise DiscoveryError('knowledge_stale', '$.calls.name',
                             'The retained operation is degraded; collect fresh browser evidence and learn a new version')
    url = _materialize(site_origin, payload['request']['template'], call['arguments'])
    key = digest({'partition': partition, 'name': call['name'], 'revision': row['revision'],
                  'arguments': call['arguments']})
    cache = context.setdefault('operation_cache', {})
    cached = cache.get(key)
    if cached and time.monotonic() - cached['at'] <= 60:
        store = Store(context, persistent=True)
        try:
            store.record_operation_outcome(partition, call['name'], row['revision'], 'cache_hit')
        finally:
            store.close()
        return dict(cached['result'], cache_hit=True, http_calls=0)
    started = time.monotonic()
    query_keys = [item['key'] for item in payload['request']['template']['query']]
    try:
        response = await _request(context, site_origin, url, query_keys)
        data = _extract(_decode(response), payload['response'])
        if _shape(data) != payload['shape']:
            raise DiscoveryError('unexpected_transition', '$.response',
                                 'Response shape differs from the promoted operation')
        result = {'name': call['name'], 'revision': row['revision'], 'class': 'ok',
                  'data': _compact(data), 'transport': 'direct_http',
                  'elapsed_ms': round((time.monotonic() - started) * 1000, 1),
                  'http_calls': 1, 'browser_launches': 0,
                  'copilot_ui_round_trips': 0, 'cache_hit': False}
        store = Store(context, persistent=True)
        try:
            store.record_operation_outcome(partition, call['name'], row['revision'], 'success')
        finally:
            store.close()
        cache[key] = {'at': time.monotonic(), 'result': result}
        return result
    except DiscoveryError as error:
        classification = _failure_class(error)
        store = Store(context, persistent=True)
        try:
            store.record_operation_outcome(partition, call['name'], row['revision'],
                                           'failure', classification)
        finally:
            store.close()
        return {'name': call['name'], 'revision': row['revision'], 'class': classification,
                'ok': False, 'reason': error.message, 'code': error.code,
                'next_action': ('collect fresh browser evidence and learn a new version'
                                if classification == 'drift' else
                                'stop; user authentication is required' if classification == 'auth' else
                                'stop; do not retry while rate limited' if classification == 'rate' else
                                'stop and inspect the classified failure'),
                'http_calls': 1, 'browser_launches': 0,
                'copilot_ui_round_trips': 0, 'automatic_retry': False}


async def _call(args, context):
    site_origin = checked_origin(args['origin'])
    unique, positions = {}, []
    for call in args['calls']:
        key = digest(call)
        positions.append(key)
        unique.setdefault(key, call)
    semaphore = asyncio.Semaphore(4)

    async def run(key, call):
        async with semaphore:
            try:
                return key, await _one_call(site_origin, call, context)
            except DiscoveryError as error:
                return key, {'name': call['name'], 'ok': False,
                             'class': _failure_class(error), 'code': error.code,
                             'reason': error.message, 'automatic_retry': False,
                             'http_calls': 0, 'browser_launches': 0,
                             'copilot_ui_round_trips': 0}

    results = dict(await asyncio.gather(*(run(key, call) for key, call in unique.items())))
    ordered = [results[key] for key in positions]
    return {'status': 'completed' if all(item.get('class') == 'ok' for item in ordered)
            else 'completed_with_failures', 'results': ordered,
            'metrics': {'requested_calls': len(positions), 'unique_calls': len(unique),
                        'duplicates_avoided': len(positions) - len(unique),
                        'http_calls': sum(item.get('http_calls', 0) for item in results.values()),
                        'browser_launches': 0, 'copilot_ui_round_trips': 0}}


async def execute_operation(name, args, context):
    validate_operation(name, args, context)
    if name == 'operation.learn':
        return await _learn(args, context)
    if name == 'operation.list':
        return _list(args, context)
    if name == 'operation.call':
        return await _call(args, context)
    raise DiscoveryError('operation_mapping')
