"""Deterministic capability selection; execution stays with ToolRegistry."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .policy import PolicyError, config_value
from .rea import rea_health
from .session_mode import website_policy


ROUTING_SPECS = {'research.route': ({
    'type': 'object', 'properties': {
        'target': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
        'target_type': {'type': 'string', 'enum': ['website', 'har', 'saz', 'managed', 'go', 'rust', 'javascript']},
        'objective': {'type': 'string', 'enum': ['investigate', 'api', 'crawl', 'navigate', 'screenshot', 'script']},
        'prior_call_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'refresh': {'type': 'boolean'},
    }, 'required': ['target', 'target_type', 'objective'], 'additionalProperties': False,
}, 'read_only', 'Select the next research capability locally without executing it. Prefer healthy REA for general supported investigation; retain specialized API Anything-inspired operation tools, Crawl4AI, browser and file tools. Reuse fresh completed evidence, explain combined research and safe fallback from an actual prior result. Never grant target or execution access.')}


def _target(args, context, policy):
    if args['target_type'] == 'website':
        domains = [*config_value(context.get('config', {}), 'allowed_domains', []),
                   *context.get('approved_domains', [])]
        value = website_policy(context.get('config', {}), domains).resolve(args['target'])
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', '', ''))
    return str(policy.resolve(args['target'], must_exist=True))


def validate_route(args, context, policy):
    target = _target(args, context, policy)
    prior_id = args.get('prior_call_id')
    if prior_id:
        state = context.get('session_state')
        prior = getattr(state, 'data', {}).get('calls', {}).get(prior_id)
        if not prior or prior.get('status') not in {'completed', 'uncertain'}:
            raise PolicyError('Choose an existing completed or uncertain research call')
        if not prior.get('request', {}).get('name', '').startswith(('rea.', 'operation.', 'crawl4ai.', 'browser.')):
            raise PolicyError('The prior call must belong to a registered research capability')
        prior_result = prior.get('result', {}).get('result', {})
        recorded = prior_result.get('target')
        if not recorded:
            prior_args = prior['request'].get('arguments', {})
            recorded = prior_args.get('url') or prior_args.get('path')
            if prior['request']['name'] == 'crawl4ai.crawl':
                urls = prior_args.get('urls', [])
                recorded = urls[0] if len(urls) == 1 else None
        if recorded and recorded != target:
            # Query parameters are private request state, not routing identity.
            if args['target_type'] != 'website' or _clean_url(recorded) != target:
                raise PolicyError('Prior research evidence belongs to a different target')
        if recorded is None:
            raise PolicyError('Prior result has no locally verifiable target; choose a target-bound result')
    return target


def _clean_url(value):
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', '', ''))


def _fresh_evidence(target, selected, context, args, policy):
    calls = getattr(context.get('session_state'), 'data', {}).get('calls', {})
    now = datetime.now(timezone.utc)
    for call_id, record in reversed(list(calls.items())):
        request = record.get('request', {})
        # A later browser effect invalidates a previous page snapshot.
        if request.get('name', '').startswith('browser.') and record.get('state_changing'):
            break
        outcome = record.get('result', {})
        result = outcome.get('result', {})
        if (request.get('name') != selected or record.get('status') != 'completed'
                or outcome.get('ok') is not True or result.get('status') != 'completed'
                or result.get('target') != target or not result.get('evidence_path')
                or not result.get('evidence_sha256')):
            continue
        try:
            if args['target_type'] != 'website':
                from .rea import validate_rea
                identity_args = {'path': target, 'format' if args['target_type'] in {'har', 'saz'} else 'kind': args['target_type']}
                current = validate_rea(selected, identity_args, context, policy)['input']
                if current != result.get('provenance', {}).get('input'):
                    continue
            age = (now - datetime.fromisoformat(record['finished_at'].replace('Z', '+00:00'))).total_seconds()
            path = Path(result['evidence_path']).resolve()
            root = Path(context['session_dir']).resolve()
            from .policy import reject_path_redirection
            reject_path_redirection(path)
            if root not in path.parents or not 0 <= age <= 120 or path.stat().st_size > 8388608:
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != result['evidence_sha256']:
                continue
        except (KeyError, OSError, ValueError, PolicyError):
            continue
        return {'call_id': call_id, 'tool': selected, 'evidence_path': str(path),
                'sha256': result['evidence_sha256'], 'age_seconds': round(age, 2),
                'scope': 'same target and capability; verify the current live state before relying on navigation'}
    return None


def route_research(args, context, policy):
    target = validate_route(args, context, policy)
    config = context.get('config', {})
    health = rea_health(config)
    api = config_value(config, 'operation_reuse', False) is True
    crawl = importlib.util.find_spec('crawl4ai') is not None
    kind, objective = args['target_type'], args['objective']
    rea_tool = ('rea.inspect_page' if kind == 'website' else
                'rea.analyze_capture' if kind in {'har', 'saz'} else 'rea.analyze_artifact')
    specialized = {'api': 'operation.list' if api else 'browser.recon',
                   'crawl': 'crawl4ai.crawl' if crawl else 'browser.recon',
                   'navigate': 'browser.route', 'screenshot': 'browser.screenshot',
                   'script': 'browser.javascript'}
    alternatives = ([*(['operation.list'] if api else []),
                     *(['crawl4ai.crawl'] if crawl else []), 'browser.recon', 'browser.inspect']
                    if kind == 'website' else ['files.metadata', 'files.read'] if kind == 'javascript' else ['files.metadata', 'files.hash'])
    selected = specialized.get(objective) if kind == 'website' else None
    reason = 'A specialized tool provides direct evidence for this narrow objective.' if selected else 'Healthy REA is preferred for broad technical investigation.'
    if selected is None:
        selected = rea_tool if health['available'] else alternatives[0]
        if not health['available']:
            reason = 'REA is unavailable or disabled; use an existing capability and preserve its diagnostic.'
    state = getattr(context.get('session_state'), 'data', {})
    prior = state.get('calls', {}).get(args.get('prior_call_id'))
    blocked, prior_reference = False, None
    if prior:
        outcome = prior.get('result', {})
        prior_reference = {'call_id': args['prior_call_id'], 'tool': prior['request']['name'],
                           'status': prior['status'], 'error': outcome.get('error', {}).get('code')}
        result = outcome.get('result', {})
        blocked = (prior['status'] == 'uncertain' or result.get('side_effects_uncertain') is True
                   or outcome.get('error', {}).get('code') in {'approval_denied', 'policy_denied'})
        if blocked:
            reason = 'Reconcile uncertainty or obtain the required scope; fallback cannot bypass denial.'
        elif not outcome.get('ok'):
            candidates = [name for name in alternatives if name != prior['request']['name']]
            selected = candidates[0]
            reason = 'The prior capability did not complete; use a complementary existing capability.'
    reused = None if args.get('refresh') or blocked else _fresh_evidence(target, selected, context, args, policy)
    complementary = (['operation.list', 'operation.call', 'crawl4ai.crawl', 'browser.inspect',
                       'browser.screenshot', 'browser.documents'] if kind == 'website'
                     else ['files.hash', 'files.metadata'])
    return {'status': 'blocked' if blocked else 'reuse_available' if reused else 'planned',
            'target': target, 'target_type': kind, 'objective': objective,
            'preferred': None if blocked else selected,
            'reason': reason, 'rea': health, 'prior_attempt': prior_reference,
            'retained_evidence': reused,
            'prerequisites': ['browser.open on this approved target, then select its owned tab']
                             if selected == 'rea.inspect_page' else [],
            'alternatives': [name for name in alternatives if name != selected],
            'complementary': complementary,
            'execution': 'Copilot requests only relevant next tools through ToolRegistry; parallelize independent read-only calls, retain provenance, and stop once evidence is sufficient.',
            'limitations': ['A route is a capability preference, never execution approval.',
                           'Static file metadata is a degraded fallback and cannot replace REA semantic analysis.']}


def request_routes(text, context, policy):
    """Provide deterministic non-executing hints for explicitly named websites."""
    if not isinstance(text, str):
        return []
    objective = next((kind for pattern, kind in (
        (r'\b(?:screenshot|screen shot)\b', 'screenshot'),
        (r'\b(?:crawl|extract)\b', 'crawl'),
        (r'\b(?:api|endpoint)\b', 'api'),
        (r'\b(?:navigate|visit|open)\b', 'navigate')) if re.search(pattern, text, re.I)), 'investigate')
    routes, seen = [], set()
    for url in re.findall(r'https?://[^\s<>"\']+', text):
        url = url.rstrip('.,;!)]}')
        if url in seen:
            continue
        seen.add(url)
        try:
            routes.append(route_research({'target': url, 'target_type': 'website',
                                          'objective': objective}, context, policy))
        except (PolicyError, ValueError):
            routes.append({'status': 'scope_required', 'reason': 'An explicitly named target needs scope approval before research.'})
        if len(routes) >= 4:
            break
    return routes
