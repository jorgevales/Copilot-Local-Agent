"""Visible Edge/Copilot UI adapter with bounded waits and owned-page isolation."""
from __future__ import annotations

import asyncio
from collections import Counter
import inspect
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlparse

from . import reused_browser as edge
from .protocol import BEGIN, END


class BrowserUIError(RuntimeError):
    pass


class ExistingEdgeUnavailable(BrowserUIError):
    """A user-selected existing Edge session failed attachment verification."""


class ModelAccessError(BrowserUIError):
    """The UI reports that the chosen model is unavailable or silently fell back."""


class ModelUnavailableError(BrowserUIError):
    """A discovered model became unavailable or disabled before selection."""


def model_access_exhausted(text):
    value = ' '.join(text.lower().split())
    return ('<<<copilot_agent_v1_begin>>>' not in value and len(value) <= 1500 and
            value.startswith("you've used today's") and 'access' in value and
            'now using auto' in value and 'available again' in value)


def response_envelope_closed(text: str) -> bool:
    """Recognize a complete wire envelope without parsing or validating its JSON."""
    return (text.count(BEGIN) == 1 and text.count(END) == 1
            and text.index(BEGIN) < text.index(END))


def copied_code_response(text: str, request_id: str) -> str:
    """Frame a complete current-turn JSON code block without validating its JSON."""
    if not isinstance(text, str) or not text.strip() or not request_id:
        return ''
    value = text.strip().replace('\r\n', '\n').replace('\r', '\n')
    if response_envelope_closed(value):
        body = value[value.index(BEGIN) + len(BEGIN):value.index(END)].strip()
        candidate = value
    else:
        body = value
        if body.startswith('```') and body.endswith('```'):
            lines = body.splitlines()
            if len(lines) < 3:
                return ''
            body = '\n'.join(lines[1:-1]).strip()
        candidate = BEGIN + '\n' + body + '\n' + END
    # A completed malformed object must reach protocol correction, but a partial
    # or stale clipboard value must not. Use only structural/identity checks here.
    identity = re.compile(r'"request_id"\s*:\s*' + re.escape(json.dumps(request_id)))
    stack, quoted, escaped, closed_at = [], False, False, None
    for index, char in enumerate(body):
        if closed_at is not None:
            if not char.isspace():
                return ''
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack or (char == '}' and stack[-1] != '{') or (char == ']' and stack[-1] != '['):
                return ''
            stack.pop()
            if not stack:
                closed_at = index
    if (not body.startswith('{') or quoted or escaped or stack or closed_at is None
            or not identity.search(body)):
        return ''
    return candidate


class SubmissionNotSentError(BrowserUIError):
    """The adapter failed before attempting Send; a persisted intent may be cancelled."""


class SubmissionAmbiguousError(BrowserUIError):
    """A Send click was attempted; delivery is uncertain and must never be retried."""


class CaptureTimeoutError(BrowserUIError):
    """Submission was committed, but a complete correlated response was not captured."""


def upload_alert_is_error(text: str) -> bool:
    """An informational upload/OneDrive notice is not a failed transfer."""
    context = re.search(r'\b(?:upload\w*|attachment\w*|files?)\b', text, re.I)
    failure = re.search(r"\b(?:error|failed|failure|problem|unable|cannot|could not|unsupported|incomplete|"
                        r"too large|exceeds?|blocked|rejected|not supported|isn't supported|try again|"
                        r"password protected|encrypted|must be less than)\b|reached.{0,40}\b(?:limit|maximum)\b|"
                        r"\b(?:limit|maximum).{0,40}reached", text, re.I)
    return bool(context and failure)


def composer_comparison(expected: str, actual: str) -> dict:
    """Accept JSON formatting changes only when every literal/value remains intact."""
    left, right = expected.replace('\r\n', '\n').strip(), actual.replace('\r\n', '\n').strip()
    result = {'matches': left == right, 'comparison': 'exact',
              'expected_length': len(expected), 'actual_length': len(actual),
              'expected_sha256': hashlib.sha256(expected.encode()).hexdigest(),
              'actual_sha256': hashlib.sha256(actual.encode()).hexdigest()}
    if result['matches']:
        return result
    def pairs(items):
        mapping = {}
        for key, value in items:
            if key in mapping:
                raise ValueError('Duplicate key')
            mapping[key] = value
        return mapping
    def constant(value):
        raise ValueError('Nonfinite JSON number')
    try:
        expected_value = json.loads(left, object_pairs_hook=pairs, parse_constant=constant)
        actual_value = json.loads(right, object_pairs_hook=pairs, parse_constant=constant)
        canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        result['matches'] = canonical(expected_value) == canonical(actual_value)
        result['comparison'] = 'semantic_json'
    except (ValueError, TypeError):
        result['comparison'] = 'exact_non_json'
    position = next((index for index, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
    result['first_difference'] = position
    def character_kind(value):
        if position >= len(value):
            return 'end_of_text'
        char = value[position]
        return ascii(char) if char.isspace() else 'non_whitespace'
    # Hashes/offsets and whitespace classification, never literal payload excerpts.
    result['expected_difference_kind'] = character_kind(left)
    result['actual_difference_kind'] = character_kind(right)
    return result


def model_rank(models: list[dict]) -> list[dict]:
    """Deterministic preference heuristic, not a measured cross-provider quality claim.

    Prefer the newest enabled GPT family, then deeper mode within that version.
    Other providers retain discovery order and require explicit user choice.
    GPT-first is an application preference, not a cross-provider quality claim.
    """
    def key(item):
        label = item.get("label", "").casefold()
        deeper = any(term in label for term in ("think", "deep", "reason", "sol"))
        quick = any(term in label for term in ("quick", "instant", "fast"))
        version = re.search(r'\bgpt[\s-]*(\d+(?:\.\d+)*)', label)
        numbers = tuple(int(value) for value in version[1].split('.')) if version else ()
        numbers = (numbers + (0, 0, 0))[:3]
        return (bool(item.get("enabled", True)), bool(version), numbers if version else (0, 0, 0),
                deeper and not quick if version else False)
    return sorted(models, key=key, reverse=True)


# Adapted selectors only from CDD; detection/correlation below is new.
_MESSAGE_SNAPSHOT = r"""() => {
  const state = window.__copilotLocalAgentNodes || (window.__copilotLocalAgentNodes = {ids:new WeakMap(),next:1});
  const text = (n,assistant) => {
    if (!assistant || !n.querySelector('pre,[role="group"][aria-label="Code Preview"]')) return String(n.innerText || n.textContent || '').replace(/\r\n?/g,'\n').trim();
    const clone=n.cloneNode(true);
    const originals=[...n.querySelectorAll('[role="group"][aria-label="Code Preview"]')];
    const copies=[...clone.querySelectorAll('[role="group"][aria-label="Code Preview"]')];
    for(let index=0;index<copies.length;index++) {
      const editors=originals[index]?.querySelectorAll('[role="textbox"][aria-label="Code editor"]');
      if(editors?.length!==1)return '';
      // M365 Scriptor renders code as a DIV editor, without PRE/CODE tags.
      // Read only that editor's literal rendered text, excluding sibling controls/badges.
      const raw=editors[0].innerText||editors[0].textContent||'';
      // The editor hydrates after its enclosing markers and controls appear.
      // Wait for readable code rather than accepting a temporarily empty envelope.
      if(!raw.trim())return '';
      copies[index].replaceWith(document.createTextNode('\n'+raw+'\n'));
    }
    for(const pre of [...clone.querySelectorAll('pre')]) {
      const code=pre.querySelector('code')||pre;
      // DOM code text is literal wire content; never unescape or repair JSON strings.
      const raw=code.textContent||'';
      let wrapper=pre;
      for(let depth=0;depth<3;depth++) {
        const parent=wrapper.parentElement;
        if(!parent||parent===clone||parent.querySelectorAll('pre').length!==1)break;
        const remainder=(parent.textContent||'').replace(pre.textContent||'', '').replace(/\s+/g,'').toLowerCase();
        // Only known language/copy chrome may surround this single code block.
        if(!/^(?:(?:json|copycode|copy|copied|expand|collapse|download|showmorelines|showlesslines|showmore))*$/.test(remainder))break;
        wrapper=parent;
      }
      wrapper.replaceWith(document.createTextNode('\n'+raw+'\n'));
    }
    clone.querySelectorAll('button,[role="button"]').forEach(n=>n.remove());
    return String(clone.textContent||'').replace(/\r\n?/g,'\n').trim();
  };
  const userSelector = '[data-testid="chatQuestion"],.fai-UserMessage,[aria-labelledby^="user-message-"],[data-testid*="userChatMessage" i],[data-testid*="user-message" i],[role="article"][data-author="user"]';
  const assistantSelector = '[data-testid="markdown-reply"],.fai-CopilotMessage__content,[data-testid="copilot-message-reply-div"],[data-testid="copilot-message-div"],[data-testid="lastChatMessage"],[data-author="assistant"],[data-message-author-role="assistant"]';
  let nodes = [...document.querySelectorAll(userSelector+','+assistantSelector)].filter(n =>
    !n.closest('[contenteditable="true"],textarea') && n.getAttribute('data-message-type') !== 'Progress');
  // Prefer narrow leaf response containers; never return a parent containing several turns.
  nodes = nodes.filter(n => !nodes.some(other => other !== n && n.contains(other)));
  nodes.sort((a,b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  return nodes.map((n,order) => {
    if (!state.ids.has(n)) state.ids.set(n,state.next++);
    const user=!!(n.matches(userSelector)||n.closest(userSelector));
    return {key:state.ids.get(n),order,role:user?'user':'assistant',text:text(n,!user)};
  });
}"""

_PICKER_RETRY_INTERVAL = .05

_RADIOS = r"""provider => [...document.querySelectorAll('[role="menuitemradio"],[role="radio"],[role="menuitem"]')]
 .filter(n => {
   if (!(n.offsetWidth || n.offsetHeight || n.getClientRects().length)) return false;
   if (provider) {
     const menu=n.closest('[role="menu"]');
     const owner=menu&&document.getElementById(menu.getAttribute('aria-labelledby'));
     for (const candidate of [n,owner].filter(Boolean)) {
       const id=candidate.getAttribute('data-testid')||candidate.getAttribute('data-test-id')||'';
       if (id.startsWith('gptSubMenuModelTrigger-')&&id!==provider) return false;
     }
   }
   if (n.matches('[role="menuitemradio"],[role="radio"]')) return true;
   const trigger=n.getAttribute('data-testid')||n.getAttribute('data-test-id')||'';
   const marker=[...n.querySelectorAll('[data-testid^="checkmark-"],[data-test-id^="checkmark-"]')]
     .map(s=>s.getAttribute('data-testid')||s.getAttribute('data-test-id'))[0];
   if (!marker) return false;
   const triggerName=trigger.split('gptSubMenuModelTrigger-').pop().toLowerCase();
   const markerName=marker.split('checkmark-').pop().toLowerCase();
   return triggerName!==markerName;
 })
 .map(n => ({label:(n.innerText || n.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim(),
 enabled:n.getAttribute('aria-disabled') !== 'true' && !n.disabled,
 checked:n.getAttribute('aria-checked') === 'true',
 test_ids:[...n.querySelectorAll('[data-testid],[data-test-id]')].map(s=>s.getAttribute('data-testid')||s.getAttribute('data-test-id'))}))"""

_ATTACHMENTS = r"""() => {
 const roots=[...document.querySelectorAll('[aria-label="Attachments"] > [data-overflow-item="true"],[aria-label="Attachments"] > div[id^="SPO_"]')];
 const buttons=[...document.querySelectorAll('button[aria-label^="Remove attachment "]')];
 const names=buttons.map(n=>n.getAttribute('aria-label').slice('Remove attachment '.length).trim());
 for(const root of roots) {
   if(root.querySelector('button[aria-label^="Remove attachment "]')) continue;
   const label=root.getAttribute('aria-label')||root.getAttribute('title')||'';
   if(label) names.push(label.replace(/^Remove attachment /,'').trim());
 }
 const root=document.querySelector('[aria-label="Attachments"]');
 return {names, busy:!!root?.querySelector('[role="progressbar"],[aria-busy="true"],svg[data-testid*="spinner" i]'),
 alerts:[...document.querySelectorAll('[role="alert"]')].filter(n=>n.offsetWidth||n.offsetHeight).map(n=>(n.innerText||'').slice(0,1000))};
}"""

_EDITOR_VALUE = r"""n => {
  if (typeof n.value === 'string') return n.value;
  let value = n.innerText || n.textContent || '';
  // Observed Lexical editor caret span: structural evidence, not blanket Unicode stripping.
  const sentinels = [...n.querySelectorAll('span[aria-hidden="true"][data-lexical-text="true"]')]
    .filter(el => el.textContent === '\u200b\u200c');
  for (let index=sentinels.length-1; index>=0; index--) {
    const suffix=sentinels[index].textContent;
    if (value.endsWith(suffix)) value=value.slice(0,-suffix.length);
  }
  return value;
}"""


def fresh_assistant(messages: list[dict], baseline: dict, user_key, request_id: str) -> str:
    """Pure correlation filter: changed assistant node after this exact committed turn."""
    user = next((item for item in messages if item["key"] == user_key and item["role"] == "user"
                 and request_id in item.get('text', '')), None)
    if user is None:
        # Copilot can replace/collapse the rendered user node after acceptance.
        # Rebind only to one unique current-request user node, never assistant/body text.
        matching = [item for item in messages if item['role'] == 'user' and request_id in item.get('text', '')]
        if len(matching) == 1:
            user = matching[0]
    if user is None:
        return ""
    candidates = [item for item in messages if item["role"] == "assistant"
                  and item["order"] > user["order"] and item.get("text")
                  and baseline.get(item["key"]) != item["text"]]
    if not candidates:
        return ""
    # Prefer a correlated envelope if there is a separate progress/reasoning node.
    correlated = [item for item in candidates if request_id in item["text"]]
    return (correlated or candidates)[-1]["text"]


def public_progress(messages: list[dict], user_key, request_id: str) -> list[dict]:
    """Select plain, user-visible interim assistant messages, excluding protocol and reasoning UI."""
    user = next((item for item in messages if item.get('key') == user_key and item.get('role') == 'user'
                 and request_id in item.get('text', '')), None)
    if user is None:
        return []
    return [item for item in messages if item.get('role') == 'assistant'
            and item.get('order', -1) > user['order'] and item.get('text')
            and BEGIN not in item['text'] and END not in item['text']]


def uploads_verified(snapshot: dict, names: list[str], send_enabled: bool) -> bool:
    """Count equality is insufficient: identity, transfer/error state and Send agree."""
    return (Counter(snapshot.get('names', [])) == Counter(names)
            and not snapshot.get('busy', True) and not snapshot.get('error', True)
            and send_enabled)


class BrowserAdapter:
    def __init__(self, config):
        self.config = config
        self.page = self.tool_page = self.browser = self.context = self.tool_context = None
        self.tool_errors = []
        self.tool_downloads = []
        self.tool_domains = {str(item).lower().rstrip('.') for item in getattr(config, 'allowed_domains', [])}
        self._tool_pages = []
        self.model_label = None
        self.models: list[dict] = []
        self._top_level_labels = set()
        self._playwright = self._manager = None
        self._exchange_lock = asyncio.Lock()
        self._preloaded_attachment_signatures = ()
        self._delivery_uncertain = False
        self._mutex = None
        self._launched_process = None
        self.last_submission = None
        self.last_diagnostics = None
        self.last_composer_comparison = None
        self.last_capture_observation = None
        self.last_interaction_readiness = {}
        self.feedback_callback = None
        self._preloaded_exchange = None
        self.startup_stage = 'not_started'

    def set_feedback(self, callback):
        self.feedback_callback = callback

    async def _feedback(self, event):
        callback = getattr(self, 'feedback_callback', None)
        if callback:
            try:
                result = callback(event)
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, 2)
            except Exception:
                pass  # Display failure cannot authorize, resend or corrupt a request.

    @property
    def endpoint(self):
        return edge.cdp_endpoint(self.config.debug_port)

    def _acquire_controller(self):
        if __import__('os').name != 'nt':
            return
        import ctypes
        import hashlib
        profile = (('endpoint:' + str(self.config.debug_port)) if getattr(self.config, '_discovered_edge_endpoint', False)
                   else str(Path(self.config.profile_dir).resolve()).casefold())
        name = 'Local\\CopilotLocalAgent_' + hashlib.sha256(profile.encode()).hexdigest()[:32]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, False, name)
        if not handle:
            raise BrowserUIError('Could not acquire the dedicated browser controller.')
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(handle)
            raise BrowserUIError('Another local agent already controls this profile and port.')
        self._mutex = (kernel, handle)

    async def _navigate_copilot(self):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        try:
            await self.page.goto(self.config.copilot_url, wait_until='domcontentloaded',
                                 timeout=int(self.config.startup_timeout * 1000))
        except PlaywrightTimeoutError:
            if self.page.is_closed():
                raise
            # A first profile launch can still be loading or awaiting sign-in.
            # Continue the separate bounded UI readiness check on this same page.
            print('[System] Copilot navigation is still loading; checking the visible UI before stopping startup.')

    async def _claim_chat_page(self):
        """Reuse Edge's initial blank tab so startup creates one Copilot tab only."""
        pages = list(getattr(self.context, 'pages', ()))
        for page in reversed(pages):
            closed = getattr(page, 'is_closed', None)
            if getattr(page, 'url', None) == 'about:blank' and not (callable(closed) and closed()):
                self.page = page
                return page
        self.page = await asyncio.wait_for(self.context.new_page(), 10)
        return self.page

    async def _claim_committed_request_page(self, request_id: str):
        """Select the one existing Copilot conversation containing a committed request."""
        if not isinstance(request_id, str) or not request_id:
            raise BrowserUIError('A committed request_id is required to resume its existing Copilot conversation.')
        matches = []
        for page in list(getattr(self.context, 'pages', ())):
            closed = getattr(page, 'is_closed', None)
            if callable(closed) and closed():
                continue
            parsed = urlparse(str(getattr(page, 'url', '')))
            if parsed.hostname != 'm365.cloud.microsoft' or not parsed.path.startswith('/chat/conversation/'):
                continue
            try:
                messages = await asyncio.wait_for(page.evaluate(_MESSAGE_SNAPSHOT), 5)
            except Exception:
                continue
            matching_users = [item for item in messages if item.get('role') == 'user'
                              and request_id in item.get('text', '')]
            if len(matching_users) > 1:
                raise BrowserUIError('The committed request appears multiple times in one Copilot conversation; recovery stopped without navigating.')
            if matching_users:
                matches.append(page)
        if len(matches) != 1:
            raise BrowserUIError('Recovery requires exactly one existing Copilot conversation containing the committed request_id; no chat was navigated.')
        self.page = matches[0]
        return self.page

    async def _connect_running_edge_fallback(self):
        """Retry verified running Edge endpoints after a failed selected route."""
        if getattr(self.config, '_new_edge_session', False):
            return None
        attempts = set()
        for round_index in range(3):
            discovered = await asyncio.to_thread(edge.discover_edge_debugging_endpoints)
            discovered.sort(key=lambda item: (item['port'] != 9222, item['port']))
            for item in discovered:
                port = item['port']
                if port == self.config.debug_port or port in attempts:
                    continue
                attempts.add(port)
                endpoint = edge.cdp_endpoint(port)
                payload = await asyncio.to_thread(edge.get_cdp_version, endpoint)
                if payload is None:
                    continue
                try:
                    edge.validate_endpoint(endpoint, payload)
                    await asyncio.to_thread(edge.validate_edge_listener, port, item.get('profile'))
                    browser = await edge.connect_bounded(
                        self._playwright, endpoint, min(12, self.config.startup_timeout),
                        initial_payload=payload)
                except edge.EndpointError:
                    continue
                self.config.debug_port = port
                self.config.attach_existing = True
                self.config._discovered_edge_endpoint = True
                if item.get('profile') is not None:
                    self.config.profile_dir = item['profile']
                print('[System] Connected to an existing verified Edge window after the initial startup route failed.')
                return browser
            if round_index < 2:
                await asyncio.sleep(.25 * (round_index + 1))
        return None

    async def _connect_direct_edge_fallback(self):
        """Retry new owned launches; keep the chosen port and exact profile."""
        if self.config.attach_existing or getattr(self.config, '_proof_exact_edge_endpoint', None):
            return None
        profile = Path(self.config.profile_dir).expanduser().resolve()
        executable = edge.find_edge_executable(self.config.edge_executable)
        if self._launched_process is not None:
            exit_code = self._launched_process.poll()
            if isinstance(exit_code, int):
                print('[System] Browser launch helper exited with code 0x' + format(exit_code & 0xffffffff, '08X') + '; trying independent launch routes.')
        for label, spelling, software_graphics in edge.direct_profile_candidates(profile):
            print('[System] Browser startup retry: ' + label + '; keeping the same profile and debugging port.')
            # An owner failure can leave a usable Edge child behind. Recheck it
            # before launching, and prove its identity before attaching.
            payload = await asyncio.to_thread(edge.get_cdp_version, self.endpoint)
            try:
                if payload is None:
                    self._launched_process = await asyncio.to_thread(edge.launch_edge_direct,
                        executable, self.config.debug_port, spelling, software_graphics=software_graphics)
                def verify():
                    edge.validate_launched_endpoint(self.config.debug_port, profile, self._launched_process)
                return await edge.connect_bounded(self._playwright, self.endpoint,
                    min(20, self.config.startup_timeout), process=self._launched_process,
                    initial_payload=payload, endpoint_validator=verify, endpoint_wait_timeout=10)
            except (edge.EndpointError, OSError):
                continue
        return None

    @staticmethod
    def _authentication_required(url):
        host = (urlparse(str(url)).hostname or '').casefold().rstrip('.')
        return host == 'login.microsoftonline.com' or host == 'login.live.com' or host.endswith('.login.microsoftonline.com')

    async def start(self, resume_request_id=None):
        if not self.config.visible:
            raise BrowserUIError('This adapter supports visible Edge only; hidden/headless operation is unsupported.')
        parsed = urlparse(self.config.copilot_url)
        if parsed.scheme != 'https' or parsed.hostname != 'm365.cloud.microsoft':
            raise BrowserUIError('Copilot control URL must use https://m365.cloud.microsoft/.')
        self.startup_stage = 'controller'
        try:
            self._acquire_controller()
            self.startup_stage = 'endpoint_probe'
            profile = Path(self.config.profile_dir).expanduser().resolve()
            exact_endpoint = getattr(self.config, '_proof_exact_edge_endpoint', None)

            def verify_exact_endpoint():
                if exact_endpoint is None:
                    return
                if (not isinstance(exact_endpoint, tuple) or len(exact_endpoint) != 2
                        or type(exact_endpoint[0]) is not int or not isinstance(exact_endpoint[1], str)
                        or self.config.debug_port != exact_endpoint[0]
                        or os.path.normcase(str(Path(self.config.profile_dir).expanduser().resolve()))
                           != os.path.normcase(str(Path(exact_endpoint[1]).expanduser().resolve()))
                        or not self.config.attach_existing):
                    raise BrowserUIError('The proof requires its exact existing Edge port and dedicated profile; no alternate listener may be used.')

            verify_exact_endpoint()
            payload = await asyncio.to_thread(edge.get_cdp_version, self.endpoint)
            if payload is not None:
                edge.validate_endpoint(self.endpoint, payload)
                if not self.config.attach_existing:
                    raise BrowserUIError('This port already has an Edge session. Enable explicit existing-session attachment or choose another port.')
                if getattr(self.config, '_discovered_edge_endpoint', False):
                    await asyncio.to_thread(edge.validate_edge_listener, self.config.debug_port)
                elif self._launched_process is not None:
                    await asyncio.to_thread(edge.validate_launched_endpoint, self.config.debug_port, profile,
                                            self._launched_process)
                else:
                    await asyncio.to_thread(edge.validate_profile_ownership, self.config.debug_port, profile)
            else:
                if self.config.attach_existing:
                    raise BrowserUIError('No existing dedicated Edge debugging session was found on this port.')
                executable = edge.find_edge_executable(self.config.edge_executable)
                print('[System] Starting a visible Edge window with the dedicated agent profile.')
                self.startup_stage = 'edge_launch'
                try:
                    self._launched_process = edge.launch_edge(executable, self.config.debug_port, profile)
                except (edge.EndpointError, OSError):
                    if edge.remote_debugging_blocked():
                        raise
                    for label, spelling, software_graphics in edge.direct_profile_candidates(profile):
                        try:
                            print('[System] Initial launch failed; retrying ' + label + '.')
                            self._launched_process = await asyncio.to_thread(edge.launch_edge_direct,
                                executable, self.config.debug_port, spelling, software_graphics=software_graphics)
                            break
                        except (edge.EndpointError, OSError):
                            continue
                    else:
                        raise BrowserUIError('All Edge launch routes failed before a debugging endpoint opened; profile files were retained.')
            from playwright.async_api import async_playwright
            self.startup_stage = 'playwright_start'
            self._manager = async_playwright()
            self._playwright = await self._manager.start()
            self.startup_stage = 'cdp_connection'
            verified_launch_port = None
            def verify_launched_endpoint():
                nonlocal verified_launch_port
                edge.validate_launched_endpoint(self.config.debug_port, profile, self._launched_process)
                verified_launch_port = self.config.debug_port
            try:
                self.browser = await edge.connect_bounded(self._playwright, self.endpoint, self.config.startup_timeout,
                                                          process=self._launched_process,
                                                          initial_payload=payload,
                                                          endpoint_validator=(verify_launched_endpoint
                                                                              if self._launched_process is not None else None),
                                                          endpoint_wait_timeout=(15 if self._launched_process is not None else None))
            except edge.EndpointError as exc:
                if exact_endpoint is not None:
                    raise BrowserUIError('The exact dedicated Edge listener could not be attached; no fallback port or profile was used.') from exc
                if getattr(self.config, '_new_edge_session', False):
                    self.browser = await self._connect_direct_edge_fallback()
                    if self.browser is None:
                        raise BrowserUIError('The new Edge session failed all launch routes. Profile files were retained; no unrelated session was reused.') from exc
                else:
                    if getattr(self.config, '_user_selected_existing', False):
                        raise ExistingEdgeUnavailable('The selected existing Edge session could not be attached.') from exc
                    self.browser = await self._connect_running_edge_fallback()
                    if self.browser is None and self._launched_process is not None:
                        self.browser = await self._connect_direct_edge_fallback()
                    if self.browser is None:
                        raise
            verify_exact_endpoint()
            if exact_endpoint is not None:
                await asyncio.to_thread(edge.validate_profile_ownership, self.config.debug_port, profile)
            # Prove the fresh listener belongs to this Popen process; fall back to
            # exact profile inspection if Edge handed off to a different process.
            if __import__('os').name == 'nt':
                if getattr(self.config, '_discovered_edge_endpoint', False):
                    await asyncio.to_thread(edge.validate_edge_listener, self.config.debug_port)
                elif verified_launch_port == self.config.debug_port:
                    pass  # Ownership was proved before Playwright attached to this endpoint.
                else:
                    await asyncio.to_thread(edge.validate_launched_endpoint, self.config.debug_port, profile,
                                            self._launched_process)
            self.startup_stage = 'page_setup'
            self.context = self.browser.contexts[0]
            # Grant this before opening Copilot so Edge never interrupts an
            # exchange with its clipboard permission confirmation dialog.
            if not getattr(self.config, '_automation_test_mode', False):
                await asyncio.wait_for(
                    self.context.grant_permissions(
                        ['clipboard-read', 'clipboard-write'],
                        origin='https://m365.cloud.microsoft'),
                    10)
            if resume_request_id:
                self.startup_stage = 'committed_request_lookup'
                await self._claim_committed_request_page(resume_request_id)
                self.page.set_default_timeout(5000)
                if hasattr(self.page, 'bring_to_front'):
                    await self.page.bring_to_front()
                self.startup_stage = 'ready'
                print('[System] Reattached to the exact existing Copilot conversation for session resume; no new chat was opened.')
                self.tool_context = self.context
                self.tool_page = None
                return self
            await self._claim_chat_page()
            # Website tool tabs are created lazily by browser.open. Starting one
            # here leaves an unexplained blank tab beside every Copilot chat.
            self.tool_context = self.context
            self.tool_page = None
            self.page.set_default_timeout(5000)
            self.startup_stage = 'copilot_navigation'
            await self._navigate_copilot()
            await self.page.bring_to_front()
            print('[System] Edge is open. Complete Microsoft 365 sign-in there if prompted.')
            self.startup_stage = 'copilot_ui_readiness'
            deadline = time.monotonic() + self.config.startup_timeout
            auth_deadline = None
            auth_notice_sent = False
            while True:
                if self._authentication_required(self.page.url):
                    # Keep this exact visible page and profile alive while the user
                    # completes interactive MFA/sign-in. Never automate credentials.
                    if auth_deadline is None:
                        auth_deadline = time.monotonic() + max(900, self.config.startup_timeout)
                    deadline = auth_deadline
                    if not auth_notice_sent:
                        print('[System] Microsoft sign-in is required. Complete sign-in and any MFA in this Edge window; startup will resume here.')
                        auth_notice_sent = True
                if time.monotonic() >= deadline:
                    break
                editor = await self._editor(required=False)
                if (urlparse(self.page.url).hostname == 'm365.cloud.microsoft' and editor is not None
                        and await self._visible(edge.PICKER_SELECTOR) is not None):
                    if any(item['role'] == 'user' for item in await self._evaluate(_MESSAGE_SNAPSHOT)):
                        raise BrowserUIError('Copilot opened an existing conversation. A fresh independent chat is required before initialization.')
                    self.startup_stage = 'ready'
                    return self
                await asyncio.sleep(self.config.poll_interval)
            if auth_deadline is not None:
                raise BrowserUIError('Copilot did not become ready after the interactive sign-in window expired. The Edge profile and session records are preserved; retry setup to resume.')
            raise BrowserUIError('Copilot editor/model picker was not ready before startup_timeout. Check sign-in/account access, then retry setup.')
        except Exception as exc:
            retry_as_new = (getattr(self.config, '_user_selected_existing', False)
                            and self.startup_stage in {'controller', 'endpoint_probe', 'cdp_connection'})
            await self.diagnostics('startup')
            await self.close()
            if retry_as_new:
                raise ExistingEdgeUnavailable(
                    'The selected existing Edge session could not be verified at attachment.') from exc
            raise

    async def _evaluate(self, script, arg=None):
        for attempt in range(2):
            try:
                return await asyncio.wait_for(self.page.evaluate(script, arg), timeout=5)
            except Exception as exc:
                if type(exc).__name__ != 'TimeoutError' or attempt == 1: raise
                await asyncio.sleep(min(.25, self.config.poll_interval))

    async def _configure_tool_context(self, page=None):
        # Keep legacy callers working by configuring the dedicated tool page
        # when available; never attach website guards to the Copilot chat page.
        page = (self.tool_page or self.page) if page is None else page
        if page is None or (callable(getattr(page, 'is_closed', None)) and page.is_closed()):
            raise BrowserUIError('A live owned page is required to configure website tools.')
        from .policy import URLPolicy, PolicyError

        owned_contexts = tuple(context for context in (self.context, self.tool_context) if context is not None)
        if page is self.page or page.context not in owned_contexts:
            raise BrowserUIError('Only a newly owned tool tab may receive website guards.')
        if page in self._tool_pages:
            return
        self._tool_pages.append(page)

        async def guard(route):
            try:
                URLPolicy(self.tool_domains).resolve(route.request.url)
            except (PolicyError, ValueError):
                self.tool_errors.append({'type': 'blocked_request', 'url': self._safe_url(route.request.url)})
                await route.abort('blockedbyclient')
            else:
                await route.continue_()

        await page.route('**/*', guard)
        if hasattr(page, 'route_web_socket'):
            async def websocket_guard(route):
                self.tool_errors.append({'type': 'blocked_websocket', 'url': self._safe_url(route.url)})
                await route.close()
            await page.route_web_socket('**/*', websocket_guard)
        # Popup creation is not a reviewed tool operation. Explicit browser
        # tabs are opened by the orchestrator after its URL/approval checks.
        await page.add_init_script('window.open = () => null;')

        def register():
            def error(exc):
                self.tool_errors.append({'type': 'page_error', 'message': 'JavaScript error observed on owned tool page'})
            def failed(request):
                self.tool_errors.append({'type': 'request_failed', 'url': self._safe_url(request.url),
                                         'failure': str(request.failure or '')[:100]})
            async def download(item):
                grants = getattr(self, '_approved_web_downloads', {}).get(page, set())
                allowed = item.url in grants
                if allowed:
                    grants.discard(item.url)
                self.tool_downloads.append({'url': self._safe_url(item.url), 'suggested_filename': Path(item.suggested_filename).name,
                                            'saved': False, 'status': 'approved_pending_verification' if allowed else 'cancelled_by_policy'})
                if not allowed:
                    await item.cancel()
            async def check_navigation(frame):
                if frame != page.main_frame or frame.url == 'about:blank':
                    return
                try:
                    URLPolicy(self.tool_domains).resolve(frame.url)
                except (PolicyError, ValueError):
                    self.tool_errors.append({'type': 'blocked_navigation', 'url': self._safe_url(frame.url)})
                    # Close this owned popup/page, preserving all files and original tabs.
                    await page.close()
            page.on('pageerror', error)
            page.on('requestfailed', failed)
            page.on('download', download)
            page.on('framenavigated', check_navigation)
        register()

    async def new_tool_page(self):
        if self.context is None:
            raise BrowserUIError('The verified Edge context is unavailable.')
        if sum(not p.is_closed() for p in self._tool_pages) >= 6:
            raise BrowserUIError('Owned tool-tab limit reached.')
        page = await asyncio.wait_for(self.context.new_page(), 10)
        try:
            await self._configure_tool_context(page)
            page.set_default_timeout(5000)
            return page
        except Exception:
            await page.close()
            raise

    async def focus_chat(self):
        if self.page is not None and not self.page.is_closed():
            await self.page.bring_to_front()

    def authorize_tool_domain(self, domain):
        """Extend only the owned tool browser after an explicit domain approval."""
        self.tool_domains.add(str(domain).lower().rstrip('.'))

    @staticmethod
    def _safe_url(url):
        parsed = urlparse(url)
        return f'{parsed.scheme}://{parsed.hostname or ""}{parsed.path}'[:500]

    async def _visible(self, selector):
        locator = self.page.locator(selector)
        for index in range(min(await locator.count(), 30)):
            item = locator.nth(index)
            if await item.is_visible():
                return item
        return None

    async def _editor(self, required=True):
        for selector in edge.EDITOR_SELECTORS:
            found = await self._visible(selector)
            if found is not None:
                return found
        if required:
            raise BrowserUIError('The Copilot composer is unavailable; check sign-in/account access.')
        return None

    async def _open_picker(self):
        deadline = time.monotonic() + 5
        next_click = 0
        click_attempts = 0
        while time.monotonic() < deadline:
            if await self._evaluate(r"""() => [...document.querySelectorAll('[role="menuitemradio"],[role="radio"],[role="menuitem"][aria-checked],[data-testid^="gptSubMenuModelTrigger-"],[data-test-id^="gptSubMenuModelTrigger-"]')].some(n=>(n.offsetWidth||n.offsetHeight||n.getClientRects().length))"""):
                return
            if time.monotonic() >= next_click:
                # Copilot can expose the button before its click handler hydrates.
                # Re-find it after rerenders and retry only while options are absent.
                picker = await self._visible(edge.PICKER_SELECTOR)
                if picker is not None:
                    try:
                        if click_attempts % 3 == 0:
                            await picker.press('ArrowDown', timeout=1000)
                        elif click_attempts % 3 == 1:
                            await picker.click(timeout=1000)
                        else:
                            await picker.press('Enter', timeout=1000)
                    except Exception as exc:
                        if type(exc).__name__ != 'TimeoutError':
                            raise
                    click_attempts += 1
                next_click = time.monotonic() + .25
            await asyncio.sleep(_PICKER_RETRY_INTERVAL)
        raise BrowserUIError('The model picker did not render visible options within its bounded wait.')

    async def _providers(self):
        return await self._evaluate(r"""() => [...document.querySelectorAll('[data-testid^="gptSubMenuModelTrigger-"],[data-test-id^="gptSubMenuModelTrigger-"]')]
          .filter(n=>{
            if (!(n.offsetWidth||n.offsetHeight||n.getClientRects().length)||n.getAttribute('aria-disabled')==='true'||n.disabled) return false;
            return n.getAttribute('aria-haspopup')==='menu'||!n.querySelector('[data-testid^="checkmark-"],[data-test-id^="checkmark-"]');
          }).map(n=>({id:n.getAttribute('data-testid')||n.getAttribute('data-test-id'), label:(n.innerText||'').replace(/\s+/g,' ').trim(), submenu:n.getAttribute('aria-haspopup')==='menu'}))""")

    async def _open_provider(self, trigger, label=None):
        await self._open_picker()
        find_and_open = r"""({id,label}) => {
          const norm=n=>(n.innerText||n.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim();
          const candidates=[...document.querySelectorAll('[data-testid],[data-test-id]')].filter(n=>
            (n.getAttribute('data-testid')===id||n.getAttribute('data-test-id')===id)
            && (n.offsetWidth||n.offsetHeight||n.getClientRects().length));
          const providers=candidates.filter(n=>n.getAttribute('aria-haspopup')==='menu'
            || !n.querySelector('[data-testid^="checkmark-"],[data-test-id^="checkmark-"]'));
          const matches=providers.length?providers:candidates.filter(n=>!label||norm(n)===label);
          const n=matches.length===1?matches[0]:null;
          if(!n || !(n.offsetWidth||n.offsetHeight)) return false;
          if(n.getAttribute('aria-expanded')!=='true') n.click(); return true;
        }"""
        deadline = time.monotonic() + 5
        opened = False
        while time.monotonic() < deadline:
            opened = await self._evaluate(find_and_open, {'id': trigger, 'label': label})
            if opened:
                break
            await asyncio.sleep(_PICKER_RETRY_INTERVAL)
        if not opened:
            raise BrowserUIError('The discovered model provider menu is no longer available.')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            radios = await self._evaluate(_RADIOS, trigger)
            if any(item['label'] not in self._top_level_labels for item in radios):
                return
            await asyncio.sleep(_PICKER_RETRY_INTERVAL)
        raise BrowserUIError('The model provider submenu did not render its options within the bounded wait.')

    async def discover_models(self) -> list[dict]:
        try:
            await self._open_picker()
            providers = []
            top_level = []
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                providers = await self._providers()
                top_level = await self._evaluate(_RADIOS)
                if providers or top_level:
                    break
                await asyncio.sleep(_PICKER_RETRY_INTERVAL)
            entries = [{**item, 'provider': 'Copilot', 'provider_trigger': None}
                       for item in top_level]
            self._top_level_labels = {item['label'] for item in entries}
            for provider in providers:
                if not provider.get('submenu'):
                    await self.page.keyboard.press('Escape')
                    await self.page.keyboard.press('Escape')
                await self._open_provider(provider['id'], provider['label'])
                name = provider['id'].split('gptSubMenuModelTrigger-', 1)[-1]
                entries.extend({**item, 'provider': name, 'provider_trigger': provider['id'],
                                'provider_label': provider['label']}
                               for item in await self._evaluate(_RADIOS, provider['id'])
                               if item['label'] not in self._top_level_labels)
            unique = {}
            for item in entries:
                if item['label']:
                    unique[(item['provider'], item['label'])] = item
            self.models = list(unique.values())
            if not any(item['enabled'] for item in self.models):
                raise BrowserUIError('No enabled model radio options were discovered in this account.')
            return self.models
        except Exception:
            await self.diagnostics('model_discovery')
            raise
        finally:
            if self.page:
                await self.page.keyboard.press('Escape')
                await self.page.keyboard.press('Escape')

    async def discover_models_on_auxiliary_page(self) -> list[dict]:
        """Compatibility entry point; discovery stays on the single chat tab."""
        return await self.discover_models()

    async def select_model(self, label: str):
        matches = [item for item in self.models if item['label'] == label and item['enabled']]
        if len(matches) != 1:
            raise ModelUnavailableError('Choose one exact, unambiguous enabled label from the current discovered model list.')
        chosen = matches[0]
        try:
            if chosen['provider_trigger']:
                if chosen.get('provider_label'):
                    await self._open_provider(chosen['provider_trigger'], chosen['provider_label'])
                else:
                    await self._open_provider(chosen['provider_trigger'])
            else:
                await self._open_picker()
            clicked = await self._evaluate(r"""label => {
              const norm=n=>(n.innerText||n.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim();
              const matches=[...document.querySelectorAll('[role="menuitemradio"],[role="radio"],[role="menuitem"]')].filter(n=>{
                if(norm(n)!==label||!(n.offsetWidth||n.offsetHeight||n.getClientRects().length)) return false;
                if(n.matches('[role="menuitemradio"],[role="radio"]')) return true;
                const trigger=n.getAttribute('data-testid')||n.getAttribute('data-test-id')||'';
                const marker=[...n.querySelectorAll('[data-testid^="checkmark-"],[data-test-id^="checkmark-"]')]
                  .map(s=>s.getAttribute('data-testid')||s.getAttribute('data-test-id'))[0];
                return marker&&trigger.split('gptSubMenuModelTrigger-').pop().toLowerCase()!==marker.split('checkmark-').pop().toLowerCase();
              });
              if(matches.length!==1||matches[0].getAttribute('aria-disabled')==='true'||matches[0].disabled) return false;
              if(matches[0].getAttribute('aria-checked')!=='true') matches[0].click(); return true;
            }""", label)
            if not clicked:
                raise ModelUnavailableError('The discovered model became unavailable before it could be selected.')
            deadline = time.monotonic() + min(10, self.config.startup_timeout)
            while time.monotonic() < deadline:
                if chosen['provider_trigger']:
                    await self._open_provider(chosen['provider_trigger'], chosen.get('provider_label'))
                else:
                    await self._open_picker()
                radios = await self._evaluate(_RADIOS, chosen['provider_trigger'])
                if any(item['label'] == label and item['checked'] for item in radios):
                    self.model_label = label
                    observed = next(item for item in radios if item['label'] == label and item['checked'])
                    chosen = {**chosen, **observed, 'checked': True, 'verified': True}
                    self.models = [chosen if item['label'] == label and item['provider'] == chosen['provider'] else item for item in self.models]
                    return chosen
                await asyncio.sleep(self.config.poll_interval)
            raise ModelUnavailableError('The selected model became unavailable before its checked state could be verified.')
        except Exception:
            await self.diagnostics('model_selection')
            raise
        finally:
            await self.page.keyboard.press('Escape')
            await self.page.keyboard.press('Escape')

    async def _stop_present(self):
        return bool(await self._evaluate(r"""() => [...document.querySelectorAll('button')].some(n=>
          (n.offsetWidth||n.offsetHeight||n.getClientRects().length)>0
          && /^(?:stop|stop generating|stop responding)$/i.test(
            (n.getAttribute('aria-label')||n.getAttribute('title')||n.innerText||'').replace(/\s+/g,' ').trim()))"""))

    async def _generation_state(self):
        """Observe the live generation control and the restored, enabled Send control."""
        stop_present = await self._stop_present()
        send = await self._visible(edge.SEND_SELECTOR)
        send_ready = bool(send is not None and await send.is_enabled())
        return stop_present, send_ready

    async def attach_files(self, paths):
        paths = list(paths)
        if len(paths) > 20:
            raise BrowserUIError('Copilot accepts at most 20 attachments; no files were uploaded.')
        if any(Path(path).suffix.casefold() == '.zip' for path in paths):
            raise BrowserUIError('ZIP files cannot be uploaded to Copilot. Select the documents inside the ZIP.')
        resolved = [Path(path).expanduser().resolve(strict=True) for path in paths]
        if not resolved:
            return
        if any(not path.is_file() for path in resolved):
            raise BrowserUIError('Every attachment must be a regular existing file.')
        names = [path.name for path in resolved]
        if len(set(names)) != len(names):
            raise BrowserUIError('Duplicate attachment basenames cannot be verified unambiguously.')
        before = await self._evaluate(_ATTACHMENTS)
        if before['names']:
            raise BrowserUIError('Composer already has attachments; refusing to replace or duplicate them.')
        inputs = self.page.locator("input[type='file']")
        if not await inputs.count():
            button = await self._visible(edge.ATTACH_SELECTOR)
            if button is None:
                raise BrowserUIError('Copilot attachment control is unavailable.')
            await button.click(timeout=3000)
            await self.page.wait_for_timeout(150)
        try:
            inputs = self.page.locator("input[type='file']")
            if await inputs.count():
                suitable = []
                for index in range(await inputs.count()):
                    item = inputs.nth(index)
                    if len(resolved) == 1 or await item.get_attribute('multiple') is not None:
                        suitable.append(item)
                if len(suitable) != 1:
                    raise BrowserUIError('Native upload input is missing or ambiguous for bulk assignment.')
                await suitable[0].set_input_files([str(path) for path in resolved], timeout=10000)
            else:
                upload = self.page.get_by_role('menuitem', name=re.compile(r'^(Upload from|Upload file|Attach file|Upload).*', re.I))
                if await upload.count() != 1:
                    raise BrowserUIError('A unique local-file upload action was not found.')
                async with self.page.expect_file_chooser(timeout=5000) as chooser_info:
                    await upload.click(timeout=3000)
                chooser = await chooser_info.value
                if len(resolved) > 1 and not chooser.is_multiple():
                    raise BrowserUIError('The native chooser does not support this bulk attachment plan.')
                await chooser.set_files([str(path) for path in resolved], timeout=10000)
            deadline = time.monotonic() + min(self.config.response_timeout, 120)
            stable = 0
            while time.monotonic() < deadline:
                snapshot = await self._evaluate(_ATTACHMENTS)
                snapshot['error'] = bool(snapshot.get('error', False) or any(upload_alert_is_error(alert) for alert in snapshot.get('alerts', [])))
                if snapshot['error']:
                    raise BrowserUIError('Copilot reported an upload/attachment error; no message was sent.')
                button = await self._visible(edge.SEND_SELECTOR)
                ready = uploads_verified(snapshot, names, button is not None and await button.is_enabled())
                stable = stable + 1 if ready else 0
                if stable >= max(3, self.config.capture_stable_samples):
                    return
                await asyncio.sleep(self.config.poll_interval)
            raise BrowserUIError('Upload did not reach exact filename, no-progress and enabled-Send verification before timeout.')
        except Exception:
            await self.diagnostics('attachment')
            raise

    @staticmethod
    def _attachment_signature(path):
        resolved = Path(path).expanduser().resolve(strict=True)
        digest = hashlib.sha256()
        with resolved.open('rb') as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return str(resolved), resolved.name, resolved.stat().st_size, digest.hexdigest()

    async def _attachment_signatures(self, paths):
        return tuple(await asyncio.gather(*(
            asyncio.to_thread(self._attachment_signature, path) for path in paths)))

    @staticmethod
    def _attachment_identities(signatures):
        return tuple((name, size, digest) for _, name, size, digest in signatures)

    async def _remove_preloaded_attachments(self):
        """Remove only the exact attachment batch prepared by this adapter."""
        if not self._preloaded_attachment_signatures:
            return
        expected = Counter(item[1] for item in self._preloaded_attachment_signatures)
        snapshot = await self._evaluate(_ATTACHMENTS)
        if Counter(snapshot.get('names', [])) != expected:
            self._preloaded_attachment_signatures = ()
            raise BrowserUIError('Prepared attachments changed in the Copilot composer; refusing an unrelated send.')
        deadline = time.monotonic() + min(15, self.config.response_timeout)
        while time.monotonic() < deadline:
            buttons = self.page.locator('button[aria-label^="Remove attachment "]')
            if not await buttons.count():
                snapshot = await self._evaluate(_ATTACHMENTS)
                if not snapshot.get('names'):
                    self._preloaded_attachment_signatures = ()
                    return
                break
            await buttons.first.click(timeout=3000)
            await asyncio.sleep(self.config.poll_interval)
        raise BrowserUIError('Prepared attachments could not be removed before the next message.')

    async def _reconcile_preloaded_attachments(self, paths):
        """Reuse an exact prepared batch or detach it before uploading a new one."""
        paths = list(paths)
        target = await self._attachment_signatures(paths) if paths else ()
        if (target and self._attachment_identities(self._preloaded_attachment_signatures)
                == self._attachment_identities(target)):
            snapshot = await self._evaluate(_ATTACHMENTS)
            button = await self._visible(edge.SEND_SELECTOR)
            if uploads_verified(snapshot, [item[1] for item in target],
                                button is not None and await button.is_enabled()):
                return
        if self._preloaded_attachment_signatures:
            await self._remove_preloaded_attachments()
        await self.attach_files(paths)

    async def preload_attachments(self, paths):
        """Upload an immutable, already-authorized batch while the next request is drafted."""
        paths = list(paths)
        async with self._exchange_lock:
            if self._delivery_uncertain:
                raise SubmissionAmbiguousError('A previous delivery remains uncertain; attachment preparation is disabled.')
            if await self._stop_present():
                raise BrowserUIError('Copilot is still generating; attachments cannot be prepared yet.')
            editor = await self._editor(required=False)
            if editor is None or str(await self._editor_text(editor) or '').strip():
                raise BrowserUIError('Copilot composer is not empty; refusing to mix prepared files with draft text.')
            signatures = await self._attachment_signatures(paths) if paths else ()
            await self._reconcile_preloaded_attachments(paths)
            self._preloaded_attachment_signatures = signatures
            return {'status': 'prepared', 'count': len(signatures),
                    'names': [item[1] for item in signatures]}

    async def _editor_text(self, editor):
        for attempt in range(2):
            try:
                return await asyncio.wait_for(editor.evaluate(_EDITOR_VALUE), timeout=5)
            except Exception as exc:
                if type(exc).__name__ != 'TimeoutError' or attempt == 1: raise
                await asyncio.sleep(min(.25, self.config.poll_interval))

    async def _expand_response_code(self, request_id):
        """Read-only expansion of the current response's own virtualized code preview."""
        group = '[role="group"][aria-label="Code Preview"]'
        roots = ('[data-testid="markdown-reply"]', '.fai-CopilotMessage__content', '[data-author="assistant"]',
                 '[data-message-author-role="assistant"]', '[data-testid="copilot-message-reply-div"]')
        groups = self.page.locator(','.join(root + ' ' + group for root in roots)).filter(has_text=request_id)
        expanded = 0
        for index in range(min(await groups.count(), 3)):
            button = groups.nth(index).get_by_role('button', name='Show more lines', exact=True)
            if await button.count() == 1 and await button.is_visible() and await button.is_enabled():
                await button.click(timeout=2000)
                expanded += 1
        return expanded

    def _response_code_groups(self, request_id):
        roots = ('[data-testid="markdown-reply"]', '.fai-CopilotMessage__content', '[data-author="assistant"]',
                 '[data-message-author-role="assistant"]', '[data-testid="copilot-message-reply-div"]')
        selector = ','.join(root + ' [role="group"][aria-label="Code Preview"]' for root in roots)
        return self.page.locator(selector).filter(has_text=request_id)

    async def _copy_response_code(self, request_id):
        """Use the accessible Copy code control attached to this turn's code block."""
        try:
            groups = self._response_code_groups(request_id)
            matches = []
            for index in range(min(await groups.count(), 10)):
                group = groups.nth(index)
                # Copilot's current Fluent button has a stable id and accessible
                # name; keep the group scope to avoid copying another response.
                button = (group.locator('#copy-button[aria-label="Copy code"]')
                          if hasattr(group, 'locator') else None)
                if button is None or await button.count() != 1:
                    button = group.get_by_role('button', name=re.compile(r'^Copy code$', re.I))
                if (await button.count() == 1 and await button.is_visible()
                        and await button.is_enabled()):
                    matches.append(button)
            if len(matches) != 1:
                return {'status':'unavailable' if not matches else 'ambiguous', 'text':''}
            await matches[0].click(timeout=3000)
            value = await asyncio.wait_for(self.page.evaluate(
                """async () => { if (!navigator.clipboard?.readText) throw new Error('clipboard unavailable'); return await navigator.clipboard.readText(); }"""), 5)
            return {'status':'copied' if isinstance(value, str) else 'clipboard_unavailable',
                    'text':value if isinstance(value, str) else ''}
        except Exception as exc:
            return {'status':'clipboard_failed', 'text':'', 'error_type':type(exc).__name__}

    async def _safe_dom_code_response(self, request_id):
        """Fallback only to a non-virtualized PRE code block scoped to this response."""
        roots = ('[data-testid="markdown-reply"]', '.fai-CopilotMessage__content', '[data-author="assistant"]',
                 '[data-message-author-role="assistant"]', '[data-testid="copilot-message-reply-div"]')
        selector = ','.join(root + ' pre' for root in roots)
        blocks = self.page.locator(selector).filter(has_text=request_id)
        ordinary = []
        for index in range(min(await blocks.count(), 10)):
            block = blocks.nth(index)
            virtual_parent = block.locator('xpath=ancestor::*[@role="group" and @aria-label="Code Preview"]')
            if await virtual_parent.count() == 0:
                ordinary.append(block)
        if len(ordinary) != 1:
            return ''
        block = ordinary[0]
        code = block.locator('code')
        source = code if await code.count() == 1 else block
        return str(await source.text_content() or '')

    async def _prepare_submission(self, text, request_id, attachments, *, require_model=True):
        if not request_id or request_id not in text:
            raise BrowserUIError('Every outbound message must contain its unique request_id.')
        if require_model and not self.model_label:
            raise BrowserUIError('Select and verify a discovered model before sending.')
        self.preparation_stage = 'generation_check'
        if await self._stop_present():
            raise BrowserUIError('Copilot is still generating; a second message cannot be sent.')
        self.preparation_stage = 'message_snapshot'
        baseline_messages = await self._evaluate(_MESSAGE_SNAPSHOT)
        baseline = {item['key']: item['text'] for item in baseline_messages}
        old_users = {item['key'] for item in baseline_messages if item['role'] == 'user'}
        if any(request_id in item['text'] for item in baseline_messages if item['role'] == 'user'):
            self._delivery_uncertain = True
            raise SubmissionAmbiguousError('This request_id is already present in the chat; refusing duplicate delivery.')
        self.preparation_stage = 'composer_lookup'
        editor = await self._editor()
        self.preparation_stage = 'composer_fill'
        await editor.fill(text, timeout=5000)
        self.preparation_stage = 'composer_verification'
        actual = await self._editor_text(editor)
        self.last_composer_comparison = composer_comparison(text, str(actual))
        if not self.last_composer_comparison['matches']:
            await self.diagnostics('composer_mismatch')
            raise BrowserUIError('The composer did not preserve the complete outbound message.')
        self.preparation_stage = 'attachment_upload'
        await self._reconcile_preloaded_attachments(attachments)
        self.preparation_stage = 'send_control_check'
        button = await self._visible(edge.SEND_SELECTOR)
        if button is None or not await button.is_enabled():
            raise BrowserUIError('The exact Send control is unavailable or disabled.')
        return baseline, old_users, button

    async def preload_exchange(self, text: str, request_id: str, attachments=()):
        """Fill and upload one exact message without sending it.

        Startup uses this while the model choice is still being presented.  A
        later exchange must match the exact payload and paths and re-verifies
        the live composer before it is allowed to click Send.
        """
        async with self._exchange_lock:
            if self._delivery_uncertain:
                raise SubmissionAmbiguousError('A previous delivery remains uncertain. Reconcile manually before a new send.')
            if self._preloaded_exchange is not None:
                raise BrowserUIError('A prepared Copilot message is already waiting to be sent.')
            if hasattr(self.page, 'bring_to_front'):
                await self.page.bring_to_front()
            baseline, old_users, _ = await self._prepare_submission(
                text, request_id, attachments, require_model=False)
            self._preloaded_exchange = {
                'text': text,
                'request_id': request_id,
                'attachments': tuple(str(Path(path).expanduser().resolve()) for path in attachments),
                'attachment_names': [Path(path).name for path in attachments],
                'baseline': baseline,
                'old_users': old_users,
            }
            return {'request_id': request_id, 'attachment_count': len(attachments)}

    async def _consume_preloaded_exchange(self, text, request_id, attachments):
        prepared = self._preloaded_exchange
        paths = tuple(str(Path(path).expanduser().resolve()) for path in attachments)
        if (prepared is None or prepared['text'] != text or prepared['request_id'] != request_id
                or prepared['attachments'] != paths):
            raise BrowserUIError('The prepared Copilot message does not match this exact submission.')
        if not self.model_label:
            raise BrowserUIError('Select and verify a discovered model before sending.')
        if await self._stop_present():
            raise BrowserUIError('Copilot is still generating; the prepared message cannot be sent.')
        messages = await self._evaluate(_MESSAGE_SNAPSHOT)
        if any(request_id in item['text'] for item in messages if item['role'] == 'user'):
            self._delivery_uncertain = True
            raise SubmissionAmbiguousError('This request_id is already present in the chat; refusing duplicate delivery.')
        editor = await self._editor()
        actual = await self._editor_text(editor)
        self.last_composer_comparison = composer_comparison(text, str(actual))
        if not self.last_composer_comparison['matches']:
            raise BrowserUIError('The prepared composer no longer contains the complete outbound message.')
        snapshot = await self._evaluate(_ATTACHMENTS)
        snapshot['error'] = bool(snapshot.get('error', False) or any(
            upload_alert_is_error(alert) for alert in snapshot.get('alerts', [])))
        button = await self._visible(edge.SEND_SELECTOR)
        if not uploads_verified(snapshot, prepared['attachment_names'],
                                button is not None and await button.is_enabled()):
            raise BrowserUIError('The prepared attachments or Send control changed before submission.')
        self._preloaded_exchange = None
        return prepared['baseline'], prepared['old_users'], button

    async def verify_interaction_ready(self, expected_model: str, request_id: str | None = None):
        """Wait for the visible chat to settle, while preserving any unsent draft."""
        started = time.monotonic()
        maximum = started + getattr(self.config, 'response_max_duration', self.config.response_timeout)
        startup_deadline = started + self.config.startup_timeout
        generation_observed = False
        progress_seen = set()
        last_progress = None
        last_state = {}
        while time.monotonic() < (maximum if generation_observed else startup_deadline):
            messages = await self._evaluate(_MESSAGE_SNAPSHOT)
            if request_id:
                users = [item for item in messages if item.get('role') == 'user'
                         and request_id in item.get('text', '')]
                if len(users) == 1:
                    interim = public_progress(messages, users[0]['key'], request_id)
                    signature = tuple((item['key'], item['text']) for item in interim)
                    if signature != last_progress:
                        generation_observed = generation_observed or bool(signature)
                        last_progress = signature
                    for item in interim:
                        identity = (item['key'], item['text'])
                        if identity not in progress_seen:
                            progress_seen.add(identity)
                            await self._feedback({'type': 'progress', 'request_id': request_id,
                                                  'message': item['text'][:1000]})
            stop_present = await self._stop_present()
            generation_observed = generation_observed or stop_present
            editor = await self._editor(required=False)
            picker = await self._visible(edge.PICKER_SELECTOR)
            editor_text = str(await self._editor_text(editor)) if editor is not None else ''
            empty = editor is not None and not editor_text.strip()
            attachments = await self._evaluate(_ATTACHMENTS) if editor is not None else {'names': [], 'busy': True}
            send = await self._visible(edge.SEND_SELECTOR) if editor is not None else None
            send_ready = bool(send is not None and await send.is_enabled())
            last_state = {'editor_visible': editor is not None, 'editor_empty': empty,
                          'model_matches': self.model_label == expected_model,
                          'picker_visible': picker is not None, 'generation_active': stop_present,
                          'send_ready': send_ready, 'attachment_count': len(attachments.get('names', [])),
                          'attachments_busy': bool(attachments.get('busy', False))}
            if (self.model_label == expected_model and editor is not None and picker is not None
                    and not stop_present and empty and not attachments.get('names')
                    and not attachments.get('busy', False)):
                return True
            if editor is not None and not empty and not stop_present and not generation_observed:
                await self.diagnostics('interaction_readiness_unsent_draft')
                raise BrowserUIError('Copilot has an unsent draft in its composer. It was left untouched; reconcile or clear that draft before sending another request.')
            await asyncio.sleep(self.config.poll_interval)
        self.last_interaction_readiness = last_state
        await self.diagnostics('interaction_readiness')
        raise BrowserUIError('Copilot Chat did not become ready within the response window. Last observed UI state: '
                             + json.dumps(last_state, ensure_ascii=False, sort_keys=True))

    async def read_reconciled_draft(self, request_id: str, expected_sha256: str) -> str:
        """Return only a hash-matching, text-only draft already proven not sent."""
        if (not isinstance(request_id, str) or not request_id
                or not isinstance(expected_sha256, str)
                or not re.fullmatch(r'[a-f0-9]{64}', expected_sha256)):
            raise BrowserUIError('A reconciled request ID and SHA-256 are required to reuse a draft.')
        if self.page is None or self.page.is_closed():
            raise BrowserUIError('The Copilot page is unavailable; the unsent draft was left untouched.')
        if self._delivery_uncertain or await self._stop_present():
            raise BrowserUIError('Copilot delivery is still uncertain or generating; the draft was not reused.')
        messages = await self._evaluate(_MESSAGE_SNAPSHOT)
        matches = [item for item in messages if item['role'] == 'user' and request_id in item.get('text', '')]
        if matches:
            raise BrowserUIError('The reconciled request is already visible in the chat; refusing to resend it.')
        editor = await self._editor(required=False)
        if editor is None:
            raise BrowserUIError('The Copilot composer is unavailable; the unsent draft was left untouched.')
        text = str(await self._editor_text(editor))
        if hashlib.sha256(text.encode()).hexdigest() != expected_sha256 or request_id not in text:
            raise BrowserUIError('The composer no longer matches the exact reconciled draft; it was left untouched.')
        attachments = await self._evaluate(_ATTACHMENTS)
        if attachments.get('names') or attachments.get('busy'):
            raise BrowserUIError('The reconciled draft has unverified attachments; it was left untouched.')
        send = await self._visible(edge.SEND_SELECTOR)
        if send is None or not await send.is_enabled():
            raise BrowserUIError('The Copilot Send control is not ready; the draft was left untouched.')
        return text

    async def _verified_unsent_retry_control(self, text: str, request_id: str,
                                             old_user_keys: set) -> object | None:
        """Return a fresh Send control only after stable evidence proves this draft is unsent."""
        previous = None
        stable = 0
        for _ in range(4):
            messages = await self._evaluate(_MESSAGE_SNAPSHOT)
            new_users = [item for item in messages
                         if item.get('role') == 'user' and item.get('key') not in old_user_keys]
            if new_users or any(request_id in item.get('text', '') for item in messages
                                if item.get('role') == 'user'):
                return None
            if await self._stop_present():
                return None
            editor = await self._editor(required=False)
            if editor is None:
                return None
            actual = str(await self._editor_text(editor) or '')
            if not composer_comparison(text, actual).get('matches'):
                return None
            attachments = await self._evaluate(_ATTACHMENTS)
            if (not isinstance(attachments, dict) or attachments.get('names')
                    or attachments.get('busy') or attachments.get('error')
                    or any(upload_alert_is_error(alert) for alert in attachments.get('alerts', []))):
                return None
            button = await self._visible(edge.SEND_SELECTOR)
            if button is None or not await button.is_enabled():
                return None
            snapshot = (actual, tuple((item.get('key'), item.get('text')) for item in messages),
                        tuple(attachments.get('names', [])), bool(attachments.get('busy')))
            stable = stable + 1 if snapshot == previous else 1
            if stable >= 2:
                return button
            previous = snapshot
            await asyncio.sleep(min(.1, max(.01, self.config.poll_interval)))
        return None

    async def capture_committed_response(self, request_id: str) -> str:
        """Recover one already-submitted response without sending another message."""
        if not isinstance(request_id, str) or not request_id:
            raise BrowserUIError('A committed request_id is required for response recovery.')
        closed = getattr(self.page, 'is_closed', lambda: False)() if self.page is not None else True
        if self.page is None or closed:
            raise CaptureTimeoutError('The existing Copilot chat page is unavailable; the committed request was not resent.')
        if hasattr(self.page, 'bring_to_front'):
            await self.page.bring_to_front()
        started = time.monotonic()
        overall_deadline = started + getattr(self.config, 'response_max_duration', self.config.response_timeout)
        idle_deadline = min(overall_deadline, started + self.config.response_timeout)
        previous = ''
        stable = 0
        previous_activity = None
        progress_seen = set()
        while time.monotonic() < min(overall_deadline, idle_deadline):
            messages = await self._evaluate(_MESSAGE_SNAPSHOT)
            matching_users = [item for item in messages if item['role'] == 'user'
                              and request_id in item.get('text', '')]
            if len(matching_users) > 1:
                raise SubmissionAmbiguousError('More than one submitted user turn matches this request_id; recovery stopped without action.')
            if len(matching_users) == 1:
                stop_present, send_ready = await self._generation_state()
                candidate = fresh_assistant(messages, {}, matching_users[0]['key'], request_id)
                interim = public_progress(messages, matching_users[0]['key'], request_id)
                for item in interim:
                    identity = (item['key'], item['text'])
                    if identity not in progress_seen:
                        progress_seen.add(identity)
                        await self._feedback({'type':'progress', 'request_id':request_id,
                                              'message':item['text'][:1000]})
                activity = (candidate, tuple((item['key'], item['text']) for item in interim))
                if stop_present:
                    # Response recovery must honor the same live-generation
                    # signal as a newly submitted turn.
                    idle_deadline = min(overall_deadline, time.monotonic() + self.config.response_timeout)
                elif activity != previous_activity:
                    idle_deadline = min(overall_deadline, time.monotonic() + self.config.response_timeout)
                previous_activity = activity
                complete = bool(candidate and request_id in candidate
                                and response_envelope_closed(candidate)
                                and copied_code_response(candidate, request_id))
                ended = not stop_present and (send_ready or bool(candidate))
                stable = stable + 1 if complete and ended and candidate == previous else 1 if complete and ended else 0
                previous = candidate
                self.last_capture_observation = {
                    'request_id': request_id, 'committed_user_key': matching_users[0]['key'],
                    'candidate_length': len(candidate), 'stop_present': stop_present,
                    'send_ready': send_ready, 'generation_observed': False,
                    'generation_ended': ended, 'capture_method': 'existing_chat_text',
                    'complete_current_text': complete,
                    'nodes': [{'key': item['key'], 'order': item['order'], 'role': item['role'],
                               'length': len(item['text']), 'contains_request': request_id in item['text']}
                              for item in messages[-30:]]}
                if stable >= max(2, self.config.capture_stable_samples):
                    assistant_matches = [item for item in messages if item['role'] == 'assistant'
                                         and item['order'] > matching_users[0]['order']
                                         and item.get('text') == candidate]
                    source = {'request_id': request_id, 'user_key': matching_users[0]['key'],
                              'committed': True}
                    if len(assistant_matches) == 1:
                        source['assistant_key'] = assistant_matches[0]['key']
                    self.last_submission = source
                    return candidate
            await asyncio.sleep(self.config.poll_interval)
        try:
            await self.diagnostics('committed_response_recovery')
        except Exception:
            pass
        raise CaptureTimeoutError('The existing Copilot response could not be captured as a complete, stable envelope; the committed request was not resent.')

    async def exchange(self, text: str, request_id: str, attachments=(), on_submitted=None) -> str:
        async with self._exchange_lock:
            if self._delivery_uncertain:
                raise SubmissionAmbiguousError('A previous delivery remains uncertain. Reconcile manually before a new send.')
            try:
                self.last_submission = {'request_id': request_id, 'committed': False, 'send_attempted': False}
                self.last_composer_comparison = None
                self.last_capture_observation = None
                self.preparation_stage = 'initial_checks'
                if hasattr(self.page, 'bring_to_front'): await self.page.bring_to_front()
                if self._preloaded_exchange is not None:
                    baseline, old_users, button = await self._consume_preloaded_exchange(
                        text, request_id, attachments)
                else:
                    baseline, old_users, button = await self._prepare_submission(text, request_id, attachments)
            except SubmissionAmbiguousError:
                raise
            except Exception as exc:
                self.last_submission = {'request_id': request_id, 'committed': False, 'send_attempted': False}
                message = str(exc) if isinstance(exc, BrowserUIError) else ('Preparation failed before Send at ' + self.preparation_stage + ' (' + type(exc).__name__ + ').')
                try: await self.diagnostics('preparation_' + self.preparation_stage)
                except Exception: pass
                raise SubmissionNotSentError(message) from exc
            user_key = None
            last_error = None
            for send_attempt in range(1, 3):
                self.last_submission = {'request_id': request_id, 'committed': False,
                                        'send_attempted': True, 'send_attempts': send_attempt}
                try:
                    # A retry is allowed only after fresh, stable UI evidence proves
                    # the exact text remains unsent and no attachments were submitted.
                    await button.click(timeout=5000)
                    self._preloaded_attachment_signatures = ()
                    deadline = time.monotonic() + min(20, self.config.response_timeout)
                    while time.monotonic() < deadline:
                        messages = await self._evaluate(_MESSAGE_SNAPSHOT)
                        fresh = [item for item in messages if item['role'] == 'user'
                                 and item['key'] not in old_users and request_id in item['text']]
                        editor = await self._editor(required=False)
                        composer = await self._editor_text(editor) if editor else None
                        if len(fresh) == 1 and composer is not None and not str(composer).strip():
                            user_key = fresh[0]['key']
                            self.last_submission = {'request_id': request_id, 'user_key': user_key,
                                                    'committed': True, 'send_attempts': send_attempt}
                            if on_submitted is not None:
                                outcome = on_submitted()
                                if inspect.isawaitable(outcome):
                                    await outcome
                            break
                        await asyncio.sleep(self.config.poll_interval)
                except BaseException as exc:
                    last_error = exc
                    if user_key is not None:
                        self._delivery_uncertain = True
                        raise SubmissionAmbiguousError('Message was delivered, but its local submission callback failed. Reconcile the counter before continuing.') from exc
                    if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                        self._delivery_uncertain = True
                        await self.diagnostics('ambiguous_submission')
                        raise
                if user_key is not None:
                    break
                if send_attempt == 1:
                    try:
                        retry_button = await self._verified_unsent_retry_control(text, request_id, old_users)
                    except Exception as exc:
                        last_error = last_error or exc
                        retry_button = None
                    if retry_button is not None:
                        self.last_submission = {'request_id': request_id, 'committed': False,
                                                'send_attempted': True, 'send_attempts': 1,
                                                'verified_not_sent': True}
                        await self._feedback({'type': 'progress', 'request_id': request_id,
                                              'message': 'Copilot kept the exact request unsent. The page confirms it is still in the composer, so I am retrying Send once.'})
                        button = retry_button
                        continue
                self._delivery_uncertain = True
                await self.diagnostics('ambiguous_submission')
                raise SubmissionAmbiguousError('Delivery could not be committed safely after the Send attempt. Reconciliation is required; no resend was attempted.') from last_error
            started = time.monotonic()
            overall_deadline = started + getattr(self.config, 'response_max_duration', self.config.response_timeout)
            idle_deadline = min(overall_deadline, started + self.config.response_timeout)
            previous = ''
            stable = 0
            previous_activity = None
            progress_seen = set()
            await self._feedback({'type':'generation', 'request_id':request_id, 'message':'Waiting for Copilot to render its reply.'})
            streamed_candidate = ''
            generation_observed = False
            invalid_stable = 0
            scrolled_for_tail = False
            try:
                while time.monotonic() < min(overall_deadline, idle_deadline):
                    if any(host in self.page.url for host in ('login.microsoftonline.com', 'login.live.com')):
                        raise CaptureTimeoutError('Authentication interrupted a committed request; do not resend automatically.')
                    messages = await self._evaluate(_MESSAGE_SNAPSHOT)
                    candidate = fresh_assistant(messages, baseline, user_key, request_id)
                    if model_access_exhausted(candidate):
                        await self._feedback({'type':'generation','request_id':request_id,
                            'message':'Selected model access is exhausted; Copilot reported an Auto fallback. No protocol retry or local tool execution.'})
                        raise ModelAccessError('Copilot reported that today\'s selected-model access is exhausted and switched to Auto. Start a fresh setup and explicitly select an available model, or wait for access to return.')
                    stop_present, send_ready = await self._generation_state()
                    if stop_present and not generation_observed:
                        generation_observed = True
                        await self._feedback({'type':'generation','request_id':request_id,'message':'Copilot is generating a response.'})
                    interim = public_progress(messages, user_key, request_id)
                    for item in interim:
                        identity = (item['key'], item['text'])
                        if identity not in progress_seen:
                            progress_seen.add(identity)
                            await self._feedback({'type':'progress', 'request_id':request_id,
                                                  'message':item['text'][:1000]})
                    if candidate and candidate != streamed_candidate:
                        streamed_candidate = candidate
                        await self._feedback({'type':'candidate','request_id':request_id,'raw':candidate,
                                              'generation_ended':generation_observed and not stop_present})
                    generation_ended = generation_observed and not stop_present
                    activity = (candidate, tuple((item['key'], item['text']) for item in interim))
                    if stop_present:
                        # Copilot can spend several minutes reasoning without
                        # changing rendered text. Its visible loading/stop state
                        # is active progress, so wait for the overall deadline.
                        idle_deadline = min(overall_deadline, time.monotonic() + self.config.response_timeout)
                    elif activity != previous_activity:
                        idle_deadline = min(overall_deadline, time.monotonic() + self.config.response_timeout)
                    previous_activity = activity
                    if candidate and len(candidate) > self.config.max_capture_chars:
                        raise CaptureTimeoutError('The rendered response exceeded max_capture_chars; no partial response was accepted.')
                    # Never invent markers around chat text. A finished malformed reply
                    # goes to the protocol validator so it can request a correction.
                    complete = bool(generation_ended and response_envelope_closed(candidate)
                                    and copied_code_response(candidate, request_id))
                    self.last_capture_observation = {
                        'request_id': request_id, 'committed_user_key':user_key, 'candidate_length':len(candidate),
                        'stop_present':stop_present, 'send_ready':send_ready,
                        'generation_observed':generation_observed, 'generation_ended':generation_ended,
                        'capture_method':'chat_text', 'complete_current_text':complete,
                        'nodes':[{'key':item['key'],'order':item['order'],'role':item['role'],
                                  'length':len(item['text']),'contains_request':request_id in item['text']}
                                 for item in messages[-30:]]}
                    settled = bool(candidate) and generation_ended
                    stable = (stable + 1 if candidate == previous else 1) if settled else 0
                    invalid_stable = (invalid_stable + 1 if settled and not complete and candidate == previous
                                      else 1 if settled and not complete else 0)
                    previous = candidate
                    if invalid_stable >= 2 and not scrolled_for_tail:
                        # Long chat replies can render their tail only after the
                        # assistant message is scrolled into view. Inspect the
                        # full DOM again before classifying a finished reply.
                        scrolled_for_tail = True
                        if hasattr(self.page, 'evaluate'):
                            try:
                                await self.page.evaluate("""() => {
                                  const nodes=[...document.querySelectorAll('[data-testid="markdown-reply"],.fai-CopilotMessage__content,[data-author="assistant"],[data-message-author-role="assistant"]')];
                                  nodes.at(-1)?.scrollIntoView({block:'end'});
                                }""")
                            except Exception:
                                pass
                    if complete and stable >= max(2, self.config.capture_stable_samples):
                        return candidate
                    if invalid_stable >= max(4, self.config.capture_stable_samples + 2):
                        return candidate
                    await asyncio.sleep(self.config.poll_interval)
                reason = ('the overall response time limit was reached' if time.monotonic() >= overall_deadline
                          else 'visible response progress stopped for the inactivity limit')
                raise CaptureTimeoutError(
                    'Copilot did not provide a current-turn chat response because ' + reason + '. '
                    'No local action ran for this reply; the committed message was not resent.')
            except Exception as exc:
                await self.diagnostics('capture')
                if isinstance(exc, (CaptureTimeoutError, ModelAccessError)):
                    raise
                raise CaptureTimeoutError('Capture failed after proven submission; do not resend automatically.') from exc

    async def diagnostics(self, reason='failure'):
        """Retain local UI evidence; no cookies, credentials, DOM dump or query strings."""
        directory = self.config.runtime_dir / 'diagnostics'
        directory.mkdir(parents=True, exist_ok=True)
        token = time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
        prefix = directory / token
        if self.page is None or self.page.is_closed():
            path = Path(str(prefix) + '.json')
            path.write_text(json.dumps({'reason': reason, 'startup_stage': self.startup_stage,
                                        'page_available': False}, indent=2), encoding='utf-8')
            self.last_diagnostics = str(path)
            return path
        parsed = urlparse(self.page.url)
        report = {'reason': reason, 'url': f'{parsed.scheme}://{parsed.netloc}{parsed.path}',
                  'model': self.model_label, 'submission': self.last_submission,
                  'composer_comparison': self.last_composer_comparison,
                   'preparation_stage': getattr(self, 'preparation_stage', None),
                   'startup_stage': self.startup_stage}
        report['capture_observation'] = self.last_capture_observation
        try:
            report['ui'] = await asyncio.wait_for(self.page.evaluate(r"""() => ({
              title:document.title.slice(0,100), radios:document.querySelectorAll('[role="menuitemradio"]').length,
              file_inputs:document.querySelectorAll('input[type="file"]').length,
              assistant_nodes:document.querySelectorAll('[data-testid="markdown-reply"]').length,
              editor_present:!!document.querySelector('#m365-chat-editor-target-element'),
              alerts:[...document.querySelectorAll('[role="alert"]')].map(n=>(n.innerText||'').slice(0,200))})"""), 3)
            # Screenshots are local and may contain user content; credentials/account controls masked.
            if parsed.hostname == 'm365.cloud.microsoft' and not getattr(self, 'website_private', False):
                dimensions = await self._evaluate('() => ({width:innerWidth,height:innerHeight})')
                x, y = min(360, dimensions['width'] * .35), min(110, dimensions['height'] * .2)
                await self.page.screenshot(path=str(prefix)+'.png', timeout=3000, full_page=False,
                    clip={'x':x, 'y':y, 'width':dimensions['width']-x, 'height':dimensions['height']-y},
                    mask=[self.page.locator('input,textarea,aside,nav,header,[role="navigation"],'
                      '[data-testid*="sidebar" i],[id*="sidebar" i],[data-testid*="profile" i],'
                      '[data-testid*="avatar" i],[class*="Avatar"],button[aria-label*="account" i],button[aria-label*="profile" i]')])
                report['screenshot'] = str(prefix)+'.png'
        except Exception:
            report['ui_evidence'] = 'unavailable'
        serialized = json.dumps(report, indent=2, ensure_ascii=False)
        if getattr(self, 'website_private', False):
            from .web_privacy import audit_evidence
            serialized = json.dumps({'reason': reason, 'evidence': audit_evidence(report)}, indent=2)
        serialized = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[REDACTED]', serialized)
        serialized = re.sub(r'(?i)(token|password|secret|api[_-]?key)(["\s:=]+)[^\s,"}]+', r'\1\2[REDACTED]', serialized)
        path = Path(str(prefix)+'.json')
        path.write_text(serialized, encoding='utf-8')
        self.last_diagnostics = str(path)
        return path

    async def close(self, *, preserve_browser_process=True):
        # Keep the signed-in Edge process and its tabs for the next normal run.
        # Playwright.stop disconnects CDP without closing this browser.
        self.page = self.tool_page = None
        self.tool_context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = self.browser = self.context = None
        self._launched_process = None
        if self._mutex:
            self._mutex[0].CloseHandle(self._mutex[1])
            self._mutex = None
