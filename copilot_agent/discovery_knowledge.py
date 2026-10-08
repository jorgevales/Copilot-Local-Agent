"""Bound evidence/CAS knowledge and locally compiled static read-only intents.

These tools never navigate a browser, click/fill/submit a control or obtain auth.
Public GET verification is not a claim of an observed rendered transition.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import heapq
import json
import math
import time
from urllib.parse import urlsplit

from .discovery_contracts import (DiscoveryError, canonical, schema, validate_budgets,
                                  validate_contract)
from .discovery_engine import (Engine, cancelled, correlation, enabled, input_object,
                               testing_gate)
from .discovery_scope import Scope, origin
from .discovery_store import Store, digest
from .site_knowledge import _scope, _safe_label, PURPOSES

ID = {'type': 'string', 'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,63}$'}
ORIGIN = {'type': 'string', 'format': 'uri', 'maxLength': 280}
REVISION = {'type': 'integer', 'minimum': 0, 'maximum': 99999}
KNOWLEDGE_SPECS = {
    'discovery.knowledge_save': (input_object({'run_id': ID, 'origin': ORIGIN, 'expected_revision': REVISION}),
        'user_approval', 'Testing-only: separately consent to save locally sanitised evidence-backed navigation candidates from one current approved run. Fresh site_knowledge.bind required. CAS revision; no model supplied knowledge or automatic trust.'),
    'discovery.knowledge_lookup': (input_object({'origin': ORIGIN}), 'read_only',
        'Testing-only: bounded fresh scoped knowledge summary from the separately consented local v1 namespace; binding and knowledge_reuse flag required. Knowledge never authorises a browser action.'),
    'discovery.knowledge_invalidate': (input_object({'origin': ORIGIN, 'expected_revision': REVISION}),
        'user_approval', 'Testing-only: invalidate the exact selected local v1 knowledge namespace/revision after local review; existing website memory is separate and unchanged.'),
    'navigation.intent': (input_object({'intent': schema('navigation_intent')}), 'user_approval',
        'Testing-only: compile read intent locally against bound pinned fresh trusted public knowledge; execute bounded GET fingerprint verification, not browser interaction. Nested request_id is d + current envelope request_id. Unknown/stale maps require a separately approved discovery run.'),
}

STOP_ON = ['scope_mismatch', 'approval_missing', 'ambiguous_control', 'unexpected_transition',
           'auth_expired', 'budget_exhausted', 'cancelled']
VALIDATIONS = ['origin', 'scope', 'fingerprint', 'controls', 'authentication', 'approval', 'target']


def namespace(context, site_origin):
    checked = origin(site_origin)
    scope = _scope('site_knowledge.retrieve', {'origin': checked}, context)
    return digest({'binding': scope, 'auth_partition': 'public', 'contract': 'discovery-v1'})


def stamp(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError()
        return date.timestamp()
    except (ValueError, TypeError, AttributeError) as error:
        raise DiscoveryError('knowledge_timestamp') from error


def semantics(value, scope, now=None):
    now = time.time() if now is None else now
    k = validate_contract(value, 'website_knowledge')
    if k['origin'] not in scope.origins or k['scope_identity'] != scope.identity or k['auth_partition'] != 'public':
        raise DiscoveryError('knowledge_partition')
    if not stamp(k['first_seen']) <= stamp(k['last_verified']) <= now + 30:
        raise DiscoveryError('knowledge_timestamp')
    ids = {}
    for field in ('routes', 'templates', 'actions', 'forms', 'evidence'):
        ids[field] = {entry['id'] for entry in k[field]}
        if len(ids[field]) != len(k[field]):
            raise DiscoveryError('knowledge_reference')
    evidence = {e['id']: e for e in k['evidence']}
    templates = {t['id']: t for t in k['templates']}
    for e in k['evidence']:
        scope.resolve(e['source_url'])
        if not e['artifact_ref'].startswith('sha256:') or e['artifact_ref'][7:] != e['content_hash']:
            raise DiscoveryError('knowledge_integrity')
        if stamp(e['observed_at']) > now + 30:
            raise DiscoveryError('knowledge_timestamp')
    for r in k['routes']:
        scope.resolve(r['url'])
        _safe_label(r['purpose'])
        if (r['purpose'] not in PURPOSES or r['auth_requirement'] != 'public'
                or r['template_id'] not in ids['templates'] or not set(r['evidence_ids']) <= ids['evidence']):
            raise DiscoveryError('knowledge_reference')
        if not stamp(k['first_seen']) <= stamp(r['first_seen']) <= stamp(r['last_verified']) <= stamp(k['last_verified']) <= now + 30:
            raise DiscoveryError('knowledge_timestamp')
        refs = [evidence[i] for i in r['evidence_ids']]
        if any(e['type'] != 'page' or e['source_url'] != r['url'] or e['structural_fingerprint'] != r['fingerprint'] for e in refs):
            raise DiscoveryError('knowledge_integrity')
        # IDs are locally generated, independent run provenance is separately
        # checked against evidence rows at save/lookup, never inferred from labels.
        if r['status'] == 'trusted' and len(refs) < 2:
            raise DiscoveryError('unverified_knowledge')
        if templates[r['template_id']]['fingerprint'] != r['fingerprint']:
            raise DiscoveryError('knowledge_integrity')
    for t in k['templates']:
        if not set(t['evidence_ids']) <= ids['evidence']:
            raise DiscoveryError('knowledge_reference')
    for a in k['actions']:
        if (a['from_route'] not in ids['routes'] or a['to_route'] not in ids['routes']
                or not set(a['evidence_ids']) <= ids['evidence'] or a['kind'] != 'navigate'
                or a['effect'] != 'read' or a['approval'] != 'existing_read_approval'
                or a['locators'] or a['preconditions'] != ['verified_static_link']
                or a['expected_transition'] != a['to_route']):
            raise DiscoveryError('unsupported_navigation_check')
    if k['forms'] or k['overlays'] or k['api_patterns'] or k['recoveries']:
        raise DiscoveryError('knowledge_capability_unavailable')
    for b in k['boundaries']:
        if b['route_id'] not in ids['routes'] or not set(b['evidence_ids']) <= ids['evidence']:
            raise DiscoveryError('knowledge_reference')
    if k['revalidation']['invalidate_below'] > k['revalidation']['trust_threshold']:
        raise DiscoveryError('knowledge_confidence')
    return k


def _proofs(store, knowledge, partition):
    results = {}
    for meta in knowledge['evidence']:
        with store.lock:
            rows = store.db.execute('SELECT e.run,e.artifact,e.hash,e.expires,e.metadata,r.partition FROM evidence e JOIN runs r ON e.run=r.id WHERE e.id=?', (meta['id'],)).fetchall()
        if len(rows) != 1 or rows[0]['expires'] <= time.time():
            raise DiscoveryError('evidence_unavailable', '$', 'Retained evidence has expired or is unavailable; knowledge cannot be trusted/reused')
        row = rows[0]
        artifact = json.loads(row['artifact'])
        if (digest(artifact) != row['hash'] or row['hash'] != meta['content_hash']
                or canonical(meta) != row['metadata'] or row['partition'] != partition):
            raise DiscoveryError('evidence_integrity')
        results[meta['id']] = {'run': row['run'], 'artifact': artifact}
    for r in knowledge['routes']:
        if r['status'] == 'trusted' and len({results[i]['run'] for i in r['evidence_ids']}) < 2:
            raise DiscoveryError('unverified_knowledge')
    return results


def _run(context, run_id, site_origin):
    cache = context.get('discovery_runs', {})
    selected = cache.get(run_id) if type(cache) is dict else None
    if selected is None or time.time() - selected['created'] > 3600:
        raise DiscoveryError('run_unavailable', '$.run_id', 'Save only an unexpired current-session locally validated run; model candidates are not accepted')
    scope = Scope(selected['graph'].manifest['scope'])
    if tuple(scope.origins) != (origin(site_origin),):
        raise DiscoveryError('knowledge_partition', '$.origin', 'Knowledge save requires a single bound exact origin')
    if selected['result']['outcome'] in {'cancelled', 'failed'} or selected['result']['terminal_reason'] == 'safety_stop':
        raise DiscoveryError('knowledge_unusable')
    return selected, scope


def _purpose(url):
    from .discovery_scope import GENERIC_ALIASES
    parts = {GENERIC_ALIASES.get(segment, segment) for segment in urlsplit(url).path.split('/')}
    return next((p for p in ('search', 'documents', 'accounts', 'cases', 'transactions', 'profile', 'settings', 'help', 'navigation') if p in parts), 'landing')


def candidate(context, args, store):
    partition = namespace(context, args['origin'])
    selected, scope = _run(context, args['run_id'], args['origin'])
    if selected.get('binding_partition') != partition:
        raise DiscoveryError('knowledge_partition', '$.run_id', 'Bind the exact namespace before discovery; observations cannot be reassigned to another tenant/user/environment')
    prior = store.knowledge(partition)
    current = store.knowledge_revision(partition)
    if current != args['expected_revision']:
        raise DiscoveryError('stale_knowledge_revision')
    old = None
    if prior and not prior['invalidated']:
        try:
            old = semantics(prior['value'], scope)
            _proofs(store, old, partition)
        except DiscoveryError:
            # Missing/expired evidence cannot silently preserve trusted entries.
            old = None
    pages = [(m, a) for m, a in selected['artifacts'] if m['type'] == 'page' and a.get('rendering') == 'raw_static_only']
    if not pages:
        raise DiscoveryError('knowledge_unusable')
    # Persistence is a prerequisite: the source evidence commit must be durable
    # before explicit save consent can retain knowledge referencing it.
    for meta, artifact in pages:
        with store.lock:
            row = store.db.execute('SELECT hash FROM evidence WHERE run=? AND id=?', (args['run_id'], meta['id'])).fetchone()
        if row is None or row[0] != digest(artifact):
            raise DiscoveryError('persistent_evidence_required', '$.run_id', 'Enable persistent_graph and pass its gates before a new approved discovery run; ephemeral observations cannot be saved')
    routes = {r['url']: deepcopy(r) for r in old['routes']} if old else {}
    retained = {e['id']: deepcopy(e) for e in old['evidence']} if old else {}
    for meta, artifact in pages:
        u = scope.resolve(meta['source_url']).url
        previous = routes.get(u)
        ids = [meta['id']]
        first, verified_at = meta['observed_at'], meta['observed_at']
        if previous and previous['fingerprint'] != meta['structural_fingerprint'] and stamp(meta['observed_at']) < stamp(previous['last_verified']):
            raise DiscoveryError('knowledge_stale', '$.run_id', 'An older conflicting capture cannot replace newer route evidence; request a fresh approved observation')
        retained[meta['id']] = deepcopy(meta)
        if previous and previous['fingerprint'] == meta['structural_fingerprint']:
            ids = sorted(set(previous['evidence_ids'] + ids), key=lambda i: (stamp(retained[i]['observed_at']), i))[-6:]
            first = min(previous['first_seen'], meta['observed_at'])
            verified_at = max(previous['last_verified'], meta['observed_at'])
        routes[u] = {'id': 'route' + digest(u)[:24], 'url': u, 'purpose': _purpose(u),
                     'template_id': 'template' + meta['structural_fingerprint'][:24],
                     'fingerprint': meta['structural_fingerprint'], 'auth_requirement': 'public',
                     'confidence': .8, 'evidence_ids': ids, 'first_seen': first,
                     'last_verified': verified_at, 'status': 'candidate'}
    if len(routes) > 100:
        raise DiscoveryError('knowledge_limit')
    used = {i for r in routes.values() for i in r['evidence_ids']}
    retained = {i: e for i, e in retained.items() if i in used}
    proofs = {}
    for i in retained:
        with store.lock:
            row = store.db.execute('SELECT run,artifact,expires FROM evidence WHERE id=?', (i,)).fetchone()
        if row is None or row['expires'] <= time.time():
            raise DiscoveryError('evidence_unavailable')
        proofs[i] = {'run': row['run'], 'artifact': json.loads(row['artifact'])}
    for r in routes.values():
        independent = len({proofs[i]['run'] for i in r['evidence_ids']})
        if independent >= 2:
            r['status'], r['confidence'] = 'trusted', .9
    templates = {}
    for r in routes.values():
        artifact = proofs[r['evidence_ids'][-1]]['artifact']
        features = sorted(artifact.get('tags', {})) or ['static_resource']
        existing = templates.setdefault(r['template_id'], {'id': r['template_id'],
            'structural_features': features[:20], 'fingerprint': r['fingerprint'], 'evidence_ids': []})
        existing['evidence_ids'] = list(dict.fromkeys(existing['evidence_ids'] + r['evidence_ids']))
    actions = []
    for r in routes.values():
        links = set(proofs[r['evidence_ids'][-1]]['artifact'].get('links', []))
        for target in sorted(links & set(routes)):
            to = routes[target]
            # A reusable static-link edge needs independent source observations
            # and independently verified target GETs. It still grants no click.
            source_runs = {proofs[i]['run'] for i in r['evidence_ids'] if target in proofs[i]['artifact'].get('links', [])}
            followed_runs = {proofs[i]['run'] for i in to['evidence_ids'] if proofs[i]['artifact'].get('discovery_source') == r['url']}
            runs = source_runs & followed_runs
            if len(runs) < 2 or to['status'] != 'trusted' or r['status'] != 'trusted':
                continue
            actions.append({'id': 'action' + digest([r['id'], to['id']])[:24],
                'from_route': r['id'], 'to_route': to['id'], 'kind': 'navigate', 'effect': 'read',
                'preconditions': ['verified_static_link'], 'locators': [], 'expected_transition': to['id'],
                'approval': 'existing_read_approval', 'evidence_ids': list(dict.fromkeys(r['evidence_ids'] + to['evidence_ids'])),
                'confidence': min(r['confidence'], to['confidence']), 'verified_successes': min(2, len(runs)), 'failures': 0})
    k = {'version': '1.0', 'kind': 'website_knowledge', 'knowledge_id': 'knowledge' + partition[:24],
         'revision': current + 1, 'scope_identity': scope.identity, 'origin': origin(args['origin']),
         'application_fingerprint': digest(sorted((r['url'], r['fingerprint']) for r in routes.values())),
         'auth_partition': 'public', 'routes': sorted(routes.values(), key=lambda r: r['id']),
         'templates': sorted(templates.values(), key=lambda t: t['id']), 'actions': actions[:1000],
         'forms': [], 'boundaries': [], 'overlays': [], 'api_patterns': [], 'recoveries': [],
         'evidence': sorted(retained.values(), key=lambda e: e['id']),
         'first_seen': min(r['first_seen'] for r in routes.values()),
         'last_verified': max(r['last_verified'] for r in routes.values()), 'revalidation': {'ttl_seconds': 7 * 86400,
             'half_life_seconds': 7 * 86400, 'trust_threshold': .7, 'invalidate_below': .3},
         'sanitisation': 'strict_v1_passed'}
    semantics(k, scope)
    _proofs(store, k, partition)
    return partition, k


def validate_knowledge_tool(name, args, context=None):
    from .protocol import validate_schema
    if name not in KNOWLEDGE_SPECS or validate_schema(args, KNOWLEDGE_SPECS[name][0]):
        raise DiscoveryError('invalid_contract')
    if name == 'navigation.intent':
        expected = correlation(context) if context is not None else None
        intent = validate_contract(args['intent'], 'navigation_intent', expected)
        validate_budgets(intent['budgets'])
        Scope(intent['scope'])
        _safe_label(intent['target_purpose'])
        if intent['target_purpose'] not in PURPOSES:
            raise DiscoveryError('ambiguous_target')
        if intent['budgets']['concurrency'] != 1:
            raise DiscoveryError('navigation_serial_only')
    else:
        origin(args['origin'])
    if context is not None:
        testing_gate(context, 'knowledge_reuse' if name in {'discovery.knowledge_lookup', 'navigation.intent'} else 'knowledge_write')
        if not enabled(context, 'persistent_graph'):
            raise DiscoveryError('persistent_evidence_required')
        o = args.get('origin') or args['intent']['scope']['origins'][0]
        namespace(context, o)


def lookup(context, site_origin, scope=None):
    partition = namespace(context, site_origin)
    store = Store(context, persistent=True, readonly=True)
    try:
        record = store.knowledge(partition)
        if record is None:
            raise DiscoveryError('knowledge_missing', '$', 'No separately consented map exists; request a new approved discovery run')
        if record['invalidated']:
            raise DiscoveryError('knowledge_invalidated')
        if scope is None:
            try:
                consent = json.loads(record['consent'])
                scope = Scope(consent['scope'])
            except (ValueError, KeyError, TypeError) as error:
                raise DiscoveryError('knowledge_partition') from error
        k = semantics(record['value'], scope)
        _proofs(store, k, partition)
        now = time.time()
        if now - stamp(k['last_verified']) >= k['revalidation']['ttl_seconds']:
            raise DiscoveryError('knowledge_stale')
        return record, k
    finally:
        store.close()


def reliable_route(knowledge, start, target, now=None):
    now = time.time() if now is None else now
    rule = knowledge['revalidation']
    routes = {r['id']: r for r in knowledge['routes']}
    def fresh(r):
        age = max(0, now - stamp(r['last_verified']))
        confidence = r['confidence'] * math.exp(-math.log(2) * age / rule['half_life_seconds'])
        return r['status'] == 'trusted' and r['auth_requirement'] == 'public' and age < rule['ttl_seconds'] and confidence >= rule['trust_threshold']
    if start not in routes or target not in routes or not fresh(routes[start]) or not fresh(routes[target]):
        raise DiscoveryError('knowledge_stale')
    if start == target:
        return []
    edges = {}
    for a in knowledge['actions']:
        if (a['kind'] != 'navigate' or a['effect'] != 'read' or a['approval'] != 'existing_read_approval'
                or a['locators'] or a['preconditions'] != ['verified_static_link'] or a['verified_successes'] < 2
                or a['confidence'] < rule['trust_threshold'] or not fresh(routes[a['from_route']]) or not fresh(routes[a['to_route']])):
            continue
        cost = 1 + 5 * (1 - a['confidence']) + a['failures'] / max(1, a['verified_successes'])
        edges.setdefault(a['from_route'], []).append((a, cost))
    queue, distances = [(0.0, start, [])], {start: 0.0}
    while queue:
        cost, node, path = heapq.heappop(queue)
        if node == target:
            return path
        if cost > distances[node]:
            continue
        for edge, weight in sorted(edges.get(node, []), key=lambda item: item[0]['id']):
            total = cost + weight
            next_node = edge['to_route']
            if total < distances.get(next_node, float('inf')):
                distances[next_node] = total
                heapq.heappush(queue, (total, next_node, path + [edge]))
    raise DiscoveryError('navigation_unreachable', '$', 'No independently evidenced read-only static link chain reaches the target')


def compile_intent(args, context):
    validate_knowledge_tool('navigation.intent', args, context)
    intent = args['intent']
    scope = Scope(intent['scope'])
    if len(scope.origins) != 1:
        raise DiscoveryError('knowledge_partition')
    record, knowledge = lookup(context, scope.origins[0], scope)
    current = getattr(getattr(context.get('browser'), 'tool_page', None), 'url', None)
    current = scope.resolve(current).url
    starts = [r for r in knowledge['routes'] if r['url'] == current]
    targets = [r for r in knowledge['routes'] if r['purpose'] == intent['target_purpose'] and r['status'] == 'trusted']
    if len(starts) != 1 or len(targets) != 1:
        raise DiscoveryError('ambiguous_target', '$.target_purpose', 'The starting route and target purpose must each resolve to one current scoped route')
    start, target = starts[0], targets[0]
    route = reliable_route(knowledge, start['id'], target['id'])
    if len(route) + 1 > intent['budgets']['pages'] or len(route) + 7 > intent['budgets']['tasks']:
        raise DiscoveryError('navigation_budget')
    steps = [{'id': 'step' + str(i + 1), 'action_id': a['id'], 'from_route': a['from_route'],
              'to_route': a['to_route'], 'kind': 'navigate', 'effect': 'read', 'locators': [],
              'preconditions': ['verified_static_link'], 'expected_transition': a['to_route'],
              'validation': list(VALIDATIONS), 'approval': 'existing_read_approval',
              'recovery_policy': 'no_retry_v1', 'success_evidence_types': ['page', 'structure']}
             for i, a in enumerate(route)]
    plan = {'version': '1.0', 'kind': 'navigation_plan', 'request_id': intent['request_id'],
            'knowledge_id': knowledge['knowledge_id'], 'knowledge_revision': record['revision'],
            'scope_identity': scope.identity, 'target_route': target['id'], 'starting_route': start['id'],
            'steps': steps, 'budgets': deepcopy(intent['budgets']), 'stop_on': list(STOP_ON),
            'success': {'route_id': target['id'], 'required_evidence_types': ['page', 'structure'], 'minimum_confidence': .8}}
    validate_contract(plan, 'navigation_plan', intent['request_id'])
    check_plan(plan, knowledge)
    return plan, knowledge


def check_plan(plan, knowledge):
    validate_contract(plan, 'navigation_plan')
    if (plan['knowledge_id'] != knowledge['knowledge_id'] or plan['knowledge_revision'] != knowledge['revision']
            or plan['scope_identity'] != knowledge['scope_identity'] or set(plan['stop_on']) != set(STOP_ON)):
        raise DiscoveryError('navigation_revision')
    actions = {a['id']: a for a in knowledge['actions']}
    current = plan['starting_route']
    for step in plan['steps']:
        action = actions.get(step['action_id'])
        if (not action or step['from_route'] != current or step['from_route'] != action['from_route']
                or step['to_route'] != action['to_route'] or step['kind'] != action['kind']
                or step['effect'] != 'read' or action['effect'] != 'read' or step['locators']
                or step['approval'] != 'existing_read_approval' or step['recovery_policy'] != 'no_retry_v1'
                or set(step['validation']) != set(VALIDATIONS)
                or step['preconditions'] != ['verified_static_link'] or step['expected_transition'] != step['to_route']):
            raise DiscoveryError('navigation_chain')
        current = step['to_route']
    if current != plan['target_route'] or plan['success']['route_id'] != current:
        raise DiscoveryError('navigation_chain')


def prepare_knowledge_tool(name, args, context):
    validate_knowledge_tool(name, args, context)
    if name == 'navigation.intent':
        accepted = context.setdefault('discovery_accepted_at', time.time())
        context.setdefault('discovery_accepted_monotonic', time.monotonic())
        if time.time() >= accepted + args['intent']['budgets']['run_seconds'] - 1:
            raise DiscoveryError('runtime_limit', '$.budgets.run_seconds', 'Approval wait exhausted the original intent budget')
        plan, knowledge = compile_intent(args, context)
        routes = {route['id']: route for route in knowledge['routes']}
        verified_urls = [routes[plan['starting_route']]['url']] + [routes[step['to_route']]['url'] for step in plan['steps']]
        return {'kind': name, 'accepted_at': accepted, 'intent_sha256': digest(args['intent']), 'plan': plan,
                'scope': deepcopy(args['intent']['scope']), 'verified_urls': verified_urls,
                'target_url': routes[plan['target_route']]['url'],
                'knowledge_sha256': digest(knowledge), 'execution': 'Scoped public HTTPS GET verification only; browser page is not changed.',
                'save_consent': False, 'targeted_repair': 'Unavailable; stale/missing map requires a new separately approved discovery run.'}
    partition = namespace(context, args['origin'])
    store = Store(context, persistent=True, readonly=True)
    try:
        if name == 'discovery.knowledge_save':
            _, k = candidate(context, args, store)
            return {'kind': name, 'namespace_id': partition, 'expected_revision': args['expected_revision'],
                    'new_revision': k['revision'], 'payload_sha256': digest(k),
                    'categories': ['routes', 'templates', 'actions', 'evidence'],
                    'route_count': len(k['routes']), 'trusted_routes': sum(r['status'] == 'trusted' for r in k['routes']),
                    'consent_question': 'Save these exact sanitized evidence-backed navigation categories locally on this user/device, outside OneDrive?',
                    'scope_identity': k['scope_identity'], 'origin': k['origin'], 'ttl_seconds': k['revalidation']['ttl_seconds'],
                    'candidate_policy': 'One run is candidate only. Trust requires matching successful observations in two independent approved runs; no generated selectors, permissions or page instructions.'}
        record = store.knowledge(partition)
        current = store.knowledge_revision(partition)
        if current != args['expected_revision']:
            raise DiscoveryError('stale_knowledge_revision')
        return {'kind': name, 'namespace_id': partition, 'expected_revision': current,
                'consent_question': 'Invalidate this exact local discovery namespace? Existing legacy website memory is separate.'}
    finally:
        store.close()


async def execute_knowledge_tool(name, args, context):
    validate_knowledge_tool(name, args, context)
    if name == 'discovery.knowledge_lookup':
        partition = namespace(context, args['origin'])
        inspection = Store(context, persistent=True, readonly=True)
        try:
            revision = inspection.knowledge_revision(partition)
        finally:
            inspection.close()
        try:
            record, _ = lookup(context, args['origin'])
        except DiscoveryError as error:
            if error.code not in {'knowledge_missing', 'knowledge_stale', 'knowledge_invalidated', 'evidence_unavailable'}:
                raise
            return {'status': error.code, 'revision': revision, 'requires_new_approved_discovery': True,
                    'knowledge_grants_permission': False, 'browser_execution_available': False}
        k = record['value']
        if time.time() - stamp(k['last_verified']) >= k['revalidation']['ttl_seconds']:
            raise DiscoveryError('knowledge_stale')
        summaries = []
        rule = k['revalidation']
        for route in k['routes'][:40]:
            item = {f: route[f] for f in ('id', 'url', 'purpose', 'status', 'confidence', 'last_verified')}
            age = max(0, time.time() - stamp(route['last_verified']))
            item['confidence'] *= math.exp(-math.log(2) * age / rule['half_life_seconds'])
            if age >= rule['ttl_seconds'] or item['confidence'] < rule['trust_threshold']:
                item['status'] = 'invalid' if item['confidence'] < rule['invalidate_below'] else 'stale'
            summaries.append(item)
        return {'status': 'candidate_or_current', 'knowledge_id': k['knowledge_id'], 'revision': record['revision'],
                'scope_identity': k['scope_identity'], 'origin': k['origin'],
                'routes': summaries,
                'omitted_routes': max(0, len(k['routes']) - 40), 'requires_fresh_public_get_verification': True,
                'browser_execution_available': False}
    reviewed = prepare_knowledge_tool(name, args, context)
    if (context.get('approved') is not True or not context.get('approval_hash')
            or context.get('discovery_reviewed') != reviewed or cancelled(context)):
        raise DiscoveryError('approval_required')
    context['discovery_effects_started'] = True
    if name == 'navigation.intent':
        return await execute_intent(args, context, reviewed)
    partition = namespace(context, args['origin'])
    store = Store(context, persistent=True)
    try:
        if name == 'discovery.knowledge_save':
            if context.get('discovery_save_consent') != reviewed:
                raise DiscoveryError('save_consent_required')
            _, k = candidate(context, args, store)
            consent = {'approval_hash': context['approval_hash'], 'review_sha256': digest(reviewed),
                       'categories': reviewed['categories'], 'binding_namespace': partition,
                       'source_run': args['run_id'],
                       'scope': deepcopy(context['discovery_runs'][args['run_id']]['graph'].manifest['scope']),
                       'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            store.save_knowledge(partition, args['expected_revision'], k, consent)
            verified = store.knowledge(partition)
            if verified['hash'] != digest(k):
                raise DiscoveryError('knowledge_integrity')
            return {'status': 'saved', 'knowledge_id': k['knowledge_id'], 'revision': k['revision'],
                    'payload_sha256': digest(k), 'route_count': len(k['routes']),
                    'trusted_routes': sum(r['status'] == 'trusted' for r in k['routes']), 'knowledge_grants_permission': False}
        store.invalidate(partition, args['expected_revision'])
        return {'status': 'invalidated', 'namespace_id': partition, 'revision': args['expected_revision']}
    finally:
        store.close()


async def execute_intent(args, context, reviewed):
    from .discovery_contracts import compile_manifest
    plan, knowledge = compile_intent(args, context)
    if plan != reviewed['plan'] or digest(knowledge) != reviewed['knowledge_sha256']:
        raise DiscoveryError('navigation_revision')
    routes = {r['id']: r for r in knowledge['routes']}
    urls = [routes[plan['starting_route']]['url']] + [routes[s['to_route']]['url'] for s in plan['steps']]
    # Reuse the same compiler, cancellation, transport and evidence ledger as
    # discovery; no alternate executor can evade scope/public-IP/byte controls.
    def task(i, worker, parents, refs, url_list=()):
        from .discovery_contracts import MAPPING
        operation, output = MAPPING[worker]
        return {'id': i, 'worker': worker, 'operation': operation, 'branch': 'navigation',
                'depends_on': [{'task_id': p, 'accept': 'usable'} for p in parents],
                'inputs': {'urls': list(url_list), 'evidence_from': list(refs), 'route_ids': []},
                'output_type': output, 'priority': 100, 'critical': True,
                'timeout_seconds': min(30, args['intent']['budgets']['task_seconds']), 'max_attempts': 1,
                'recovery_policy': 'no_retry_v1', 'auth_requirement': 'public',
                'approval_requirement': 'existing_read_approval' if worker in {'bootstrap', 'http'} else 'none',
                'expand_urls': False}
    b = deepcopy(args['intent']['budgets'])
    if b['tasks'] < len(urls) + 6:
        raise DiscoveryError('navigation_budget')
    tasks = [task('bootstrap', 'bootstrap', [], []),
             task('navigation', 'http', ['bootstrap'], ['bootstrap'], urls),
             task('structure', 'structure', ['navigation'], ['navigation']),
             task('validate', 'validate', ['structure'], ['structure', 'navigation']),
             task('aggregate', 'aggregate', ['validate'], ['validate'])]
    manifest = {'version': '1.0', 'kind': 'discovery_manifest', 'request_id': plan['request_id'],
        'objective': 'Locally compiled public static route verification.', 'seed_urls': [urls[0]],
        'scope': deepcopy(args['intent']['scope']), 'authentication': {'mode': 'public', 'context_ref': None},
        'permitted_workers': ['bootstrap', 'http', 'structure', 'validate', 'aggregate'], 'budgets': b, 'tasks': tasks,
        'evidence_requirements': {'required_types': ['scope', 'page', 'structure', 'boundary'],
            'freshness_seconds': 300, 'minimum_confidence': .8, 'retain_screenshots': False},
        'stop': {'plateau_window_pages': 10, 'plateau_windows': 3, 'minimum_gain': .01,
            'duplicate_ratio': .9, 'required_high_priority_coverage': .95}, 'replanning_triggers': [],
        'redaction_profile': 'strict_v1', 'final_requirements': {'max_model_bytes': 10000, 'include_gaps': True, 'include_evidence_refs': True}}
    graph = compile_manifest(manifest, correlation(context))
    expected = {r['url']: r for r in knowledge['routes']}
    next_links = {routes[s['from_route']]['url']: routes[s['to_route']]['url'] for s in plan['steps']}
    def verify_page(artifact):
        route = expected.get(artifact['url'])
        fingerprint = digest({k: artifact[k] for k in ('tags', 'forms', 'controls') if k in artifact})
        if (route is None or fingerprint != route['fingerprint']
                or artifact['dynamic_gap'] or artifact['url'] in next_links and next_links[artifact['url']] not in artifact['links']):
            raise DiscoveryError('unexpected_transition', '$', 'Installed static fingerprint/link precondition failed; later reads are not dispatched')
    execution_context = dict(context, discovery_page_validator=verify_page)
    engine = Engine(graph, execution_context)
    projected = await engine.run()
    selected = context.get('discovery_runs', {}).get(engine.run_id)
    if not selected:
        raise DiscoveryError('navigation_verification')
    pages = {m['source_url']: (m, a) for m, a in selected['artifacts'] if m['type'] == 'page'}
    current = plan['starting_route']
    for step in plan['steps']:
        before = pages.get(routes[current]['url'])
        after = pages.get(routes[step['to_route']]['url'])
        if (not before or not after or before[0]['structural_fingerprint'] != routes[current]['fingerprint']
                or after[0]['structural_fingerprint'] != routes[step['to_route']]['fingerprint']
                or routes[step['to_route']]['url'] not in before[1]['links']):
            raise DiscoveryError('unexpected_transition', '$', 'Static link/fingerprint drift stopped verification; no browser action was attempted')
        current = step['to_route']
    target = pages.get(routes[plan['target_route']]['url'])
    if not target or target[0]['structural_fingerprint'] != routes[plan['target_route']]['fingerprint']:
        raise DiscoveryError('unexpected_transition')
    if selected['result']['outcome'] != 'complete':
        raise DiscoveryError('navigation_verification')
    return {'status': 'verified_static_target', 'request_id': plan['request_id'], 'run_id': engine.run_id,
            'knowledge_id': knowledge['knowledge_id'], 'knowledge_revision': knowledge['revision'],
            'target_route': plan['target_route'], 'plan_steps': len(plan['steps']), 'zero_action_verified': not plan['steps'],
            'evidence_ids': [target[0]['id']], 'browser_navigated': False,
            'limitations': 'Only a public static GET target and link chain were verified. No rendered browser/control/authentication state or consequential effect is claimed.'}
