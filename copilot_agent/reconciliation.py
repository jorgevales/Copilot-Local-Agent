"""Fresh, model-requested reconciliation of navigation-only browser effects.

Only hashes of page state enter the retained ledger. This module never navigates,
clicks, submits, or stores page URLs, titles, query values, or customer content.
"""
from __future__ import annotations

import asyncio
import hashlib
from urllib.parse import urlsplit, urlunsplit
import uuid

from .logging_utils import now
from .policy import PolicyError, URLPolicy


class ReconciliationRequired(RuntimeError):
    """A state-changing action is blocked until fresh evidence resolves its ledger entry."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise PolicyError('Reconciliation requires an HTTPS page in the approved browser scope')
    return 'https://' + parsed.hostname.lower().rstrip('.')


def _binding(browser):
    config = getattr(browser, 'config', None)
    return _hash(str(getattr(browser, 'endpoint', '')) + '|' + str(getattr(config, 'profile_dir', ''))
                 + '|' + str(id(getattr(browser, 'context', None))))


def _query_free(url):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.hostname or '', parsed.path, '', ''))


def _navigation_only(request: dict) -> bool:
    name = request.get('name')
    if name in {'browser.open', 'browser.back', 'browser.forward'}:
        return True
    if name != 'browser.plan':
        return False
    steps = request.get('arguments', {}).get('steps', [])
    if not isinstance(steps, list):
        return False
    if any(not isinstance(step, dict) or step.get('op') not in {'navigate', 'click', 'wait', 'assert', 'capture'}
           for step in steps):
        return False
    transitions = [step for step in steps if step.get('op') in {'navigate', 'click'}]
    return (bool(transitions)
            and all(step['op'] == 'navigate' or step.get('effect') == 'navigation' for step in transitions)
            and not request.get('arguments', {}).get('customer_key'))


def _owned_page(browser, request):
    page = getattr(browser, 'tool_page', None)
    if request.get('name') == 'browser.plan':
        tab_id = request.get('arguments', {}).get('tab_id', 'tab-1')
        state = getattr(browser, '_navigation_state', None)
        if state is not None:
            page = state.get('tabs', {}).get(tab_id, {}).get('page')
    if (page is None or page is getattr(browser, 'page', None)
            or page is getattr(browser, 'chat_page', None)
            or page not in getattr(browser, '_tool_pages', [])
            or page.is_closed()):
        raise PolicyError('The original owned website tab is unavailable for reconciliation')
    return page


async def capture_baseline(browser, request):
    """Capture a private pre-effect fingerprint immediately before an eligible call."""
    if not _navigation_only(request):
        return None
    try:
        page = _owned_page(browser, request)
    except PolicyError:
        if request.get('name') == 'browser.open':
            return None  # Fresh-tab bootstrap must reach new_tool_page().
        raise
    url = page.url
    title = await asyncio.wait_for(page.title(), timeout=3)
    origin = _origin(url) if url != 'about:blank' else None
    token = uuid.uuid4().hex
    browser._reconciliation_pages = getattr(browser, '_reconciliation_pages', {})
    browser._reconciliation_pages[token] = page
    return {'kind': 'navigation_only', 'page_token': token,
            'allow_origin_change': request.get('name') == 'browser.open',
            'browser_binding_sha256': _binding(browser),
            'transition_count': sum(step.get('op') in {'navigate', 'click'} for step in request.get('arguments', {}).get('steps', [])) if request.get('name') == 'browser.plan' else 1,
            'url_sha256': _hash(url), 'title_sha256': _hash(title),
            'origin_sha256': _hash(origin) if origin else None,
            'captured_at': now()}


def recover_missing_navigation(state, browser):
    """Quarantine lost navigation evidence without crediting or replaying it."""
    recovered = []
    for call_id, call in list(state.data['calls'].items()):
        baseline = call.get('reconciliation_baseline') or {}
        if call.get('status') != 'uncertain' or baseline.get('kind') != 'navigation_only':
            continue
        page = getattr(browser, '_reconciliation_pages', {}).get(baseline.get('page_token'))
        connection = getattr(browser, 'browser', None)
        disconnected = connection is not None and not connection.is_connected()
        if page is None or page.is_closed() or disconnected:
            state.quarantine_missing_navigation(call_id)
            recovered.append(call_id)
    return recovered


def navigation_scope_allows(request, browser, domains, expected_binding=None):
    """A browser grant covers navigation, never forms, scripts or downloads."""
    if (not domains or request.get('arguments', {}).get('customer_key')
            or expected_binding is not None and expected_binding != _binding(browser)):
        return False
    name, args = request.get('name'), request.get('arguments', {})
    urls = URLPolicy(domains)
    try:
        if name == 'browser.open':
            urls.resolve(args['url'])
            for host in args.get('allowed_domains', []):
                urls.resolve('https://' + host)
            return True
        page = _owned_page(browser, request)
        urls.resolve(page.url)
        if name in {'browser.back', 'browser.forward'}:
            return True
        if name == 'browser.tabs':
            if args.get('operation') == 'list':
                return True
            if args.get('operation') == 'open':
                urls.resolve(args['url'])
                return _origin(args['url']) == _origin(page.url)
            return False
        if name != 'browser.plan' or args.get('resume_token'):
            return False
        for step in args.get('steps', []):
            op = step.get('op')
            if step.get('effect') == 'consequential':
                return False
            if op in {'wait', 'assert', 'capture'}:
                continue
            if op == 'navigate':
                urls.resolve(step['url'])
                if _origin(step['url']) != _origin(page.url):
                    return False
            elif op == 'click' and step.get('effect') == 'navigation':
                continue  # Runtime still inspects consequential controls before clicking.
            else:
                return False
        return bool(args.get('steps'))
    except (PolicyError, ValueError, KeyError):
        return False


def browser_diagnostics(state, browser):
    owned = getattr(browser, '_launched_process', None)
    connection = getattr(browser, 'browser', None)
    context = getattr(browser, 'context', None)
    return {'registration': 'owned_launcher' if owned is not None else 'shared_verified_context' if context is not None else 'unavailable',
            'connected': bool(connection is not None and connection.is_connected()),
            'owned_launcher_running': owned.poll() is None if owned is not None else None,
            'owned_tabs': sum(not page.is_closed() for page in getattr(browser, '_tool_pages', [])),
            'endpoint_sha256': _hash(str(getattr(browser, 'endpoint', 'unavailable'))),
            'browser_binding_sha256': _binding(browser),
            'operations': [{'operation_id': _hash(call_id), 'tool': call.get('request', {}).get('name'),
                            'state': call['status'], 'navigation_only': (call.get('reconciliation_baseline') or {}).get('kind') == 'navigation_only',
                            'baseline_present': bool(call.get('reconciliation_baseline'))}
                           for call_id, call in state.data['calls'].items()
                           if call['status'] in {'uncertain', 'unverifiable_original_tab_missing'}]}


async def reconcile_browser_call(state, browser, call_id: str, outcome: str,
                                 observed_url: str, observed_title: str = ''):
    """Compare Copilot's requested state with a fresh local observation, then commit once."""
    if outcome not in {'completed', 'not_executed'}:
        raise ValueError('Choose completed or not_executed')
    call = state.data['calls'].get(call_id)
    if call is None:
        original = next((key for key in state.data['calls'] if _hash(key) == call_id), None)
        if original is not None:
            call_id, call = original, state.data['calls'][original]
    if call is None:
        raise ValueError('Unknown pending operation ID; use :status to list uncertain calls')
    if call.get('reconciliation'):
        if (call['reconciliation']['outcome'] == outcome
                and call['reconciliation']['proposed_url_sha256'] == _hash(observed_url.strip())):
            return {'status': outcome, 'call_id': call_id, 'already_reconciled': True}
        raise ValueError('This operation was already reconciled with different evidence')
    if call.get('status') != 'uncertain':
        raise ValueError('Only an uncertain operation may be reconciled')
    baseline = call.get('reconciliation_baseline')
    if not baseline or baseline.get('kind') != 'navigation_only':
        raise ReconciliationRequired('This operation lacks a navigation-only pre-state; retain the block for manual investigation')
    if not isinstance(observed_url, str) or not observed_url.strip() or len(observed_url) > 4096:
        raise ValueError('Provide the exact observed final page URL')
    observed_url = observed_url.strip()
    if observed_url != 'about:blank':
        URLPolicy(state.data.get('approved_domains', [])).resolve(observed_url)
    if not isinstance(observed_title, str) or len(observed_title) > 300:
        raise ValueError('The optional observed page title is invalid')
    # Only the exact in-memory page controlled when the operation began can
    # establish the outcome. A coincidentally matching tab is not proof.
    page = getattr(browser, '_reconciliation_pages', {}).get(baseline['page_token'])
    if page is None or page.is_closed():
        raise ReconciliationRequired('The original owned tab is unavailable; its outcome cannot be established automatically')
    if (baseline.get('browser_binding_sha256', _binding(browser)) != _binding(browser)
            or page not in getattr(browser, '_tool_pages', [])
            or hasattr(browser, 'context') and getattr(page, 'context', None) is not browser.context):
        raise ReconciliationRequired('Browser profile, endpoint or owned-tab binding changed; reconciliation remains blocked')
    current_url = page.url
    current_title = await asyncio.wait_for(page.title(), timeout=3)
    proposal_query_free = not urlsplit(observed_url).query and not urlsplit(observed_url).fragment
    projected_match = proposal_query_free and _query_free(current_url) == observed_url
    if (current_url != observed_url and not projected_match) or (observed_title and current_title != observed_title):
        raise ReconciliationRequired('Proposed final page state conflicts with a fresh browser inspection; the operation remains blocked')
    if current_url != 'about:blank':
        current_origin = _origin(current_url)
        URLPolicy(state.data.get('approved_domains', [])).resolve(current_url)
        if baseline['origin_sha256'] and not baseline.get('allow_origin_change') and _hash(current_origin) != baseline['origin_sha256']:
            raise ReconciliationRequired('The browser is on a different website origin; the operation remains blocked')
    current_url_hash = _hash(current_url)
    current_title_hash = _hash(current_title)
    if outcome == 'completed' and current_url_hash == baseline['url_sha256']:
        raise ReconciliationRequired('The current URL still matches the pre-action page; completion is not established')
    if outcome == 'completed' and baseline.get('transition_count', 1) != 1:
        raise ReconciliationRequired('A final URL cannot establish completion of every step in this navigation plan; retain the unverified operation')
    if outcome == 'not_executed' and (current_url_hash != baseline['url_sha256']
                                      or current_title_hash != baseline['title_sha256']):
        raise ReconciliationRequired('The current page differs from the pre-action state; no-effect outcome is not established')
    proof = {'kind': 'fresh_browser_observation', 'outcome': outcome,
             'call_id_sha256': _hash(call_id), 'baseline_url_sha256': baseline['url_sha256'],
             'observed_url_sha256': current_url_hash, 'observed_title_sha256': current_title_hash,
             'proposed_url_sha256': _hash(observed_url), 'observed_at': now(),
             'observed_query_free_url_sha256': _hash(_query_free(current_url)),
             'proposal_query_free': proposal_query_free,
             'session_id': state.session_id}
    state.reconcile_call(call_id, outcome, proof=proof)
    return {'status': outcome, 'call_id': call_id, 'already_reconciled': False}
