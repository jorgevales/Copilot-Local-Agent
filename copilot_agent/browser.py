"""Visible Edge/Copilot UI adapter with bounded waits and owned-page isolation."""
from __future__ import annotations

import asyncio
from collections import Counter
import inspect
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlparse

from . import reused_browser as edge
from .protocol import BEGIN, END


class BrowserUIError(RuntimeError):
    pass


class ModelAccessError(BrowserUIError):
    """The UI reports that the chosen model is unavailable or silently fell back."""


def model_access_exhausted(text):
    value = ' '.join(text.lower().split())
    return ('<<<copilot_agent_v1_begin>>>' not in value and len(value) <= 1500 and
            value.startswith("you've used today's") and 'access' in value and
            'now using auto' in value and 'available again' in value)


def response_envelope_closed(text: str) -> bool:
    """Recognize a complete wire envelope without parsing or validating its JSON."""
    return (text.count(BEGIN) == 1 and text.count(END) == 1
            and text.index(BEGIN) < text.index(END))


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

_RADIOS = r"""() => [...document.querySelectorAll('[role="menuitemradio"],[role="radio"]')]
 .filter(n => n.offsetWidth || n.offsetHeight || n.getClientRects().length)
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
        self._tool_pages = []
        self.model_label = None
        self.models: list[dict] = []
        self._top_level_labels = set()
        self._playwright = self._manager = None
        self._exchange_lock = asyncio.Lock()
        self._delivery_uncertain = False
        self._mutex = None
        self._launched_process = None
        self.last_submission = None
        self.last_diagnostics = None
        self.last_composer_comparison = None
        self.last_capture_observation = None
        self.feedback_callback = None

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
        profile = str(Path(self.config.profile_dir).resolve()).casefold()
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

    async def start(self):
        if not self.config.visible:
            raise BrowserUIError('This adapter supports visible Edge only; hidden/headless operation is unsupported.')
        parsed = urlparse(self.config.copilot_url)
        if parsed.scheme != 'https' or parsed.hostname != 'm365.cloud.microsoft':
            raise BrowserUIError('Copilot control URL must use https://m365.cloud.microsoft/.')
        self._acquire_controller()
        try:
            profile = Path(self.config.profile_dir).expanduser().resolve()
            payload = await asyncio.to_thread(edge.get_cdp_version, self.endpoint)
            if payload is not None:
                edge.validate_endpoint(self.endpoint, payload)
                if not self.config.attach_existing:
                    raise BrowserUIError('This port already has an Edge session. Enable explicit existing-session attachment or choose another port.')
                if self._launched_process is not None:
                    await asyncio.to_thread(edge.validate_launched_endpoint, self.config.debug_port, profile,
                                            self._launched_process)
                else:
                    await asyncio.to_thread(edge.validate_profile_ownership, self.config.debug_port, profile)
            else:
                if self.config.attach_existing:
                    raise BrowserUIError('No existing dedicated Edge debugging session was found on this port.')
                executable = edge.find_edge_executable(self.config.edge_executable)
                print('[System] Starting a visible Edge window with the dedicated agent profile.')
                self._launched_process = edge.launch_edge(executable, self.config.debug_port, profile)
            from playwright.async_api import async_playwright
            self._manager = async_playwright()
            self._playwright = await self._manager.start()
            self.browser = await edge.connect_bounded(self._playwright, self.endpoint, self.config.startup_timeout,
                                                      process=self._launched_process)
            # Prove the fresh listener belongs to this Popen process; fall back to
            # exact profile inspection if Edge handed off to a different process.
            if __import__('os').name == 'nt':
                await asyncio.to_thread(edge.validate_launched_endpoint, self.config.debug_port, profile,
                                        self._launched_process)
            self.context = self.browser.contexts[0]
            self.page = await asyncio.wait_for(self.context.new_page(), 10)
            self.tool_context = await asyncio.wait_for(self.browser.new_context(accept_downloads=False, service_workers='block', java_script_enabled=False), 10)
            await self._configure_tool_context()
            self.tool_page = await asyncio.wait_for(self.tool_context.new_page(), 10)
            self.page.set_default_timeout(5000)
            self.tool_page.set_default_timeout(5000)
            await self.page.goto(self.config.copilot_url, wait_until='domcontentloaded', timeout=int(self.config.startup_timeout*1000))
            await self.page.bring_to_front()
            print('[System] Edge is open. Complete Microsoft 365 sign-in there if prompted.')
            deadline = time.monotonic() + self.config.startup_timeout
            while time.monotonic() < deadline:
                editor = await self._editor(required=False)
                if editor is not None and await self._visible(edge.PICKER_SELECTOR) is not None:
                    if any(item['role'] == 'user' for item in await self._evaluate(_MESSAGE_SNAPSHOT)):
                        raise BrowserUIError('Copilot opened an existing conversation. A fresh independent chat is required before initialization.')
                    return self
                await asyncio.sleep(self.config.poll_interval)
            raise BrowserUIError('Copilot editor/model picker was not ready before startup_timeout. Complete sign-in and restart setup.')
        except Exception:
            await self.diagnostics('startup')
            await self.close()
            raise

    async def _evaluate(self, script, arg=None):
        return await asyncio.wait_for(self.page.evaluate(script, arg), timeout=5)

    async def _configure_tool_context(self):
        from .policy import URLPolicy, PolicyError
        policy = URLPolicy(self.config.allowed_domains)

        async def guard(route):
            try:
                policy.resolve(route.request.url)
            except (PolicyError, ValueError):
                self.tool_errors.append({'type': 'blocked_request', 'url': self._safe_url(route.request.url)})
                await route.abort('blockedbyclient')
            else:
                await route.continue_()

        # All pages/popups in this separate context are owned; no existing tab is intercepted.
        await self.tool_context.route('**/*', guard)
        if hasattr(self.tool_context, 'route_web_socket'):
            async def websocket_guard(route):
                self.tool_errors.append({'type': 'blocked_websocket', 'url': self._safe_url(route.url)})
                await route.close()
            await self.tool_context.route_web_socket('**/*', websocket_guard)
        await self.tool_context.add_init_script("""(() => {
          // Bound script-created non-network navigation as well as routed requests.
          const allowed = new Set(%s);
          const original = window.open;
          window.open = function(url, ...args) {
            if (!url) return null;
            try { const u = new URL(url, location.href);
              if (u.protocol !== 'https:' || !allowed.has(u.hostname.toLowerCase()) || (u.port && u.port !== '443') || u.username || u.password) return null;
            } catch (_) { return null; }
            return original.call(window, url, ...args);
          };
        })();""" % json.dumps(sorted(policy.domains)))

        def register(page):
            self._tool_pages.append(page)
            def error(exc):
                self.tool_errors.append({'type': 'page_error', 'message': 'JavaScript error observed on owned tool page'})
            def failed(request):
                self.tool_errors.append({'type': 'request_failed', 'url': self._safe_url(request.url),
                                         'failure': str(request.failure or '')[:100]})
            async def download(item):
                # Observation is not permission to export/download third-party content.
                self.tool_downloads.append({'url': self._safe_url(item.url), 'suggested_filename': Path(item.suggested_filename).name,
                                            'saved': False, 'status': 'cancelled_by_policy'})
                await item.cancel()
            async def check_navigation(frame):
                if frame != page.main_frame or frame.url == 'about:blank':
                    return
                try:
                    policy.resolve(frame.url)
                except (PolicyError, ValueError):
                    self.tool_errors.append({'type': 'blocked_navigation', 'url': self._safe_url(frame.url)})
                    # Close this owned popup/page, preserving all files and original tabs.
                    await page.close()
            page.on('pageerror', error)
            page.on('requestfailed', failed)
            page.on('download', download)
            page.on('framenavigated', check_navigation)
        self.tool_context.on('page', register)

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
        picker = await self._visible(edge.PICKER_SELECTOR)
        if picker is None:
            raise BrowserUIError('Copilot model picker is unavailable.')
        if await picker.get_attribute('aria-expanded') != 'true':
            await picker.click(timeout=3000)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if await self._evaluate(r"""() => [...document.querySelectorAll('[role="menuitemradio"],[role="radio"],[data-testid^="gptSubMenuModelTrigger-"],[data-test-id^="gptSubMenuModelTrigger-"]')].some(n=>n.offsetWidth||n.offsetHeight)"""):
                return
            await asyncio.sleep(self.config.poll_interval)
        raise BrowserUIError('The model picker did not render visible options within its bounded wait.')

    async def _providers(self):
        return await self._evaluate(r"""() => [...document.querySelectorAll('[data-testid^="gptSubMenuModelTrigger-"],[data-test-id^="gptSubMenuModelTrigger-"]')]
          .filter(n=>(n.offsetWidth||n.offsetHeight)&&n.getAttribute('aria-disabled')!=='true'&&!n.disabled).map(n=>({id:n.getAttribute('data-testid')||n.getAttribute('data-test-id'), label:(n.innerText||'').trim()}))""")

    async def _open_provider(self, trigger):
        await self._open_picker()
        opened = await self._evaluate(r"""id => {
          const n=[...document.querySelectorAll('[data-testid],[data-test-id]')].find(n=>n.getAttribute('data-testid')===id||n.getAttribute('data-test-id')===id);
          if(!n || !(n.offsetWidth||n.offsetHeight)) return false;
          if(n.getAttribute('aria-expanded')!=='true') n.click(); return true;
        }""", trigger)
        if not opened:
            raise BrowserUIError('The discovered model provider menu is no longer available.')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            radios = await self._evaluate(_RADIOS)
            if any(item['label'] not in self._top_level_labels for item in radios):
                return
            await asyncio.sleep(self.config.poll_interval)
        raise BrowserUIError('The model provider submenu did not render its options within the bounded wait.')

    async def discover_models(self) -> list[dict]:
        try:
            await self._open_picker()
            providers = await self._providers()
            entries = [{**item, 'provider': 'Copilot', 'provider_trigger': None}
                       for item in await self._evaluate(_RADIOS)]
            self._top_level_labels = {item['label'] for item in entries}
            for provider in providers:
                await self.page.keyboard.press('Escape')
                await self.page.keyboard.press('Escape')
                await self._open_provider(provider['id'])
                name = provider['id'].split('gptSubMenuModelTrigger-', 1)[-1]
                entries.extend({**item, 'provider': name, 'provider_trigger': provider['id']}
                               for item in await self._evaluate(_RADIOS)
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

    async def select_model(self, label: str):
        matches = [item for item in self.models if item['label'] == label and item['enabled']]
        if len(matches) != 1:
            raise BrowserUIError('Choose one exact, unambiguous enabled label from the discovered model list.')
        chosen = matches[0]
        try:
            if chosen['provider_trigger']:
                await self._open_provider(chosen['provider_trigger'])
            else:
                await self._open_picker()
            clicked = await self._evaluate(r"""label => {
              const norm=n=>(n.innerText||n.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim();
              const matches=[...document.querySelectorAll('[role="menuitemradio"],[role="radio"]')].filter(n=>norm(n)===label&&(n.offsetWidth||n.offsetHeight));
              if(matches.length!==1||matches[0].getAttribute('aria-disabled')==='true'||matches[0].disabled) return false;
              if(matches[0].getAttribute('aria-checked')!=='true') matches[0].click(); return true;
            }""", label)
            if not clicked:
                raise BrowserUIError('The exact discovered model radio could not be selected.')
            deadline = time.monotonic() + min(10, self.config.startup_timeout)
            while time.monotonic() < deadline:
                if chosen['provider_trigger']:
                    await self._open_provider(chosen['provider_trigger'])
                else:
                    await self._open_picker()
                radios = await self._evaluate(_RADIOS)
                if any(item['label'] == label and item['checked'] for item in radios):
                    self.model_label = label
                    observed = next(item for item in radios if item['label'] == label and item['checked'])
                    chosen = {**chosen, **observed, 'checked': True, 'verified': True}
                    self.models = [chosen if item['label'] == label and item['provider'] == chosen['provider'] else item for item in self.models]
                    return chosen
                await asyncio.sleep(self.config.poll_interval)
            raise BrowserUIError('The selected model never showed a checked exact radio.')
        except Exception:
            await self.diagnostics('model_selection')
            raise
        finally:
            await self.page.keyboard.press('Escape')
            await self.page.keyboard.press('Escape')

    async def _stop_present(self):
        return bool(await self._evaluate(r"""() => [...document.querySelectorAll('button')].some(n=>
          (n.offsetWidth||n.offsetHeight)&&/^(stop generating|stop|stop responding)/i.test(n.getAttribute('aria-label')||''))"""))

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

    async def _editor_text(self, editor):
        return await asyncio.wait_for(editor.evaluate(_EDITOR_VALUE), timeout=5)

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

    async def _prepare_submission(self, text, request_id, attachments):
        if not request_id or request_id not in text:
            raise BrowserUIError('Every outbound message must contain its unique request_id.')
        if not self.model_label:
            raise BrowserUIError('Select and verify a discovered model before sending.')
        if await self._stop_present():
            raise BrowserUIError('Copilot is still generating; a second message cannot be sent.')
        baseline_messages = await self._evaluate(_MESSAGE_SNAPSHOT)
        baseline = {item['key']: item['text'] for item in baseline_messages}
        old_users = {item['key'] for item in baseline_messages if item['role'] == 'user'}
        if any(request_id in item['text'] for item in baseline_messages if item['role'] == 'user'):
            self._delivery_uncertain = True
            raise SubmissionAmbiguousError('This request_id is already present in the chat; refusing duplicate delivery.')
        editor = await self._editor()
        await editor.fill(text, timeout=5000)
        actual = await self._editor_text(editor)
        self.last_composer_comparison = composer_comparison(text, str(actual))
        if not self.last_composer_comparison['matches']:
            await self.diagnostics('composer_mismatch')
            raise BrowserUIError('The composer did not preserve the complete outbound message.')
        await self.attach_files(attachments)
        button = await self._visible(edge.SEND_SELECTOR)
        if button is None or not await button.is_enabled():
            raise BrowserUIError('The exact Send control is unavailable or disabled.')
        return baseline, old_users, button

    async def exchange(self, text: str, request_id: str, attachments=(), on_submitted=None) -> str:
        async with self._exchange_lock:
            if self._delivery_uncertain:
                raise SubmissionAmbiguousError('A previous delivery remains uncertain. Reconcile manually before a new send.')
            try:
                baseline, old_users, button = await self._prepare_submission(text, request_id, attachments)
            except SubmissionAmbiguousError:
                raise
            except Exception as exc:
                self.last_submission = {'request_id': request_id, 'committed': False, 'send_attempted': False}
                message = str(exc) if isinstance(exc, BrowserUIError) else 'Preparation failed before attempting Send.'
                raise SubmissionNotSentError(message) from exc
            user_key = None
            try:
                # Treat even a click timeout as uncertain: the remote action may have fired.
                await button.click(timeout=5000)
                deadline = time.monotonic() + min(20, self.config.response_timeout)
                while time.monotonic() < deadline:
                    messages = await self._evaluate(_MESSAGE_SNAPSHOT)
                    fresh = [item for item in messages if item['role'] == 'user'
                             and item['key'] not in old_users and request_id in item['text']]
                    editor = await self._editor(required=False)
                    composer = await self._editor_text(editor) if editor else None
                    if len(fresh) == 1 and composer is not None and not str(composer).strip():
                        user_key = fresh[0]['key']
                        self.last_submission = {'request_id': request_id, 'user_key': user_key, 'committed': True}
                        if on_submitted is not None:
                            outcome = on_submitted()
                            if inspect.isawaitable(outcome):
                                await outcome
                        break
                    await asyncio.sleep(self.config.poll_interval)
                if user_key is None:
                    raise SubmissionAmbiguousError('Send was attempted, but a fresh correlated user turn and cleared composer were not both observed. Do not resend.')
            except BaseException as exc:
                if user_key is None:
                    self._delivery_uncertain = True
                    await self.diagnostics('ambiguous_submission')
                    if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                        raise
                    raise SubmissionAmbiguousError('Delivery could not be committed safely after the Send attempt. Reconciliation is required; no resend was attempted.') from exc
                # Callback failure after proven send is still not a retryable delivery.
                self._delivery_uncertain = True
                raise SubmissionAmbiguousError('Message was delivered, but its local submission callback failed. Reconcile the counter before continuing.') from exc
            deadline = time.monotonic() + self.config.response_timeout
            previous = ''
            stable = 0
            expansions = 0
            await self._feedback({'type':'generation', 'request_id':request_id, 'message':'Waiting for Copilot to render its reply.'})
            streamed_candidate = ''
            generation_observed = False
            try:
                while time.monotonic() < deadline:
                    if any(host in self.page.url for host in ('login.microsoftonline.com', 'login.live.com')):
                        raise CaptureTimeoutError('Authentication interrupted a committed request; do not resend automatically.')
                    if expansions < 4:
                        expansions += int(await self._expand_response_code(request_id) or 0)
                    messages = await self._evaluate(_MESSAGE_SNAPSHOT)
                    candidate = fresh_assistant(messages, baseline, user_key, request_id)
                    if len(candidate) > self.config.max_capture_chars:
                        raise CaptureTimeoutError('Assistant response exceeded max_capture_chars; refusing a truncated capture.')
                    if model_access_exhausted(candidate):
                        await self._feedback({'type':'generation','request_id':request_id,
                            'message':'Selected model access is exhausted; Copilot reported an Auto fallback. No protocol retry or local tool execution.'})
                        raise ModelAccessError('Copilot reported that today\'s selected-model access is exhausted and switched to Auto. Start a fresh setup and explicitly select an available model, or wait for access to return.')
                    stop_present, send_ready = await self._generation_state()
                    if stop_present and not generation_observed:
                        generation_observed = True
                        await self._feedback({'type':'generation','request_id':request_id,'message':'Copilot is generating a response.'})
                    if candidate and candidate != streamed_candidate:
                        streamed_candidate = candidate
                        await self._feedback({'type':'candidate','request_id':request_id,'raw':candidate,
                                              'generation_ended':not stop_present and (generation_observed or send_ready)})
                    envelope_closed = bool(candidate and response_envelope_closed(candidate))
                    generation_ended = not stop_present and (generation_observed or send_ready)
                    self.last_capture_observation = {
                        'request_id': request_id, 'committed_user_key':user_key, 'candidate_length':len(candidate),
                        'stop_present':stop_present, 'send_ready':send_ready,
                        'generation_observed':generation_observed, 'generation_ended':generation_ended,
                        'closing_marker_present':envelope_closed,
                        'nodes':[{'key':item['key'],'order':item['order'],'role':item['role'],
                                  'length':len(item['text']),'contains_request':request_id in item['text']}
                                 for item in messages[-30:]]}
                    settled = envelope_closed and generation_ended
                    stable = (stable + 1 if candidate == previous else 1) if settled else 0
                    previous = candidate
                    # Parsing belongs after capture. Only a complete, ended, briefly stable
                    # current-turn envelope may reach protocol validation.
                    if stable >= max(2, self.config.capture_stable_samples):
                        return candidate
                    await asyncio.sleep(self.config.poll_interval)
                raise CaptureTimeoutError(
                    'Copilot did not finish a complete reply before the capture limit. '
                    'No local action ran for this reply; the committed message was not resent.')
            except Exception as exc:
                await self.diagnostics('capture')
                if isinstance(exc, (CaptureTimeoutError, ModelAccessError)):
                    raise
                raise CaptureTimeoutError('Capture failed after proven submission; do not resend automatically.') from exc

    async def diagnostics(self, reason='failure'):
        """Retain local UI evidence; no cookies, credentials, DOM dump or query strings."""
        if self.page is None or self.page.is_closed():
            return None
        directory = self.config.runtime_dir / 'diagnostics'
        directory.mkdir(parents=True, exist_ok=True)
        token = time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
        prefix = directory / token
        parsed = urlparse(self.page.url)
        report = {'reason': reason, 'url': f'{parsed.scheme}://{parsed.netloc}{parsed.path}',
                  'model': self.model_label, 'submission': self.last_submission,
                  'composer_comparison': self.last_composer_comparison}
        report['capture_observation'] = self.last_capture_observation
        try:
            report['ui'] = await asyncio.wait_for(self.page.evaluate(r"""() => ({
              title:document.title.slice(0,100), radios:document.querySelectorAll('[role="menuitemradio"]').length,
              file_inputs:document.querySelectorAll('input[type="file"]').length,
              assistant_nodes:document.querySelectorAll('[data-testid="markdown-reply"]').length,
              editor_present:!!document.querySelector('#m365-chat-editor-target-element'),
              alerts:[...document.querySelectorAll('[role="alert"]')].map(n=>(n.innerText||'').slice(0,200))})"""), 3)
            # Screenshots are local and may contain user content; credentials/account controls masked.
            if parsed.hostname == 'm365.cloud.microsoft':
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
        serialized = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[REDACTED]', serialized)
        serialized = re.sub(r'(?i)(token|password|secret|api[_-]?key)(["\s:=]+)[^\s,"}]+', r'\1\2[REDACTED]', serialized)
        path = Path(str(prefix)+'.json')
        path.write_text(serialized, encoding='utf-8')
        self.last_diagnostics = str(path)
        return path

    async def close(self, *, preserve_browser_process=False):
        # Never Browser.close(): CDP disconnect must not shut down an existing browser.
        for page in (self.tool_page, self.page):
            if page is not None:
                try:
                    if not page.is_closed():
                        await asyncio.wait_for(page.close(), timeout=3)
                except Exception:
                    pass
        self.page = self.tool_page = None
        if self.tool_context is not None:
            try:
                await asyncio.wait_for(self.tool_context.close(), timeout=5)
            except Exception:
                pass
            self.tool_context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = self.browser = self.context = None
        if not preserve_browser_process and self._launched_process is not None:
            await asyncio.to_thread(edge.stop_launched_edge, self._launched_process)
        self._launched_process = None
        if self._mutex:
            self._mutex[0].CloseHandle(self._mutex[1])
            self._mutex = None
