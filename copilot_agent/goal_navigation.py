"""Goal-directed, visual continuations on existing owned browser tabs.

No model calls live here. One slice observes or executes an exact navigation-only
plan, verifies the target, and returns the next decision to the orchestrator.
All goal/website details remain in this live session; restart needs fresh evidence.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time

from .performance import trace
from .policy import PolicyError
from .web_navigation import (ASSERTIONS, IDENTITIES, KEY, _object, _step_schema,
    validate_navigation, get_navigation_page, _snapshot, _boundary, _fingerprint,
    _identity, _assertion, _install_origin_guard, _execute_plan, _same_origin, _origin,
    _check_cancelled, NavigationStop)


GOAL_SPECS = {'browser.navigate_goal': (_object({
    'task_id': KEY, 'tab_id': KEY, 'customer_key': KEY, 'identity': IDENTITIES,
    'goal': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
    'success': ASSERTIONS,
    'steps': {'type': 'array', 'items': _step_schema(), 'maxItems': 3},
    'observation_id': {'type': 'string', 'pattern': '^[a-f0-9]{64}$', 'maxLength': 64},
    'max_steps': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'max_seconds': {'type': 'integer', 'minimum': 15, 'maximum': 1800},
    'timeout_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 30},
}, ('task_id', 'goal', 'success')), 'user_approval',
    'Navigate toward one explicit goal in short visual continuations. First call without steps '
    'returns a fresh screenshot, observation_id and goal-ranked observed controls/routes. '
    'Continue using that observation_id and up to three exact navigation-only steps with '
    'postconditions. Local URL plus visible target assertions verify arrival; stop immediately '
    'on target, authentication, stale evidence, uncertainty or budgets. No broad crawl first, '
    'no automatic guessed clicks, no forms or new tabs, no nested model calls. Request another '
    'slice only from current returned evidence; final success needs current visual review.')}


def plan_arguments(args):
    """The exact plan authorized by the outer goal call; no synthesized actions."""
    return {**{k: copy.deepcopy(args[k]) for k in ('task_id', 'tab_id', 'customer_key', 'identity') if k in args},
            'steps': copy.deepcopy(args.get('steps', [])),
            'success': copy.deepcopy(args['steps'][-1]['expect']) if args.get('steps') else copy.deepcopy(args['success']),
            'max_actions': 3, 'timeout_seconds': args.get('timeout_seconds', 15)}


def validate_goal(args):
    from .protocol import validate_schema
    errors = validate_schema(args, GOAL_SPECS['browser.navigate_goal'][0])
    if errors:
        raise ValueError('; '.join(errors))
    if not args['task_id'].strip() or not args['goal'].strip() or not args['success']:
        raise ValueError('Goal navigation requires nonempty task, goal and target')
    # Unknown routes can be discovered toward exact visible target text. The
    # live owned origin is always bound; a known exact URL tightens the target.
    kinds = {a['kind'] for a in args['success']}
    if not kinds & {'visible', 'text'} or ('url' not in kinds and 'text' not in kinds):
        raise ValueError('Target needs an exact URL plus visible evidence, or exact visible text')
    if any(a['kind'] == 'text' and not a.get('value', '').strip() for a in args['success']):
        raise ValueError('Target text cannot be empty')
    check = {k: copy.deepcopy(v) for k, v in args.items() if k in ('task_id', 'tab_id', 'customer_key', 'identity')}
    check.update(steps=[{'id': 'target-check', 'op': 'assert', 'expect': args['success']}], success=args['success'])
    validate_navigation('browser.plan', check)
    if args.get('steps'):
        if not args.get('observation_id'):
            raise ValueError('Navigation steps require the returned observation_id')
        for step in args['steps']:
            if step['op'] not in {'navigate', 'click', 'wait', 'assert', 'capture'}:
                raise ValueError('Goal slices allow only navigation/read-only steps')
            if step.get('effect') not in (None, 'navigation'):
                raise ValueError('Goal slices cannot request form/search/consequential effects')
            if step.get('tab_id') not in (None, args.get('tab_id', 'tab-1')):
                raise ValueError('Goal slices stay on the bound tab')
            if not step.get('expect'):
                raise ValueError('Every goal step needs postconditions')
        validate_navigation('browser.plan', plan_arguments(args))


def page_lock(context, args):
    browser = context.get('browser')
    if browser is None:
        return asyncio.Lock()
    try:
        page = get_navigation_page(context, args.get('tab_id'))
        key = id(page)
    except Exception:
        key = 'bootstrap'
    locks = getattr(browser, '_goal_page_locks', None)
    if locks is None:
        locks = browser._goal_page_locks = {}
    return locks.setdefault(key, asyncio.Lock())


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


async def _visible_frames(page):
    """Only observed, visible, immediate same-origin frames; never cross hosts."""
    found = []
    for frame in page.main_frame.child_frames[:4]:
        if _origin(frame.url) != _origin(page.url):
            continue
        try:
            element = await frame.frame_element()
        except Exception:
            if frame.is_detached():
                continue  # An old child can linger briefly after parent navigation.
            raise
        if not await element.is_visible():
            continue
        selector = await element.evaluate("""n => {
            if(n.id)return '#'+CSS.escape(n.id);
            const parts=[];for(let p=n;p&&p.parentElement;p=p.parentElement){
              const same=[...p.parentElement.children].filter(x=>x.tagName===p.tagName);
              parts.unshift(p.tagName.toLowerCase()+':nth-of-type('+(same.indexOf(p)+1)+')');
            }return parts.join(' > ');
        }""")
        found.append((frame, selector))
    return found


async def _page_fingerprint(page):
    values = [await _fingerprint(page)]
    for frame, selector in await _visible_frames(page):
        values.append([selector, await _fingerprint(frame)])
    return _digest(values)


async def _structure(page, context):
    snapshot = await _snapshot(page, context, 80, 400)
    for frame, selector in await _visible_frames(page):
        observed = await _snapshot(frame, context, 40, 100)
        if observed['state'] not in {'ready', 'blank_page'}:
            snapshot['state'] = observed['state']
        if observed.get('boundaries'):
            snapshot['boundaries'].extend(observed['boundaries'])
        for kind in ('links', 'controls'):
            for item in observed.get(kind, []):
                item['locator']['frame_selector'] = selector
                snapshot[kind].append(item)
    snapshot['frame_coverage'] = 'At most four immediate visible same-origin frames; deeper frames need focused inspection.'
    return snapshot


def _candidates(snapshot, goal):
    words = set(re.findall(r'\w+', goal.casefold()))
    choices, seen = [], set()
    for item in snapshot.get('links', []):
        if not item.get('same_origin') or item.get('download') or item.get('document'):
            continue
        choices.append({'label': item.get('label', '')[:160], 'locator': item['locator'],
                        'url': item['url'], 'requires_locator': bool(item.get('query_omitted') or item.get('fragment_omitted'))})
    for item in snapshot.get('controls', []):
        if item.get('role') in {'button', 'tab', 'link'} and item.get('enabled'):
            if isinstance(item.get('href'), dict) and not item['href'].get('same_origin'):
                continue
            if item.get('type') in {'submit', 'password', 'file'}:
                continue
            choices.append({'label': item.get('name', '')[:160], 'locator': item['locator']})
    ranked = []
    for choice in choices:
        if re.search(r'delete|remove|sign.?out|log.?out|submit|save|purchase|confirm', choice['label'], re.I):
            continue
        key = _digest(choice['locator'])
        if key in seen:
            continue
        seen.add(key)
        choice['score'] = len(words & set(re.findall(r'\w+', (choice['label'] + ' ' + choice.get('url', '')).casefold())))
        ranked.append(choice)
    return sorted(ranked, key=lambda c: -c['score'])[:8]


async def _observe(page, context):
    from .automatic_visuals import capture_action_phase
    for _ in range(2):
        before = await _page_fingerprint(page)
        snapshot, picture = await asyncio.gather(_structure(page, context),
            capture_action_phase(page, context, 'Current goal navigation state', 'decision',
                                 str(context.get('source_call_id', 'goal'))))
        after = await _page_fingerprint(page)
        if before == after and picture is not None:
            return snapshot, after, picture
    raise NavigationStop('observation_unstable', 'A coherent current screenshot and page observation are required')


async def execute_goal(args, context):
    context['goal_effects_started'] = False
    try:
        return await _execute_goal(args, context)
    except NavigationStop as exc:
        return {'status': 'blocked', 'reason': exc.code, 'side_effects_uncertain': context['goal_effects_started']}


async def _matches(page, args, context):
    for assertion in args['success']:
        if not await _assertion(page, assertion, context):
            return False
        if assertion['kind'] == 'text' and not await _assertion(page,
                {'kind': 'visible', 'locator': assertion['locator']}, context):
            return False
    return True


async def _checked_target(page, args, context, fingerprint):
    with trace(context).span('target_verification', call_id=context.get('source_call_id')):
        if args.get('customer_key'):
            await _identity(page, args['identity'], context)
        matched = await _matches(page, args, context)
        if await _page_fingerprint(page) != fingerprint:
            raise NavigationStop('observation_unstable', 'The target changed after its visual observation')
        return matched


async def _execute_goal(args, context):
    validate_goal(args)
    if context.get('approved') is not True:
        raise PolicyError('Goal navigation requires current local authorization')
    _check_cancelled(context)
    page = get_navigation_page(context, args.get('tab_id'), args['task_id'], args.get('customer_key'))
    await _install_origin_guard(page, context, page.url)
    await _boundary(page, context)
    if args.get('customer_key'):
        await _identity(page, args['identity'], context)
    # Target URL must stay on the already approved original origin, including in
    # legacy permissive embedded sessions. This new tool never widens its scope.
    target_url = next((a['value'] for a in args['success'] if a['kind'] == 'url'), page.url)
    if _origin(target_url) != _origin(page.url):
        raise PolicyError('Goal target must be an exact absolute same-origin URL')
    _same_origin(target_url, page.url, context)
    context['goal_origin'] = page.url
    browser = context['browser']
    states = getattr(browser, '_goal_navigation', None)
    if states is None:
        states = browser._goal_navigation = {}
    binding = {k: args.get(k) for k in ('task_id', 'tab_id', 'customer_key', 'identity', 'goal', 'success')}
    binding.update(tenant=context.get('tenant_id'), namespace=context.get('site_namespace_id'), page=id(page))
    key = _digest(binding)
    record = states.get(key)
    if record is None:
        if args.get('steps'):
            raise PolicyError('Goal continuation is missing; observe the current page first')
        if len(states) >= 30:
            raise PolicyError('Goal retention limit reached; start a fresh task session')
        record = states[key] = {'started': time.monotonic(), 'actions': 0, 'visits': {}, 'observation_id': None,
            'max_steps': args.get('max_steps', 30), 'max_seconds': args.get('max_seconds', 600)}
    if (args.get('max_steps', record['max_steps']) != record['max_steps']
            or args.get('max_seconds', record['max_seconds']) != record['max_seconds']):
        raise PolicyError('Existing goal budgets cannot be changed by a continuation')
    if time.monotonic() - record['started'] >= record['max_seconds'] or record['actions'] >= record['max_steps']:
        return {'status': 'blocked', 'reason': 'goal_budget_exhausted', 'side_effects_uncertain': False}
    from .policy import config_value
    context['navigation_visual_packet'] = config_value(context.get('config', {}), 'compact_navigation', True)
    with trace(context).span('goal_observation', call_id=context.get('source_call_id')):
        snapshot, fingerprint, picture = await _observe(page, context)
    if snapshot['state'] != 'ready':
        return {'status': 'blocked', 'reason': snapshot['state'], 'side_effects_uncertain': False}
    if snapshot.get('boundaries'):
        return {'status': 'blocked', 'reason': 'unexpected_dialog', 'side_effects_uncertain': False}
    matched = await _checked_target(page, args, context, fingerprint)
    if matched:
        trace(context).record('goal_total', call_id=context.get('source_call_id'), matched=True,
            actions=record['actions'], duration_ms=(time.monotonic() - record['started']) * 1000)
        return {'status': 'target_verified', 'target_verified': True, 'goal_id': key,
                'url': snapshot['url'], 'actions': record['actions'], 'side_effects_uncertain': False,
                'visual_review_required': True, 'instruction': 'Review the current target screenshot before the final answer.'}
    result = None
    if args.get('steps'):
        if (args['observation_id'] != record['observation_id'] or fingerprint != record.get('fingerprint')):
            return {'status': 'blocked', 'reason': 'stale_observation', 'side_effects_uncertain': False,
                    'instruction': 'Observe again without steps; never replay the stale plan.'}
        if len(args['steps']) + record['actions'] > record['max_steps']:
            return {'status': 'blocked', 'reason': 'goal_budget_exhausted', 'side_effects_uncertain': False}
        # Every executable input is tied to an observed locator/route. Later
        # states within a predictable segment are still checked by exact expects.
        for step in [s for s in args['steps'] if s['op'] in {'click', 'navigate'}][:1]:
            if step['op'] == 'click' and step['locator'] not in record['locators']:
                raise PolicyError('The first action must use an actually observed control')
            if step['op'] == 'navigate' and step['url'] not in record['urls']:
                raise PolicyError('The first route must have been observed, not guessed')
        for step in args['steps']:
            if step.get('url') and _origin(step['url']) != _origin(page.url):
                raise PolicyError('Goal plans cannot cross origins')
        remaining_seconds = int(record['max_seconds'] - (time.monotonic() - record['started']))
        if remaining_seconds < 1:
            return {'status': 'blocked', 'reason': 'goal_budget_exhausted', 'side_effects_uncertain': False}
        local_plan = plan_arguments(args)
        local_plan['timeout_seconds'] = min(local_plan['timeout_seconds'], remaining_seconds)
        record['observation_id'] = None  # A continuation token is consumed once, before effects.
        with trace(context).span('goal_slice', call_id=context.get('source_call_id')):
            async def reached(current_page):
                return await _matches(current_page, args, context)
            context['goal_effects_started'] = True
            result = await _execute_plan(local_plan, context, stop_when=reached)
        record['actions'] += result['total_actions']
        if result['status'] not in {'verified', 'target_reached'}:
            return {'status': 'interrupted', 'plan': result,
                    'side_effects_uncertain': result['side_effects_uncertain'],
                    'instruction': 'Inspect and reconcile; do not automatically repeat the segment.'}
        snapshot, fingerprint, picture = await _observe(page, context)
        if snapshot['state'] != 'ready':
            return {'status': 'blocked', 'reason': snapshot['state'], 'side_effects_uncertain': False, 'plan': result}
        if snapshot.get('boundaries'):
            return {'status': 'blocked', 'reason': 'unexpected_dialog', 'side_effects_uncertain': False, 'plan': result}
        matched = await _checked_target(page, args, context, fingerprint)
        if matched:
            trace(context).record('goal_total', call_id=context.get('source_call_id'), matched=True,
                actions=record['actions'], duration_ms=(time.monotonic() - record['started']) * 1000)
            return {'status': 'target_verified', 'target_verified': True, 'goal_id': key,
                    'url': snapshot['url'], 'actions': record['actions'], 'plan': result,
                    'side_effects_uncertain': False, 'visual_review_required': True}
    record['visits'][fingerprint] = record['visits'].get(fingerprint, 0) + 1
    if record['visits'][fingerprint] > 2:
        return {'status': 'blocked', 'reason': 'no_progress', 'side_effects_uncertain': False}
    candidates = _candidates(snapshot, args['goal'])
    record.update(fingerprint=fingerprint, observation_id=_digest([key, fingerprint, time.monotonic()]),
                  locators=[c['locator'] for c in candidates], urls=[c['url'] for c in candidates if 'url' in c and not c.get('requires_locator')])
    trace(context).record('goal_observation', call_id=context.get('source_call_id'), candidates=len(candidates), matched=False)
    return {'status': 'needs_visual_decision', 'target_verified': False, 'goal_id': key,
            'observation_id': record['observation_id'], 'url': snapshot['url'],
            'headings': snapshot.get('headings', [])[:4], 'candidates': candidates,
            'frame_coverage': snapshot['frame_coverage'],
            'actions': record['actions'], 'remaining_steps': record['max_steps'] - record['actions'],
            'side_effects_uncertain': False, 'plan': result,
            'instruction': 'Read the current screenshot. Continue toward the target using observed controls '
                           'and this observation_id in an exact short plan; do not finish a whole-site crawl first.'}
