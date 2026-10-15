"""One approved login click using browser-held credentials; no credential handling."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from .policy import PolicyError, config_value
from .protocol import validate_schema
from .session_mode import discovery_mode, website_origin, website_policy
from .web_navigation import get_navigation_page, _install_origin_guard


AUTH_SPECS = {
    'browser.login_once': ({
        'type': 'object',
        'properties': {
            'tab_id': {'type': 'string', 'minLength': 1, 'maxLength': 100},
            'selector': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
        },
        'required': ['selector'], 'additionalProperties': False,
    }, 'user_approval', 'Click one uniquely identified, visible enabled Sign in/Login control once per exact origin per session. Use a CSS selector and browser-prefilled credentials or an existing authenticated session. Never reads, exports or types credentials; MFA, captcha, denial and unverified outcomes require the user. The scoped discovery session grant can authorize this single attempt; otherwise exact approval is required.'),
}


# Browser-local observations return only booleans. Input values, page text and
# account identifiers never cross into Python or the tool response.
CONTROL_STATE = r"""node => {
 const visible=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden'&&getComputedStyle(n).display!=='none';
 const login=/^(?:sign[ -]?in|log[ -]?in)(?:\s+(?:to (?:your )?account|with (?:microsoft|google|sso)))?$/i;
 const label=n=>String(n.getAttribute('aria-label')||(n.tagName==='INPUT'?n.getAttribute('value'):n.innerText)||'').trim().replace(/\s+/g,' ');
 const fields=[...(node.closest('form')||document).querySelectorAll('input')].filter(n=>visible(n)&&(
   ['password','email'].includes(n.type)||['username','current-password'].includes(n.autocomplete)||
   (['text','tel'].includes(n.type)&&(n.required||/user|login|email/i.test(n.name+' '+n.id)))));
 return {login_control:node.matches('button,a[href],input[type=submit],input[type=button],[role=button]')&&login.test(label(node)),
   fields_present:fields.length>0,fields_populated:fields.every(n=>!!n.value),
   visible:visible(node),enabled:!node.matches(':disabled')&&node.getAttribute('aria-disabled')!=='true'};
}"""

PAGE_STATE = r"""() => {
 const visible=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden'&&getComputedStyle(n).display!=='none';
 const login=/^(?:sign[ -]?in|log[ -]?in)(?:\s+(?:to (?:your )?account|with (?:microsoft|google|sso)))?$/i;
 const controls=[...document.querySelectorAll('button,a[href],input[type=submit],input[type=button],[role=button]')].filter(visible);
 const label=n=>String(n.getAttribute('aria-label')||(n.tagName==='INPUT'?n.getAttribute('value'):n.innerText)||'').trim().replace(/\s+/g,' ');
 const notices=[...document.querySelectorAll('h1,h2,label,[role=alert],[role=dialog],[data-error],.error,.alert-danger,.validation-summary-errors')].filter(visible).map(n=>String(n.innerText||''));
 const notice=notices.join(' ');
 return {
   mfa:[...document.querySelectorAll('input')].some(n=>visible(n)&&(n.autocomplete==='one-time-code'||/otp|mfa|verification.?code|security.?code/i.test(n.name+' '+n.id)))||/verification code|approve (?:the )?sign[ -]?in|multi[ -]?factor|two[ -]?(?:step|factor)|authenticator|security key|verify your identity/i.test(notice),
   captcha:[...document.querySelectorAll('iframe')].some(n=>visible(n)&&/captcha|recaptcha|hcaptcha/i.test(n.getAttribute('src')||''))||[...document.querySelectorAll('.g-recaptcha,.h-captcha,[id*=captcha i]')].some(visible)||/captcha|verify you are human|human verification|security challenge/i.test(notice),
   denied:/access denied|incorrect (?:password|username)|invalid credentials|sign[ -]?in failed|login failed|account (?:is )?locked|unauthori[sz]ed|forbidden/i.test(notice),
   credential_fields:[...document.querySelectorAll('input[type=password],input[type=email],input[autocomplete=username],input[autocomplete=current-password]')].some(visible),
   login_control:controls.some(n=>login.test(label(n))),
   authenticated_control:controls.some(n=>/^(?:sign[ -]?out|log[ -]?out)$/i.test(label(n)))
 };
}"""


def _scope(context, url):
    config = context.get('config', {})
    return website_policy(config, [*config_value(config, 'allowed_domains', []),
                                   *context.get('approved_domains', [])]).resolve(url)


def _safe_url(url):
    try:
        parsed = urlsplit(url)
        return website_origin(url) + parsed.path
    except (PolicyError, ValueError):
        return '[unavailable]'


def validate_login(args, context=None):
    errors = validate_schema(args, AUTH_SPECS['browser.login_once'][0])
    if errors:
        raise ValueError('; '.join(errors))
    if not args['selector'].strip() or any(ord(char) < 32 for char in args['selector']):
        raise ValueError('Login needs a nonempty bounded selector without control characters')
    if context is not None:
        page = get_navigation_page(context, args.get('tab_id'))
        _scope(context, page.url)


def _boundary(state):
    return next((name for name in ('mfa', 'captcha', 'denied') if state.get(name)), None)


async def execute_login(args, context):
    validate_login(args, context)
    config = context.get('config', {})
    session_authorized = discovery_mode(config) and context.get('session_login_authorized') is True
    if context.get('approved') is not True and not session_authorized:
        raise PolicyError('One login click needs the scoped session grant or exact approval')
    page = get_navigation_page(context, args.get('tab_id'))
    before_url = page.url
    origin = website_origin(before_url)
    attempts = context.setdefault('login_attempts', {})
    if not isinstance(attempts, dict):
        raise PolicyError('Session login-attempt ledger is unavailable')

    def result(reason, *, clicked=False, uncertain=False, evidence=None):
        value = {'status': 'needs_user_input', 'reason': reason,
                 'tab_id': args.get('tab_id', 'tab-1'), 'attempted': clicked,
                 'side_effects_uncertain': uncertain,
                 'url_before': _safe_url(before_url), 'url_after': _safe_url(page.url),
                 'next_action': 'Complete sign-in or MFA manually; do not replay the login click.'}
        if evidence is not None:
            value['evidence'] = evidence
        return value

    if origin in attempts:
        return result('The single login attempt for this origin was already consumed.')
    try:
        before = await asyncio.wait_for(page.evaluate(PAGE_STATE), 5)
        boundary = _boundary(before)
        if boundary:
            return result('User action required: ' + boundary + '.')
        locator = page.locator(args['selector'])
        if await locator.count() != 1:
            return result('The selector must identify exactly one login control.')
        control = await locator.element_handle()
        if control is None:
            return result('The selected login control disappeared.')
        if not await control.is_visible() or not await control.is_enabled():
            return result('The login control must be visible and enabled.')
        state = await asyncio.wait_for(control.evaluate(CONTROL_STATE), 5)
        if not state.get('login_control') or not state.get('visible') or not state.get('enabled'):
            return result('The selected control is not a visible enabled Sign in/Login action.')
        if state.get('fields_present') and not state.get('fields_populated'):
            return result('Visible credential fields are not already populated by the browser.')
        # Recheck ownership/scope immediately before installing the exact-origin
        # guard, then consume the attempt before the click can have any effect.
        if get_navigation_page(context, args.get('tab_id')) is not page or website_origin(page.url) != origin:
            return result('The website changed during login preflight.')
        _scope(context, page.url)
        await _install_origin_guard(page, context, before_url)
    except PolicyError:
        raise
    except Exception:
        return result('Login preflight could not establish a safe single control.')

    # No await between testing and setting: parallel calls share this ledger.
    if origin in attempts:
        return result('The single login attempt for this origin was already consumed.')
    if website_origin(page.url) != origin:
        return result('The website changed before the login click.')
    attempts[origin] = {'attempted': True}
    try:
        await control.click(timeout=5000, no_wait_after=True)
    except Exception:
        return result('The login click failed or its effect is unknown.', clicked=True, uncertain=True)
    try:
        for index in range(16):
            _scope(context, page.url)
            if website_origin(page.url) != origin:
                return result('Login left the approved exact origin.', clicked=True, uncertain=True)
            after = await asyncio.wait_for(page.evaluate(PAGE_STATE), 2)
            boundary = _boundary(after)
            if boundary:
                return result('User action required after login: ' + boundary + '.', clicked=True,
                              evidence={'boundary': boundary})
            authenticated = (after.get('authenticated_control') and not after.get('login_control')
                             and not after.get('credential_fields'))
            transitioned = page.url != before_url or not before.get('authenticated_control')
            if authenticated and transitioned:
                return {'status': 'completed', 'tab_id': args.get('tab_id', 'tab-1'),
                        'attempted': True, 'side_effects_uncertain': False,
                        'url_before': _safe_url(before_url), 'url_after': _safe_url(page.url),
                        'evidence': {'login_controls_absent': True, 'credential_fields_absent': True,
                                     'authenticated_signout_control_observed': True,
                                     'auth_transition_observed': True}}
            if index < 15:
                await asyncio.sleep(0.2)
    except Exception:
        return result('Login outcome could not be verified.', clicked=True, uncertain=True)
    return result('Login remains required or success could not be verified.', clicked=True, uncertain=True)
