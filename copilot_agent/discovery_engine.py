"""Installed bounded public-read manifest dispatch, local fan-in and safe evidence."""
from __future__ import annotations

import asyncio
from collections import Counter, deque
from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import os
import time
from urllib.parse import urljoin
import uuid

from .discovery_contracts import (DiscoveryError, canonical, compile_manifest, schema,
                                  validate_contract, INSTALLED_WORKERS)
from .discovery_http import PublicReader, ReadFailure
from .discovery_scope import Scope
from .discovery_store import Store, TERMINAL, alias, digest
from .policy import config_value

FLAGS = ('manifest_path', 'persistent_graph', 'bounded_parallelism', 'local_recovery',
         'knowledge_write', 'knowledge_reuse', 'targeted_repair')


def enabled(context, flag):
    return config_value(context.get('config', {}), flag, False) is True


def testing_gate(context, flag):
    if not enabled(context, flag):
        raise DiscoveryError('feature_disabled', '$', 'This capability is disabled; use the existing approved sequential tools')


def cancelled(context):
    event = context.get('cancel_event')
    return bool(event is not None and event.is_set() or callable(context.get('cancelled')) and context['cancelled']())


def correlation(context):
    value = context.get('source_request_id')
    if type(value) is not str or not value:
        raise DiscoveryError('request_unavailable')
    return 'd' + value


def input_object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


MANIFEST_SCHEMA = input_object({'manifest': schema('discovery_manifest')})
DISCOVERY_SPECS = {
    'discovery.manifest': (MANIFEST_SCHEMA, 'user_approval',
        'One exact approved public read-only manifest, locally compiled DAG, bounded HTTPS GET/HEAD, evidence and aggregate. No browser/auth/network observers/generated code. Feature flags and local approval remain authoritative. Nested request_id is d + current envelope request_id.'),
    'discovery.shadow': (MANIFEST_SCHEMA, 'read_only',
        'Manifest shape/scope/capability/DAG compilation, zero network or persistence; never grants execution authority.'),
}


def validate_discovery(name, args, context=None):
    if name not in DISCOVERY_SPECS or type(args) is not dict or set(args) != {'manifest'}:
        raise DiscoveryError('invalid_contract')
    expected = correlation(context) if context is not None else None
    graph = compile_manifest(args['manifest'], expected)
    if context is not None:
        testing_gate(context, 'manifest_path')
        if graph.manifest['budgets']['concurrency'] != 1 and not enabled(context, 'bounded_parallelism'):
            raise DiscoveryError('parallelism_disabled', '$.budgets.concurrency', 'Sequential canary requires concurrency=1 until the parallel gate passes')
    return graph


def prepare_discovery(args, context):
    graph = validate_discovery('discovery.manifest', args, context)
    m = graph.manifest
    accepted = context.setdefault('discovery_accepted_at', time.time())
    context.setdefault('discovery_accepted_monotonic', time.monotonic())
    if time.time() >= accepted + m['budgets']['run_seconds'] - 1:
        raise DiscoveryError('runtime_limit', '$.budgets.run_seconds', 'Approval/validation wait exhausted the original run budget; a new request is required')
    storage = 'ephemeral; no retained run/knowledge'
    if enabled(context, 'persistent_graph'):
        from .discovery_store import directory
        directory(context)
        storage = 'sanitised local-device/user transactional ledger; seven-day evidence; no OneDrive store'
    return {'kind': 'discovery.manifest', 'manifest_sha256': graph.digest,
            'request_id': m['request_id'], 'accepted_at': accepted,
            'scope': deepcopy(m['scope']),
            'effective_origins': list(Scope(m['scope']).origins),
            'scope_identity': Scope(m['scope']).identity,
            'authentication': 'public; no credentials, browser cookies or session copying',
            'workers': sorted(set(t['worker'] for t in m['tasks'])), 'budgets': deepcopy(m['budgets']),
            'storage': storage, 'knowledge_saved': False,
            'consequence': 'Public read-only GET/HEAD only. No JavaScript, forms, clicks, probes or auth bypass.',
            'limitations': 'Generic navigation paths only; browser/authentication/passive-network/replanning unavailable. Static evidence does not prove rendered UI transitions.'}


class StructureParser(HTMLParser):
    """Retain closed-vocabulary structural features and scoped hrefs, never text/values."""
    def __init__(self, url, scope):
        super().__init__(convert_charrefs=True)
        self.url, self.scope = url, scope
        self.tags, self.links, self.blocked = Counter(), [], 0
        self.forms, self.scripts, self.controls = 0, 0, 0
        self.authentication_boundary = False
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        safe_tags = {'html', 'head', 'body', 'main', 'nav', 'header', 'footer', 'section',
                     'article', 'a', 'button', 'form', 'input', 'select', 'textarea',
                     'table', 'tr', 'td', 'h1', 'h2', 'h3', 'script'}
        if tag in safe_tags:
            self.tags[tag] = min(1000, self.tags[tag] + 1)
        self.forms += int(tag == 'form')
        self.scripts += int(tag == 'script')
        self.controls += int(tag in {'a', 'button', 'input', 'select', 'textarea'})
        if tag == 'input' and any(name == 'type' and str(value).lower() == 'password' for name, value in attrs):
            self.authentication_boundary = True
        if tag != 'a':
            return
        if len(attrs) > 50 or len(self.links) >= 100:
            self.suppressed += 1
            return
        hrefs = [value for name, value in attrs if name == 'href']
        if len(hrefs) != 1 or hrefs[0] is None or len(hrefs[0]) > 2048:
            self.blocked += 1
            return
        try:
            target = self.scope.resolve(urljoin(self.url, hrefs[0])).url
        except DiscoveryError:
            self.blocked += 1
            return
        if target not in self.links:
            self.links.append(target)

    def snapshot(self):
        return {'url': self.url, 'tags': dict(sorted(self.tags.items())), 'links': sorted(self.links),
                'forms': min(self.forms, 1000), 'scripts': min(self.scripts, 1000),
                'controls': min(self.controls, 1000), 'blocked_links': self.blocked,
                'suppressed_links': self.suppressed, 'rendering': 'raw_static_only',
                'values_text_headers_omitted': True}


def extract(response, scope):
    try:
        text = response.body.decode('utf-8', errors='strict')
    except UnicodeError as error:
        raise ReadFailure('encoding_unavailable') from error
    parser = StructureParser(response.url, scope)
    if response.content_type in {'text/html', 'application/xhtml+xml'}:
        parser.feed(text)
        parser.close()
    if parser.authentication_boundary:
        raise ReadFailure('authentication_required')
    snapshot = parser.snapshot()
    snapshot.update(status=response.status, content_type=response.content_type,
                    redirects=list(response.redirects), body_sha256=hashlib.sha256(response.body).hexdigest(),
                    text_extraction='not_retained')
    snapshot['dynamic_gap'] = bool(parser.scripts and not parser.controls)
    return snapshot


class Engine:
    def __init__(self, graph, context):
        self.graph, self.context = graph, context
        self.m = graph.manifest
        self.scope = Scope(self.m['scope'])
        self.run_id, self.owner = 'r' + uuid.uuid4().hex, 'o' + uuid.uuid4().hex
        self.tasks = {t['id']: t for t in self.m['tasks']}
        self.states, self.outputs, self.reasons, self.task_evidence = {}, {}, {}, {}
        self.page_cache, self.url_locks, self.families = {}, {}, Counter()
        self.gaps, self.evidence = [], []
        self.diagnostics = {}
        self.stop_reason = None
        self.features, self.windows, self.window_features = set(), [], set()
        self.duplicate_windows, self.last_duplicate_count = [], 0
        self.completed_pages, self.plateau = 0, False
        self.completed_urls = set()
        self.started = context.get('discovery_accepted_at', time.time())
        self.monotonic_deadline = context.get('discovery_accepted_monotonic', time.monotonic()) + self.m['budgets']['run_seconds'] - 1
        partition = digest({'session': str(context.get('session_dir')), 'scope': self.scope.identity, 'auth': 'public'})
        self.binding_partition = None
        if len(self.scope.origins) == 1:
            from .site_knowledge import _scope
            try:
                binding = _scope('site_knowledge.retrieve', {'origin': self.scope.origins[0]}, context)
                self.binding_partition = digest({'binding': binding, 'auth_partition': 'public', 'contract': 'discovery-v1'})
                partition = self.binding_partition
            except (ValueError, RuntimeError):
                pass
        self.store = Store(context, enabled(context, 'persistent_graph'))
        try:
            self.reader = PublicReader(self.scope, self.store, self.run_id, self.m['budgets'],
                                       lambda: cancelled(context), monotonic_deadline=self.monotonic_deadline)
            self.store.create_run(self.run_id, graph, partition, self.owner, self.started)
        except BaseException:
            self.store.close()
            raise

    def gap(self, reason, tasks=(), severity='material', area='public_read'):
        value = {'area': area, 'reason': reason, 'severity': severity,
                 'affected_tasks': [alias(t) for t in tasks], 'next_action': 'new_request'}
        if value not in self.gaps and len(self.gaps) < 100:
            self.gaps.append(value)

    def evidence_pair(self, task, kind, artifact, source=None, confidence=.8):
        source = self.scope.resolve(source or self.m['seed_urls'][0]).url
        fingerprint = digest({k: artifact[k] for k in ('tags', 'forms', 'controls') if k in artifact})
        metadata = {'id': 'e' + uuid.uuid4().hex, 'type': kind, 'task_id': alias(task),
                    'source_url': source, 'observed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'content_hash': digest(artifact), 'structural_fingerprint': fingerprint,
                    'artifact_ref': 'sha256:' + digest(artifact), 'redaction': 'passed',
                    'confidence': confidence, 'summary': {
                        'scope': 'Locally approved public scope and response assessed.',
                        'boundary': 'Explicit access/scope boundary assessment; no bypass or secret content retained.',
                        'page': 'Sanitised static page structure; no DOM text, values, headers or rendered-state claims.',
                        'structure': 'Scoped observed routes/links assembled from immutable sanitised page metadata.',
                        'diagnostic': 'A bounded installed read stopped; material limitations are explicit.',
                    }[kind]}
        if kind == 'page':
            features = ', '.join(name + '=' + str(count) for name, count in sorted(artifact.get('tags', {}).items()))
            metadata['summary'] = ('Static structure (' + (features or 'plain resource') + '); '
                                   + str(len(artifact.get('links', []))) + ' scoped generic link candidates; '
                                   + str(artifact.get('forms', 0)) + ' forms never submitted. Text/values omitted; no rendered transition claim.')[:2048]
        elif kind == 'structure' and artifact.get('scope_only'):
            metadata['summary'] = 'Scoped public response routes from HEAD assessment only; no page content, structure or controls were verified.'
        elif kind == 'structure':
            metadata['summary'] = ('Observed candidate map: ' + str(len(artifact.get('routes', []))) + ' scoped static routes and '
                                   + str(len(artifact.get('edges', []))) + ' observed link edges. No automatic trust or browser execution.')
        return metadata, artifact

    async def read_url(self, task, url, depth, source, deadline, method='GET'):
        scoped = self.scope.resolve(url)
        lock = self.url_locks.setdefault(method + scoped.url, asyncio.Lock())
        async with lock:
            if method == 'GET' and scoped.url in self.page_cache:
                self.store.reserve(self.run_id, 'duplicates_avoided', 1, 100000)
                return deepcopy(self.page_cache[scoped.url])
            if depth > self.m['budgets']['depth']:
                self.gap('Depth limit suppressed an observed candidate.', [task['id']])
                self.store.reserve(self.run_id, 'suppressed', 1, 100000)
                return None
            fresh = self.store.enqueue(self.run_id, method + ':' + scoped.url, depth, source, task['id'])
            # Queue keys include method so HEAD bootstrap never suppresses page GET.
            queue_url = method + ':' + scoped.url
            if fresh:
                self.store.reserve(self.run_id, 'tasks', 1, self.m['budgets']['tasks'])
            if method == 'GET':
                self.store.reserve(self.run_id, 'pages', 1, self.m['budgets']['pages'])
                family = scoped.origin + '/' + '/'.join(scoped.path.split('/')[1:2])
                if self.families[family] >= 20:
                    self.gap('Route-family cap suppressed expansion.', [task['id']])
                    self.store.reserve(self.run_id, 'suppressed', 1, 100000)
                    return None
                self.families[family] += 1
            attempts = task['max_attempts'] if enabled(self.context, 'local_recovery') and task['recovery_policy'] == 'read_only_v1' else 1
            backoff = 0.0
            for attempt in range(attempts):
                self.reader.check(deadline)
                self.store.url_attempt(self.run_id, queue_url, deadline, attempts)
                try:
                    response = await self.reader.fetch(scoped.url, min(deadline, time.time() + task['timeout_seconds']), method)
                    result = ({'url': response.url, 'status': response.status, 'redirects': list(response.redirects),
                               'public': True, 'boundary_assessed': True, 'observed_access_restriction': False}
                              if method == 'HEAD' else extract(response, self.scope))
                    if method == 'GET':
                        predicate = self.context.get('discovery_page_validator')
                        if callable(predicate):
                            predicate(result)
                    self.store.url_finish(self.run_id, queue_url, 'SUCCEEDED')
                    if method == 'GET':
                        self.page_cache[scoped.url] = deepcopy(result)
                    return result
                except ReadFailure as error:
                    if error.code == 'cancelled':
                        raise
                    delay = error.delay or min(20, 2 ** (attempt + 1))
                    if (not error.retryable or attempt + 1 >= attempts or backoff + delay > min(60, self.m['budgets']['backoff_seconds'])
                            or time.time() + delay >= deadline):
                        self.store.url_finish(self.run_id, queue_url, 'FAILED')
                        boundary = error.code in {'access_denied', 'authentication_required', 'scope_mismatch', 'private_destination'}
                        pair = self.evidence_pair(task['id'], 'boundary' if boundary else 'diagnostic',
                                                  {'error': error.code, 'assessed': True, 'no_bypass': True,
                                                   'public_read_usable': False}, scoped.url, confidence=1)
                        self.diagnostics.setdefault(task['id'], []).append(pair)
                        self.gap('Installed public read stopped: ' + error.code + '.', [task['id']],
                                 area='boundary' if error.code in {'access_denied', 'authentication_required', 'scope_mismatch', 'private_destination'} else 'public_read')
                        return None
                    self.store.reserve(self.run_id, 'retries', 1, 100000)
                    self.store.reserve(self.run_id, 'backoff_seconds', delay, self.m['budgets']['backoff_seconds'])
                    backoff += delay
                    await self.reader.wait(delay, deadline)
            return None

    def dependency(self, task):
        waiting = False
        for dep in task['depends_on']:
            state = self.states.get(dep['task_id'])
            if state not in TERMINAL:
                waiting = True
                continue
            accepted = (dep['accept'] == 'terminal' or state == 'SUCCEEDED'
                        or dep['accept'] == 'usable' and state == 'PARTIALLY_SUCCEEDED' and bool(self.outputs.get(dep['task_id'])))
            if not accepted:
                return 'impossible'
        return 'waiting' if waiting else 'ready'

    def update_plateau(self, artifact):
        if artifact['url'] in self.completed_urls:
            return
        self.completed_urls.add(artifact['url'])
        features = {('tag', k) for k in artifact.get('tags', {})} | {('route', u) for u in artifact.get('links', [])}
        self.window_features |= features - self.features
        self.features |= features
        self.completed_pages += 1
        if self.completed_pages % self.m['stop']['plateau_window_pages'] == 0:
            previous = len(self.features) - len(self.window_features)
            gain = len(self.window_features) / max(1, previous)
            self.windows.append(gain)
            current_duplicates = self.store.counters(self.run_id)['duplicates_avoided']
            duplicates = current_duplicates - self.last_duplicate_count
            self.last_duplicate_count = current_duplicates
            self.duplicate_windows.append(duplicates / max(1, duplicates + self.m['stop']['plateau_window_pages']))
            self.window_features.clear()

    def can_plateau(self, task):
        stop = self.m['stop']
        if (task['critical'] or task['priority'] >= 80 or len(self.windows) < stop['plateau_windows']
                or any(g['severity'] in {'material', 'blocking'} for g in self.gaps)):
            return False
        high = [i for i, t in self.tasks.items() if t['worker'] in {'bootstrap', 'http'} and t['priority'] >= 80]
        covered = [i for i in high if self.states.get(i) == 'SUCCEEDED']
        if len(covered) != len(high) or len(covered) / max(1, len(high)) < stop['required_high_priority_coverage']:
            return False
        if all(g < stop['minimum_gain'] for g in self.windows[-stop['plateau_windows']:]):
            return 'coverage_plateau'
        if all(r >= stop['duplicate_ratio'] for r in self.duplicate_windows[-stop['plateau_windows']:]):
            return 'duplicate_saturation'
        return False

    def checkpoint(self, task, outputs, artifacts):
        row = self.store.task(self.run_id, task['id'])
        self.store.checkpoint(self.run_id, task['id'], self.owner, row['fence'], outputs, artifacts)
        self.outputs[task['id']] = deepcopy(outputs)
        self.task_evidence[task['id']] = [meta['id'] for meta, _ in artifacts]

    async def worker(self, task, deadline, outputs, artifacts):
        worker = task['worker']
        if worker == 'bootstrap':
            for url in self.m['seed_urls']:
                result = await self.read_url(task, url, 0, None, deadline, 'HEAD')
                artifacts.extend(self.diagnostics.pop(task['id'], []))
                if result:
                    artifacts.extend([self.evidence_pair(task['id'], 'scope', result, result['url']),
                                      self.evidence_pair(task['id'], 'boundary', result, result['url'])])
                    outputs.append(result)
                    self.checkpoint(task, outputs, artifacts)
            if not outputs:
                artifacts.append(self.evidence_pair(task['id'], 'boundary',
                    {'assessed': True, 'public_read_usable': False, 'no_bypass': True}, confidence=1))
        elif worker == 'http':
            pending = deque((u, 0, None) for u in task['inputs']['urls'])
            admitted = set()
            while pending:
                self.reader.check(deadline)
                url, depth, source = pending.popleft()
                if url in admitted:
                    self.store.reserve(self.run_id, 'duplicates_avoided', 1, 100000)
                    continue
                admitted.add(url)
                result = await self.read_url(task, url, depth, source, deadline)
                artifacts.extend(self.diagnostics.pop(task['id'], []))
                if not result:
                    if artifacts:
                        self.checkpoint(task, outputs, artifacts)
                    continue
                result['discovery_source'] = source
                outputs.append(result)
                artifacts.append(self.evidence_pair(task['id'], 'page', result, result['url']))
                self.update_plateau(result)
                self.checkpoint(task, outputs, artifacts)
                if result['dynamic_gap']:
                    self.gap('App-shell signals require rendered evidence; autonomous browser capability is unavailable.', [task['id']], area='rendering')
                if result['blocked_links'] or result['suppressed_links']:
                    self.gap('Out-of-scope, sensitive or excess link candidates were suppressed without visiting.', [task['id']], severity='minor', area='coverage')
                plateau_reason = self.can_plateau(task)
                if plateau_reason:
                    self.plateau = plateau_reason == 'coverage_plateau'
                    self.stop_reason = plateau_reason
                    self.gap('Low-priority expansion stopped only after configured novelty/duplicate windows and all known high-priority branches completed.', [task['id']], area='coverage')
                    break
                if task['expand_urls']:
                    for link in result['links']:
                        if link not in admitted:
                            if depth + 1 > self.m['budgets']['depth']:
                                self.gap('Depth limit suppressed observed links.', [task['id']], area='coverage')
                                continue
                            if len(pending) + len(admitted) >= self.m['budgets']['pages']:
                                self.gap('Queue watermark suppressed further URL producers.', [task['id']], area='coverage')
                                break
                            pending.append((link, depth + 1, result['url']))
            # The inline expansion coordinator closes only after every admitted
            # child read is terminal. Downstream tasks cannot outrun this barrier.
        elif worker == 'structure':
            accepted = [a for ref in task['inputs']['evidence_from'] for a in self.outputs.get(ref, [])]
            pages = [a for a in accepted if a.get('rendering') == 'raw_static_only']
            scopes = [a for a in accepted if a.get('public') is True and a.get('boundary_assessed') is True]
            if pages or scopes:
                structure = {'routes': sorted({p['url'] for p in (pages or scopes)}),
                             'edges': sorted({(p['url'], link) for p in pages for link in p.get('links', [])}),
                             'candidate_only': True, 'scope_only': not pages,
                             'rendered_navigation_verified': False}
                outputs.append(structure)
                artifacts.append(self.evidence_pair(task['id'], 'structure', structure))
        elif worker == 'validate':
            accepted = [a for ref in task['inputs']['evidence_from'] for a in self.outputs.get(ref, [])]
            records = self.store.evidence(self.run_id)
            now = time.time()
            for meta, artifact in records:
                self.scope.resolve(meta['source_url'])
                stamp = datetime.fromisoformat(meta['observed_at']).timestamp()
                if stamp > now + 30 or now - stamp > self.m['evidence_requirements']['freshness_seconds'] or digest(artifact) != meta['content_hash']:
                    raise DiscoveryError('evidence_integrity')
            if any(a.get('candidate_only') is True for a in accepted):
                outputs.append({'validated': True, 'evidence_ids': [m['id'] for m, _ in records],
                                'knowledge_trusted': False})
        elif worker == 'aggregate':
            outputs.append({'finalise': True})
        return outputs, artifacts

    async def execute_task(self, task):
        i = task['id']
        self.store.transition(self.run_id, i, 'READY', 'dependencies accepted')
        fence, deadline = self.store.lease(self.run_id, i, self.owner, self.m['budgets']['task_seconds'], self.m['budgets']['branch_seconds'])
        starting_gaps = sum(alias(i) in g['affected_tasks'] for g in self.gaps)
        outputs, artifacts = [], []
        try:
            outputs, artifacts = await self.worker(task, deadline, outputs, artifacts)
            task_has_gaps = sum(alias(i) in g['affected_tasks'] for g in self.gaps) > starting_gaps
            state = 'SUCCEEDED' if outputs and not task_has_gaps else 'PARTIALLY_SUCCEEDED' if outputs else 'FAILED'
            reason = 'Installed outputs validated.' if state == 'SUCCEEDED' else 'Usable static outputs retained with gaps.' if outputs else 'Required installed output was unavailable.'
        except (DiscoveryError, OSError, ValueError) as error:
            code = error.code if isinstance(error, DiscoveryError) else 'worker_contract_failure'
            if code in {'cancelled', 'stale_commit'}:
                raise DiscoveryError('cancelled') from error
            if code in {'runtime_limit', 'page_limit', 'resource_limit', 'clock_anomaly'}:
                self.stop_reason = 'runtime_limit' if code == 'runtime_limit' else 'page_limit' if code == 'page_limit' else 'resource_limit'
            if code in {'private_destination', 'connection_mismatch', 'evidence_integrity', 'scope_mismatch'}:
                self.stop_reason = 'safety_stop'
            state, reason = ('PARTIALLY_SUCCEEDED' if outputs else 'FAILED'), 'Installed worker stopped: ' + code + '.'
            self.gap(reason, [i], 'blocking' if task['critical'] else 'material')
        try:
            self.store.commit(self.run_id, i, self.owner, fence, state, reason, outputs, artifacts)
        except DiscoveryError as error:
            if error.code != 'stale_commit' or cancelled(self.context) or self.store.run(self.run_id)['generation']:
                raise
            self.stop_reason = self.stop_reason or 'runtime_limit'
            row = self.store.task(self.run_id, i)
            if row['state'] != 'RUNNING' or row['owner'] != self.owner or row['fence'] != fence:
                raise DiscoveryError('stale_commit') from error
            retained = self.outputs.get(i, [])
            state = 'PARTIALLY_SUCCEEDED' if retained else 'FAILED'
            reason = 'Deadline exhausted; only previously fenced safe checkpoints retained.'
            self.store.transition(self.run_id, i, state, reason, expected=row['revision'])
            outputs = retained
            artifacts = [pair for pair in self.store.evidence(self.run_id) if pair[0]['task_id'] == alias(i)]
            self.gap(reason, [i], 'blocking' if task['critical'] else 'material')
        self.states[i], self.outputs[i], self.reasons[i] = state, outputs, reason
        self.task_evidence[i] = [meta['id'] for meta, _ in artifacts]
        self.evidence.extend(meta for meta, _ in artifacts)
        if task['critical'] and state == 'FAILED':
            self.stop_reason = self.stop_reason or 'critical_failure'

    def result(self):
        clean = []
        try:
            known_tasks = {alias(i) for i in self.tasks}
            now = time.time()
            for meta, artifact in self.store.evidence(self.run_id):
                self.scope.resolve(meta['source_url'])
                observed = datetime.fromisoformat(meta['observed_at']).timestamp()
                if (meta['task_id'] not in known_tasks or digest(artifact) != meta['content_hash']
                        or meta['redaction'] != 'passed' or observed > now + 30
                        or now - observed > self.m['evidence_requirements']['freshness_seconds']):
                    raise DiscoveryError('evidence_integrity')
                clean.append(meta)
        except DiscoveryError:
            clean = []
            self.stop_reason = 'cancelled' if self.stop_reason == 'cancelled' else 'safety_stop'
            self.gap('Evidence integrity failed; invalid artifacts are quarantined from projection.', severity='blocking', area='integrity')
        clean_ids = {e['id'] for e in clean}
        required = set(self.m['evidence_requirements']['required_types'])
        present = {e['type'] for e in clean if e['confidence'] >= self.m['evidence_requirements']['minimum_confidence']}
        for missing in sorted(required - present):
            self.gap('Required evidence type is missing: ' + missing + '.', severity='blocking', area='requirements')
        for i, state in self.states.items():
            if state not in {'SUCCEEDED', 'PARTIALLY_SUCCEEDED'}:
                self.gap('An objective task did not produce its expected output.', [i],
                         'blocking' if self.tasks[i]['critical'] else 'material', 'tasks')
        usable = any(e['type'] in {'page', 'structure'} for e in clean)
        severity = 'blocking' if any(g['severity'] == 'blocking' for g in self.gaps) else 'material' if any(g['severity'] == 'material' for g in self.gaps) else 'minor' if self.gaps else 'none'
        outcome = ('cancelled' if self.stop_reason == 'cancelled' else 'complete' if usable and severity in {'none', 'minor'}
                   and required <= present and all(self.states.get(i) == 'SUCCEEDED' for i, t in self.tasks.items() if t['critical'])
                   else 'partial' if usable else 'failed')
        c = self.store.counters(self.run_id)
        result = {'version': '1.0', 'kind': 'discovery_result', 'request_id': self.m['request_id'],
                  'run_id': self.run_id, 'outcome': outcome, 'terminal_reason': self.stop_reason or 'queue_exhausted',
                  'tasks': [{'id': alias(i), 'state': self.states[i], 'reason': self.reasons[i],
                             'evidence_ids': [e for e in self.task_evidence.get(i, []) if e in clean_ids]} for i in self.graph.order],
                  'evidence': clean, 'gaps': self.gaps,
                  'coverage': {'score': len(required & present) / max(1, len(required)),
                               'denominator': 'Required evidence types within observed approved generic static routes; not universal website coverage.',
                               'high_priority_remaining': sum(t['priority'] >= 80 and self.states[i] not in {'SUCCEEDED', 'PARTIALLY_SUCCEEDED'} for i, t in self.tasks.items()),
                               'plateau': self.plateau},
                  'confidence': min((e['confidence'] for e in clean if e['type'] in {'page', 'structure'}), default=0),
                  'limitation_severity': severity, 'knowledge_ref': None,
                  'recommended_next_action': 'Review material gaps; use existing separately approved browser tools for rendered/authenticated state.' if self.gaps else 'Use these evidence-backed static findings; saving knowledge requires separate local consent.',
                  'metrics': {'planning_turns': 1, 'replanning_turns': 0,
                              'http_tasks': sum(t['worker'] == 'http' for t in self.tasks.values()),
                              'browser_tasks': 0, 'retries': c['retries'],
                              'duration_seconds': max(0, time.time() - self.started),
                              'requests': c['requests'], 'duplicates_avoided': c['duplicates_avoided']}}
        return validate_contract(result, 'discovery_result')

    async def run(self):
        active = {}
        pending = set(self.graph.order)
        try:
            while pending or active:
                if cancelled(self.context):
                    self.stop_reason = 'cancelled'
                if (time.time() >= self.started + self.m['budgets']['run_seconds'] - 1
                        or time.monotonic() >= self.monotonic_deadline):
                    self.stop_reason = self.stop_reason or 'runtime_limit'
                if self.stop_reason:
                    if self.stop_reason == 'cancelled':
                        self.store.cancel(self.run_id)
                    for future in active:
                        future.cancel()
                    await asyncio.gather(*active, return_exceptions=True)
                    break
                for i in self.graph.order:
                    if i not in pending:
                        continue
                    dep = self.dependency(self.tasks[i])
                    if dep == 'impossible':
                        self.store.transition(self.run_id, i, 'SKIPPED', 'dependency output unavailable')
                        self.states[i], self.reasons[i] = 'SKIPPED', 'Dependency acceptance rule could not be met.'
                        pending.remove(i)
                    elif dep == 'ready' and len(active) < self.m['budgets']['concurrency']:
                        pending.remove(i)
                        future = asyncio.create_task(self.execute_task(self.tasks[i]))
                        active[future] = i
                if not active:
                    if pending:
                        self.stop_reason = 'critical_failure'
                        self.gap('Graph could not reach a terminal dependency barrier.', severity='blocking')
                    break
                done, _ = await asyncio.wait(active, timeout=.05, return_when=asyncio.FIRST_COMPLETED)
                for future in done:
                    i = active.pop(future)
                    try:
                        future.result()
                    except asyncio.CancelledError:
                        self.stop_reason = self.stop_reason or 'cancelled'
                    except DiscoveryError as error:
                        self.stop_reason = 'cancelled' if error.code == 'cancelled' else 'safety_stop'
                        self.gap('A fenced task commit was refused.', [i], 'blocking', 'integrity')
                    except Exception:
                        self.stop_reason = 'resource_limit'
                        self.gap('Installed worker/storage contract failed; no raw error content is exported.', [i], 'blocking', 'storage')
            # Independent local finaliser: never held hostage by aggregate edges.
            for i in self.graph.order:
                if i not in self.states:
                    row = self.store.task(self.run_id, i)
                    state = 'CANCELLED' if self.stop_reason == 'cancelled' else 'FAILED' if row['state'] == 'RUNNING' else 'SKIPPED'
                    if row['state'] not in TERMINAL:
                        try:
                            self.store.transition(self.run_id, i, state, 'independent finalisation')
                        except DiscoveryError:
                            pass
                    self.states[i], self.reasons[i] = state, 'Independent finaliser retained diagnostics after a bounded stop.'
            full = self.result()
            self.store.finish(self.run_id, full)
            artifacts = self.store.evidence(self.run_id) if self.stop_reason != 'safety_stop' else []
            cache = self.context.get('discovery_runs')
            if type(cache) is dict:
                while len(cache) >= 3:
                    cache.pop(next(iter(cache)))
                cache[self.run_id] = {'graph': self.graph, 'result': deepcopy(full),
                                      'artifacts': deepcopy(artifacts), 'created': self.started,
                                      'binding_partition': self.binding_partition}
            return project_result(full, min(self.m['final_requirements']['max_model_bytes'],
                                           min(12000, max(1000, config_value(self.context.get('config', {}), 'max_output_chars', 12000))) - 600))
        except asyncio.CancelledError:
            self.stop_reason = 'cancelled'
            self.store.cancel(self.run_id)
            for future in active:
                future.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            for i in self.graph.order:
                if i not in self.states:
                    self.states[i], self.reasons[i] = 'CANCELLED', 'Cancellation fenced this nonterminal task; prior clean checkpoints are retained.'
            full = self.result()
            self.store.finish(self.run_id, full)
            return project_result(full, min(self.m['final_requirements']['max_model_bytes'],
                                           min(12000, max(1000, config_value(self.context.get('config', {}), 'max_output_chars', 12000))) - 600))
        except Exception:
            for future in active:
                future.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            try:
                self.store.fail_run(self.run_id)
            except Exception:
                # A storage fault may prevent a durable outcome; never claim one.
                pass
            raise
        finally:
            for future in active:
                if not future.done():
                    future.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            await self.reader.close()
            try:
                if self.store.run(self.run_id)['state'] != 'TERMINAL':
                    self.store.fail_run(self.run_id)
            except Exception:
                # A failed store cannot prove durable completion; caller receives failure.
                pass
            self.store.close()


def project_result(result, budget):
    value = deepcopy(result)
    if len(canonical(value).encode()) <= budget:
        return value
    # Never drop material gaps or convert a partial result into completion. A
    # compact alternate projection is explicitly not a full result-schema object.
    projection = {'kind': 'discovery_projection', 'version': '1.0',
                  'request_id': result['request_id'], 'run_id': result['run_id'],
                  'outcome': result['outcome'], 'terminal_reason': result['terminal_reason'],
                  'coverage': result['coverage'], 'limitation_severity': result['limitation_severity'],
                  'metrics': result['metrics'], 'knowledge_ref': result['knowledge_ref'],
                  'material_gap_count': sum(g['severity'] in {'material', 'blocking'} for g in result['gaps']),
                  'evidence_count': len(result['evidence']), 'full_result_retained': True,
                  'truncated': True,
                  'instruction': 'This is a bounded projection, not full evidence. Missing details are unknown; no completion inference from omissions.',
                  'gaps': deepcopy(result['gaps']), 'evidence_refs': [e['id'] for e in result['evidence']],
                  'recommended_next_action': result['recommended_next_action']}
    while len(canonical(projection).encode()) > budget and projection['evidence_refs']:
        projection['evidence_refs'].pop()
    if len(canonical(projection).encode()) > budget:
        projection['gaps'] = [{'area': 'projection', 'severity': 'blocking',
                               'reason': 'Material gap details exceed the model budget; inspect the locally retained approved result before drawing conclusions.',
                               'affected_tasks': [], 'next_action': 'new_request'}]
        projection['outcome'] = 'incomplete' if result['outcome'] != 'cancelled' else 'cancelled'
        projection['limitation_severity'] = 'blocking'
    if len(canonical(projection).encode()) > budget:
        projection = {k: projection[k] for k in ('kind', 'version', 'run_id', 'request_id', 'outcome', 'terminal_reason', 'truncated', 'material_gap_count', 'gaps')}
    return projection


async def execute_discovery(name, args, context):
    graph = validate_discovery(name, args, context)
    if name == 'discovery.shadow':
        return {'status': 'compiled_shadow', 'request_id': graph.manifest['request_id'],
                'manifest_sha256': graph.digest, 'tasks': len(graph.order),
                'workers': sorted(INSTALLED_WORKERS), 'network_requests': 0,
                'authority_granted': False, 'persistent_records_written': False}
    reviewed = prepare_discovery(args, context)
    if (context.get('approved') is not True or not context.get('approval_hash')
            or context.get('discovery_reviewed') != reviewed):
        raise DiscoveryError('approval_required', '$', 'Exact current local approval and prepared scope must match before any dispatch')
    if cancelled(context):
        raise DiscoveryError('cancelled')
    context['discovery_effects_started'] = True
    return await Engine(graph, context).run()
