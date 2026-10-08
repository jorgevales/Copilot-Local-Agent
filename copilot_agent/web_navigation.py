"""Bounded semantic website discovery and verified plans in owned Edge tabs.

Page content is untrusted. Plans are approved immutable inputs, never page-produced
code. Site maps and customer observations remain ephemeral here; persistence has
its own explicit consent boundary. A failed/uncertain effect is never replayed.
"""
import asyncio
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urljoin, urlsplit, urlunsplit

from .policy import PolicyError, URLPolicy, config_value


def _object(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TEXT = {"type": "string", "maxLength": 4096}
KEY = {"type": "string", "maxLength": 128}
LOCATOR = _object({key: TEXT for key in ("id", "testid", "role", "name", "label", "text", "css", "frame_selector")})
ASSERTION = _object({
    "kind": {"type": "string", "enum": ["visible", "hidden", "text", "url", "count", "enabled"]},
    "locator": LOCATOR, "value": TEXT,
    "count": {"type": "integer", "minimum": 0, "maximum": 100},
}, ("kind",))
ASSERTIONS = {"type": "array", "items": ASSERTION, "maxItems": 10}
IDENTITIES = {"type": "array", "items": _object({"locator": LOCATOR, "value": TEXT}, ("locator", "value")), "maxItems": 5}


def _step_schema(depth=2):
    properties = {
        "id": KEY,
        "op": {"type": "string", "enum": ["navigate", "click", "fill", "select", "press", "wait", "assert", "capture", "branch", "loop", "open_tab", "close_tab"]},
        "locator": LOCATOR, "url": TEXT, "value": TEXT, "key": KEY, "tab_id": KEY,
        "effect": {"type": "string", "enum": ["navigation", "search", "consequential"]},
        "expect": ASSERTIONS, "condition": ASSERTION,
        "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 15000},
        "locator_retries": {"type": "integer", "minimum": 0, "maximum": 2},
        "max_iterations": {"type": "integer", "minimum": 1, "maximum": 10},
        "purpose": {"type": "string", "maxLength": 256},
        "max_chars": {"type": "integer", "minimum": 1, "maximum": 3000},
    }
    if depth:
        nested = {"type": "array", "items": _step_schema(depth-1), "maxItems": 10}
        properties.update({"then": nested, "else": nested, "steps": nested})
    return _object(properties, ("id", "op"))


NAVIGATION_SPECS = {
    "browser.recon": (_object({
        "goal": {"type": "string", "maxLength": 1000}, "tab_id": KEY, "task_id": KEY, "customer_key": KEY,
        "max_elements": {"type": "integer", "minimum": 1, "maximum": 120},
        "max_text_chars": {"type": "integer", "minimum": 0, "maximum": 4000},
    }), "read_only", "Inspect one approved page in one bounded semantic snapshot; return a task-ranked ephemeral site map, controls, forms, tables, documents and security boundaries. No crawling or input values."),
    "browser.route": (_object({"goal": {"type": "string", "maxLength": 1000}, "tab_id": KEY, "task_id": KEY, "customer_key": KEY}, ("goal",)), "read_only", "Rank fresh routes actually observed by reconnaissance in this same origin/session. Missing or stale knowledge requires recon; guessed routes are never executable."),
    "browser.tabs": (_object({
        "operation": {"type": "string", "enum": ["list", "open", "close", "reset"]},
        "tab_id": KEY, "url": TEXT, "purpose": {"type": "string", "maxLength": 256},
        "task_id": KEY, "customer_key": KEY,
    }, ("operation",)), "user_approval", "Manage at most six owned same-origin tabs with stable IDs and explicit task/customer contexts; preserve the primary page. Reset navigates that page to an approved safe URL before clearing prior task/customer bindings and ephemeral plans/maps."),
    "browser.plan": (_object({
        "task_id": KEY, "customer_key": KEY, "identity": IDENTITIES, "tab_id": KEY,
        "steps": {"type": "array", "items": _step_schema(), "maxItems": 50},
        "success": ASSERTIONS,
        "max_actions": {"type": "integer", "minimum": 1, "maximum": 150},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
        "resume_token": KEY,
    }, ("task_id", "steps", "success")), "user_approval", "Execute one exact approved, bounded semantic action plan with branches/loops, assertions, cancellation and verified partials. Side effects run once, require checkpoints, and uncertain effects block automatic resume. Consequential effects require a separate exact local grant."),
    "browser.customer_summary": (_object({
        "task_id": KEY, "customer_key": KEY, "identity": IDENTITIES, "tab_id": KEY,
        "fields": {"type": "array", "maxItems": 20, "items": _object({"name": KEY, "locator": LOCATOR}, ("name", "locator"))},
    }, ("task_id", "customer_key", "identity", "fields")), "user_approval", "Verify supplied authorised identifiers exactly and uniquely before extracting only requested customer fields. Facts have sources; missing/ambiguous fields are explicit; no inference or persistence."),
}


def _validate_schema(value, schema):
    kind = schema.get("type")
    expected = {"object": dict, "array": list, "string": str, "integer": int}[kind]
    if not isinstance(value, expected) or kind == "integer" and isinstance(value, bool):
        raise ValueError("Invalid navigation argument type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Unsupported navigation option")
    if kind == "object":
        if set(value)-set(schema["properties"]) or set(schema["required"])-set(value):
            raise ValueError("Missing or unsupported navigation arguments")
        for key, item in value.items():
            _validate_schema(item, schema["properties"][key])
    elif kind == "array":
        if len(value) > schema["maxItems"]:
            raise ValueError("Navigation array exceeds limit")
        for item in value:
            _validate_schema(item, schema["items"])
    elif kind == "string":
        if len(value) > schema.get("maxLength", 4096):
            raise ValueError("Navigation string exceeds limit")
    elif not schema["minimum"] <= value <= schema["maximum"]:
        raise ValueError("Navigation number outside bounds")


def _validate_locator(locator):
    if not locator or not any(locator.get(key) for key in ("id", "testid", "role", "label", "text", "css")):
        raise ValueError("A semantic locator is required")
    if "role" in locator and not locator.get("name"):
        raise ValueError("Role locators require an exact accessible name")
    if "name" in locator and not locator.get("role"):
        raise ValueError("Accessible name requires a role")
    if any(not value.strip() for value in locator.values()):
        raise ValueError("Locator values cannot be empty")
    css = locator.get("css", "")
    if css.startswith(("xpath=", "//", "..")) or ">>>" in css:
        raise ValueError("Use explicit scoped CSS and semantic locators")


def _validate_assertion(assertion):
    if assertion["kind"] == "url":
        if not assertion.get("value"):
            raise ValueError("URL assertion requires a value")
    else:
        _validate_locator(assertion.get("locator", {}))
    if assertion["kind"] == "text" and "value" not in assertion:
        raise ValueError("Text assertion requires exact expected text")
    if assertion["kind"] == "count" and "count" not in assertion:
        raise ValueError("Count assertion requires an explicit count")


def validate_navigation(name, args, context=None):
    """Validate every nested step before the first browser effect."""
    if name not in NAVIGATION_SPECS:
        raise ValueError("Unknown navigation capability")
    _validate_schema(args, NAVIGATION_SPECS[name][0])
    if name == "browser.plan":
        if not args["task_id"].strip() or not args["steps"] or not args["success"]:
            raise ValueError("A nonempty task, plan and final success criteria are required")
        ids = set()
        def steps(items):
            for step in items:
                if not step["id"].strip() or step["id"] in ids:
                    raise ValueError("Every nested step needs a unique ID")
                ids.add(step["id"])
                op = step["op"]
                if op in {"click", "fill", "select", "press", "wait", "capture"}:
                    _validate_locator(step.get("locator", {}))
                if op in {"click", "select", "press", "navigate", "open_tab"} and not step.get("expect"):
                    raise ValueError("Every transition requires explicit postconditions")
                if op in {"click", "press", "select"} and "effect" not in step:
                    raise ValueError("Transition must declare navigation, search or consequential effect")
                if op == "press" and step.get("key") not in {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Home", "End", "PageDown", "PageUp", "Space"}:
                    raise ValueError("Unsupported key")
                if op in {"fill", "select"} and "value" not in step:
                    raise ValueError("Form action requires an explicit value")
                if op in {"navigate", "open_tab"} and not step.get("url"):
                    raise ValueError("Navigation requires an explicit URL")
                if op == "close_tab" and not step.get("tab_id"):
                    raise ValueError("Closing requires an explicit tab ID")
                if op == "assert" and not step.get("expect"):
                    raise ValueError("Assert requires postconditions")
                if op in {"loop", "branch"}:
                    if "condition" not in step:
                        raise ValueError("Branch/loop requires a condition")
                    if op == "loop" and (not step.get("steps") or "max_iterations" not in step):
                        raise ValueError("Loop requires steps and a strict iteration bound")
                    if op == "branch" and not step.get("then") and not step.get("else"):
                        raise ValueError("Branch requires a bounded branch")
                if "condition" in step:
                    _validate_assertion(step["condition"])
                for assertion in step.get("expect", []):
                    _validate_assertion(assertion)
                for key in ("then", "else", "steps"):
                    if key in step:
                        if key not in ({"then", "else"} if op == "branch" else {"steps"} if op == "loop" else set()):
                            raise ValueError("Nested actions only belong to branch/loop")
                        steps(step[key])
        steps(args["steps"])
        if len(ids) > 100:
            raise ValueError("Plan has too many nested actions")
        for assertion in args["success"]:
            _validate_assertion(assertion)
    if name == "browser.tabs":
        if args["operation"] == "open" and any(not args.get(key, "").strip() for key in ("url", "purpose", "task_id")):
            raise ValueError("New tabs require URL, purpose and task")
        if args["operation"] == "close" and not args.get("tab_id"):
            raise ValueError("Close requires tab ID")
        if args["operation"] == "reset" and (not args.get("url", "").strip() or not args.get("task_id", "").strip() or args.get("customer_key") or args.get("tab_id") not in {None, "tab-1"}):
            raise ValueError("Reset requires a safe URL and new task on the primary tab, without a customer binding")
    if name == "browser.customer_summary":
        if not args["identity"] or not args["fields"] or any(not args[key].strip() for key in ("task_id", "customer_key")):
            raise ValueError("Customer summary needs explicit task, customer, identifiers and fields")
        if len({field["name"] for field in args["fields"]}) != len(args["fields"]):
            raise ValueError("Customer summary field names must be unique")
        for field in args["fields"]:
            _validate_locator(field["locator"])
    for identity in args.get("identity", []):
        _validate_locator(identity["locator"])
        if not identity["value"].strip():
            raise ValueError("Authorised identifiers cannot be empty")
    if name == "browser.plan" and args.get("customer_key") and not args.get("identity"):
        raise ValueError("Customer plans require explicit identity verification")


def safe_url(url):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _origin(url):
    parsed = urlsplit(url)
    return (parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))


def _url_policy(context):
    config = context.get("config", {})
    return URLPolicy([*config_value(config, "allowed_domains", []), *context.get("approved_domains", [])])


def _same_origin(url, reference, context):
    resolved = _url_policy(context).resolve(urljoin(reference, url))
    if _origin(resolved) != _origin(reference):
        raise PolicyError("Navigation crosses the exact website origin")
    return resolved


def _state(context):
    browser = context.get("browser")
    page = getattr(browser, "tool_page", None)
    if browser is None or page is None:
        raise PolicyError("Owned tool page is unavailable")
    if page is getattr(browser, "page", None) or page is getattr(browser, "chat_page", None):
        raise PolicyError("Copilot control page cannot be a tool page")
    if (getattr(page, "context", None) is not getattr(browser, "tool_context", None)
            or page not in getattr(browser, "_tool_pages", [page])):
        raise PolicyError("Tool page is not an owned website tab")
    state = getattr(browser, "_navigation_state", None)
    if state is None:
        state = {"tabs": {"tab-1": {"page": page, "purpose": "Primary workflow", "task_id": None,
                                  "customer_key": None, "customer_verified": False, "primary": True}},
                 "next_tab_id": getattr(browser, "_navigation_next_tab_id", 2), "site_maps": {}, "map_source_urls": {}, "plans": {}}
        browser._navigation_state = state
    return state


async def clear_navigation_state(browser):
    """Before a separately approved browser.open, release the prior origin guard.

    Call only after approval and URL-policy preflight. Preserve the primary page
    and control page; revoke ephemeral plans/maps and close known owned extras.
    The orchestrator clears its active task/customer/catalogues after the new
    navigation succeeds. A failed open retains those outer authorisation checks.
    """
    state = getattr(browser, "_navigation_state", None)
    if state is None:
        return
    primary = getattr(browser, "tool_page", None)
    control = {getattr(browser, "page", None), getattr(browser, "chat_page", None)}
    owned_context = getattr(browser, "tool_context", None)
    if (primary is None or primary in control or getattr(primary, "context", None) is not owned_context
            or primary not in getattr(browser, "_tool_pages", [primary])):
        raise PolicyError("Primary tool-page ownership changed")
    for page, guard in state.get("guards", {}).items():
        if page not in control and getattr(page, "context", None) is owned_context and not page.is_closed():
            await page.unroute("**/*", guard)
    for tab in state["tabs"].values():
        page = tab["page"]
        if page is not primary and page not in control and getattr(page, "context", None) is owned_context and not page.is_closed():
            await page.close()
    browser._navigation_next_tab_id = state["next_tab_id"]
    browser._navigation_state = None


def get_navigation_page(context, tab_id=None, task_id=None, customer_key=None):
    """Public lookup for document tooling; never redirect the Copilot/primary page."""
    active_task = context.get("task_id")
    active_customer = context.get("customer_key")
    if task_id is not None and active_task is not None and task_id != active_task:
        raise PolicyError("Requested task disagrees with the active authorised task")
    if customer_key is not None and active_customer is not None and customer_key != active_customer:
        raise PolicyError("Requested customer disagrees with the active authorised customer")
    task_id = active_task if task_id is None else task_id
    customer_key = active_customer if customer_key is None else customer_key
    tab = _state(context)["tabs"].get(tab_id or "tab-1")
    if tab is None or tab["page"].is_closed():
        raise PolicyError("Unknown or closed tool tab")
    if tab["customer_key"] is not None and customer_key is None:
        raise PolicyError("Customer-bound tab requires the exact active customer context")
    if (getattr(tab["page"], "context", None) is not getattr(context.get("browser"), "tool_context", None)
            or tab["page"] not in getattr(context.get("browser"), "_tool_pages", [tab["page"]])):
        raise PolicyError("Tab ownership changed")
    if task_id is not None and tab["task_id"] not in {None, task_id}:
        raise PolicyError("Tab belongs to another task")
    if customer_key is not None and tab["customer_key"] not in {None, customer_key}:
        raise PolicyError("Tab belongs to another customer")
    page = tab["page"]
    if page.url != "about:blank":
        _url_policy(context).resolve(page.url)
        primary = _state(context)["tabs"]["tab-1"]["page"]
        if primary.url != "about:blank":
            _same_origin(page.url, primary.url, context)
    return page


def _check_cancelled(context):
    callback = context.get("cancelled")
    if callable(callback) and callback():
        raise NavigationStop("cancelled", "User cancellation received")


class NavigationStop(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


RECON_SCRIPT = r"""({limit,textLimit}) => {
  const visible = n => !!n.getClientRects().length && getComputedStyle(n).visibility!=='hidden' && getComputedStyle(n).display!=='none';
  const clean = n => ['INPUT','TEXTAREA'].includes(n.tagName)||n.isContentEditable ? '' : String(n.innerText||n.textContent||'').trim().replace(/\s+/g,' ').slice(0,160);
  const all = [];
  let shadowCount=0;
  const visit = root => {for(const n of root.querySelectorAll('*')) {all.push(n);if(n.shadowRoot&&shadowCount<20){shadowCount++;visit(n.shadowRoot);}if(all.length>=6000)break;}};
  visit(document);
  const name = n => n.getAttribute('aria-label') || (n.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ').trim() || [...(n.labels||[])].map(l=>clean(l)).join(' ') || clean(n);
  const role = n => n.getAttribute('role') || ({A:'link',BUTTON:'button',SELECT:'combobox',TEXTAREA:'textbox',SUMMARY:'button',TABLE:'table'})[n.tagName] || (n.tagName==='INPUT'?({checkbox:'checkbox',radio:'radio',submit:'button',button:'button',number:'spinbutton'})[n.type]||'textbox':null);
  const locator = n => {const p={};if(n.id)p.id=n.id;if(n.dataset.testid)p.testid=n.dataset.testid;const r=role(n),label=name(n);if(r&&label){p.role=r;p.name=label.slice(0,160);}if(n.labels?.length)p.label=clean(n.labels[0]);if(!Object.keys(p).length&&clean(n))p.text=clean(n);return p;};
  const url = value => {try{const u=new URL(value,location.href);if(!['http:','https:'].includes(u.protocol))return null;return {url:u.origin+u.pathname,same_origin:u.origin===location.origin,query_omitted:!!u.search,fragment_omitted:!!u.hash};}catch(_){return null;}};
  const controls = all.filter(n=>visible(n)&&(role(n)||n.matches('input,textarea,[contenteditable=true],[role=tab]'))).slice(0,limit).map(n=>({tag:n.tagName.toLowerCase(),role:role(n),name:name(n).slice(0,160),locator:locator(n),type:n.getAttribute('type'),enabled:!n.matches(':disabled')&&n.getAttribute('aria-disabled')!=='true',selected:n.getAttribute('aria-selected')==='true'||n.checked===true,expanded:n.getAttribute('aria-expanded'),required:n.required===true||n.getAttribute('aria-required')==='true',href:n.hasAttribute('href')?url(n.getAttribute('href')):null}));
  const links=all.filter(n=>n.matches('a[href]')&&visible(n)).slice(0,limit).map(n=>({label:clean(n),locator:locator(n),...url(n.getAttribute('href')),download:n.hasAttribute('download'),document:/\.(pdf|docx?|xlsx?|csv|pptx?|zip|txt|png|jpe?g)$/i.test(new URL(n.href,location.href).pathname)})).filter(n=>n.url);
  const headings=all.filter(n=>n.matches('h1,h2,h3,[role=heading]')&&visible(n)).slice(0,16).map(n=>clean(n));
  const landmarks=all.filter(n=>n.matches('nav,main,header,footer,aside,[role=navigation],[role=main],[role=region]')&&visible(n)).slice(0,12).map(n=>({tag:n.tagName.toLowerCase(),name:name(n).slice(0,120),locator:locator(n)}));
  const forms=all.filter(n=>n.tagName==='FORM'&&visible(n)).slice(0,10).map(n=>({locator:locator(n),name:name(n).slice(0,120),method:(n.method||'get').toLowerCase(),action:url(n.action),fields:[...n.querySelectorAll('input,select,textarea')].filter(visible).slice(0,15).map(f=>({name:name(f).slice(0,120),type:f.type,required:f.required,locator:locator(f)}))}));
  const tables=all.filter(n=>n.matches('table,[role=table],[role=grid]')&&visible(n)).slice(0,8).map(n=>({locator:locator(n),headers:[...n.querySelectorAll('th,[role=columnheader]')].slice(0,15).map(clean),visible_rows:n.querySelectorAll('tr,[role=row]').length}));
  const frames=all.filter(n=>n.tagName==='IFRAME').slice(0,10).map(n=>({locator:locator(n),src:url(n.src),same_origin:!n.src||new URL(n.src,location.href).origin===location.origin}));
  const boundaries=all.filter(n=>n.matches('dialog,[role=dialog],[role=alertdialog],[aria-modal=true]')&&visible(n)).slice(0,8).map(n=>({role:n.getAttribute('role')||'dialog',name:name(n).slice(0,120),locator:locator(n)}));
  const notices=all.filter(n=>n.matches('[role=alert],h1,h2,[data-error],[role=status]')&&visible(n)).slice(0,12).map(clean);
  const password=all.some(n=>n.matches('input[type=password]')&&visible(n));
  const challenge=all.some(n=>n.matches('iframe')&&/captcha|recaptcha|hcaptcha/i.test(n.src||''))||all.some(n=>visible(n)&&(/captcha|verify you are human|human verification|security challenge/i).test(clean(n))&&n.matches('h1,h2,[role=alert],[role=dialog]'));
  const walker=document.createTreeWalker(document.body||document.documentElement,NodeFilter.SHOW_TEXT);
  let bodyText='',walked=0,node;
  while((node=walker.nextNode())&&walked++<6000&&bodyText.length<textLimit){const parent=node.parentElement;if(parent&&visible(parent)&&!parent.closest('input,textarea,[contenteditable=true],script,style'))bodyText+=' '+String(node.textContent||'').trim();}
  return {title:document.title.slice(0,160),headings,landmarks,controls,links,forms,tables,frames,boundaries,shadow_roots:shadowCount,notices,password,challenge,loading:!!all.find(n=>visible(n)&&n.matches('[aria-busy=true],[role=progressbar]')),text:bodyText.trim().replace(/\s+/g,' ').slice(0,textLimit),elements_truncated:controls.length===limit||links.length===limit};
}"""


def _stop_state(snapshot, url):
    text = " ".join([snapshot.get("title", ""), *snapshot.get("notices", [])]).casefold()
    if snapshot.get("challenge"):
        return "human_verification"
    if snapshot.get("password") or re.search(r"/(?:login|signin|sign-in|auth)(?:/|$)", urlsplit(url).path, re.I) or any(s in text for s in ("session expired", "sign in to continue", "authentication required")):
        return "authentication_required"
    if any(s in text for s in ("access denied", "permission denied", "not authorised", "not authorized", "forbidden")):
        return "access_denied"
    if any(s in text for s in ("too many requests", "rate limit", "try again later")):
        return "rate_limited"
    if any(s in text for s in ("internal server error", "service unavailable", "bad gateway")):
        return "server_error"
    if snapshot.get("loading"):
        return "loading"
    if not snapshot.get("headings") and not snapshot.get("controls") and not snapshot.get("text"):
        return "blank_page"
    return "ready"


async def _snapshot(page, context, max_elements=60, max_text_chars=1200):
    _check_cancelled(context)
    _url_policy(context).resolve(page.url)
    data = await page.evaluate(RECON_SCRIPT, {"limit": max_elements, "textLimit": max_text_chars})
    data.update({"url": safe_url(page.url), "origin": urlunsplit((*urlsplit(page.url)[:2], "", "", "")),
                 "observed_at": time.time(), "source": "authorised_live_dom", "state": _stop_state(data, page.url)})
    return data


async def _boundary(page, context):
    deadline = time.monotonic()+3
    while True:
        snapshot = await _snapshot(page, context, 8, 100)
        if snapshot["state"] not in {"loading", "blank_page"} or time.monotonic() >= deadline:
            break
        await asyncio.sleep(.1)
    state = snapshot["state"]
    if state in {"authentication_required", "human_verification", "access_denied", "rate_limited", "server_error", "loading", "blank_page"}:
        raise NavigationStop(state, "Website boundary requires authorised user intervention")
    return {"url": snapshot["url"], "state": state, "observed_at": snapshot["observed_at"]}


async def _scope(page, locator, context):
    selector = locator.get("frame_selector")
    if not selector:
        return page
    frame = page.locator(selector)
    if await frame.count() != 1 or (await frame.evaluate("n=>n.tagName")) != "IFRAME":
        raise NavigationStop("frame_unavailable", "Explicit iframe must be unique")
    src = await frame.get_attribute("src")
    if src and src != "about:blank":
        _same_origin(src, page.url, context)
    elif await frame.get_attribute("srcdoc") is None:
        raise PolicyError("Unresolved iframe origin")
    handle = await frame.element_handle()
    actual = await handle.content_frame() if handle is not None else None
    if actual is None:
        raise NavigationStop("frame_unavailable", "Iframe has not rendered")
    if actual.url not in {"about:srcdoc", "about:blank"}:
        _same_origin(actual.url, page.url, context)
    return page.frame_locator(selector)


async def _candidates(page, strategy, context):
    scope = await _scope(page, strategy, context)
    candidates = []
    if strategy.get("id"):
        candidates.append(("id", scope.locator('[id=' + json.dumps(strategy["id"]) + ']')))
    if strategy.get("testid"):
        candidates.append(("testid", scope.get_by_test_id(strategy["testid"])))
    if strategy.get("role"):
        candidates.append(("role", scope.get_by_role(strategy["role"], name=strategy["name"], exact=True)))
    if strategy.get("label"):
        candidates.append(("label", scope.get_by_label(strategy["label"], exact=True)))
    if strategy.get("text"):
        candidates.append(("text", scope.get_by_text(strategy["text"], exact=True)))
    if strategy.get("css"):
        candidates.append(("css", scope.locator(strategy["css"])))
    return candidates


async def _resolve(page, strategy, context, retries=0, visible=True):
    attempts = []
    for attempt in range(retries+1):
        _check_cancelled(context)
        for method, locator in await _candidates(page, strategy, context):
            count = await locator.count()
            attempts.append({"strategy": method, "matches": count, "retry": attempt})
            if count > 1:
                # Ambiguity is a hard stop; never silently choose a weaker locator.
                raise NavigationStop("ambiguous_locator", "Locator matches multiple elements")
            if count == 1 and (not visible or await locator.is_visible()):
                return locator, method, attempts
        if attempt < retries:
            await asyncio.sleep(.15*(attempt+1))
    raise NavigationStop("locator_unavailable", "No unique visible semantic locator matched")


async def _assertion(page, assertion, context, wait_ms=0):
    deadline = time.monotonic()+wait_ms/1000
    while True:
        _check_cancelled(context)
        kind = assertion["kind"]
        if kind == "url":
            expected = _same_origin(assertion["value"], page.url, context)
            observed = page.url == expected
        else:
            candidates = await _candidates(page, assertion["locator"], context)
            found = False
            observed = False
            for _, locator in candidates:
                count = await locator.count()
                if count > 1 and kind != "count":
                    raise NavigationStop("ambiguous_locator", "Assertion matches multiple elements")
                if kind == "count":
                    observed = count == assertion["count"]
                    if count:
                        found = True
                        break
                elif kind == "hidden":
                    observed = count == 0 or not await locator.is_visible()
                    if count:
                        found = True
                        break
                elif count == 1:
                    found = True
                    if kind == "visible":
                        observed = await locator.is_visible()
                    elif kind == "enabled":
                        observed = await locator.is_enabled()
                    elif kind == "text":
                        observed = (await locator.inner_text(timeout=1000)).strip() == assertion["value"].strip()
                    break
            if kind == "hidden" and not found:
                observed = True
        if observed or time.monotonic() >= deadline:
            return observed
        await asyncio.sleep(min(.1, max(0, deadline-time.monotonic())))


async def _verify(page, assertions, context, timeout_ms=3000):
    for assertion in assertions:
        if not await _assertion(page, assertion, context, timeout_ms):
            raise NavigationStop("verification_failed", "Expected page state was not observed")


async def _identity(page, identities, context):
    for identity in identities:
        locator, _, _ = await _resolve(page, identity["locator"], context)
        if (await locator.evaluate("n=>n.tagName")) in {"INPUT", "TEXTAREA"}:
            raise PolicyError("Identity evidence must be displayed source data, not an editable field")
        if (await locator.inner_text(timeout=1000)).strip() != identity["value"].strip():
            raise NavigationStop("customer_identity_mismatch", "Authorised customer identity did not match exactly")


async def _fingerprint(page):
    """Ephemeral digest only; never retain raw DOM/input contents or log them."""
    observed = await page.evaluate(r"""() => {
      const shown=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden';
      return {url:location.href,text:String(document.body?.innerText||'').slice(0,30000),
       values:[...document.querySelectorAll('input,textarea,select')].filter(n=>shown(n)&&!['password','file','hidden'].includes(n.type)).slice(0,100).map(n=>[n.id,n.name,n.value])};
    }""")
    return hashlib.sha256(json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _install_origin_guard(page, context, reference):
    """Block redirected main-frame/iframe navigation before crossing origins."""
    urls = _url_policy(context)
    async def guard(route):
        try:
            urls.resolve(route.request.url)
            if route.request.is_navigation_request():
                _same_origin(route.request.url, reference, context)
        except (PolicyError, ValueError):
            await route.abort("blockedbyclient")
        else:
            # Continue through the existing context guard and fixture routes.
            await route.fallback()
    state = _state(context)
    old = state.setdefault("guards", {}).get(page)
    if old is not None:
        await page.unroute("**/*", old)
    await page.route("**/*", guard)
    state["guards"][page] = guard


async def _consequential_control(locator, op):
    evidence = await locator.evaluate(r"""n => {
      const form=n.closest('form');
      const ids=(n.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ');
      const name=[n.getAttribute('aria-label')||'',ids,...[...(n.labels||[])].map(l=>l.textContent||''),
        ['INPUT','TEXTAREA'].includes(n.tagName)?'':n.innerText||'',n.name||''].join(' ');
      return {name,type:n.type||'',submit:!!form&&n.tagName==='BUTTON'&&(n.type||'submit')==='submit',method:form?.method||null};
    }""")
    name = evidence["name"].casefold()
    sensitive = re.search(r"\b(?:delete|approve|reject|send|save|update|pay|payment|purchase|transfer|withdraw|deposit|confirm|accept|grant|permission|security|password|mfa|2fa|consent|declaration|legal|terms)\b|\b(?:sign|log)[ -]?out\b", name)
    if sensitive:
        return True
    if op in {"fill", "select", "press"} and (evidence["type"] in {"email", "tel"} or re.search(r"\b(?:address|phone|contact|balance|amount|sort code|iban|card number)\b", name)):
        return True
    if op in {"click", "press"} and evidence["submit"] and evidence["method"] != "get" and not re.search(r"\b(?:search|find|filter|lookup)\b", name):
        return True
    return False


async def _open_tab(args, context, reference):
    state = _state(context)
    browser = context["browser"]
    limit = min(6, config_value(context.get("config", {}), "max_tool_tabs", 6))
    pages = [page for page in getattr(browser, '_tool_pages', []) if not page.is_closed()]
    if len(pages) >= limit:
        raise PolicyError("Owned tool-tab limit reached")
    url = _same_origin(args["url"], reference, context)
    page = None
    try:
        page = await browser.new_tool_page()
        await _install_origin_guard(page, context, reference)
        tab_id = f'tab-{state["next_tab_id"]}'
        state["next_tab_id"] += 1
        browser._navigation_next_tab_id = state["next_tab_id"]
        state["tabs"][tab_id] = {"page": page, "purpose": args.get("purpose", "Plan subtask"),
                                 "task_id": args["task_id"], "customer_key": args.get("customer_key"),
                                 "customer_verified": False, "primary": False}
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        _same_origin(page.url, reference, context)
        await _boundary(page, context)
        return tab_id
    except Exception:
        if page is not None and not page.is_closed():
            await page.close()
        raise


async def _close_tab(tab_id, context, task_id=None, customer_key=None):
    state = _state(context)
    tab = state["tabs"].get(tab_id)
    if tab is None:
        raise PolicyError("Unknown tab ID")
    if tab["primary"]:
        raise PolicyError("Primary workflow tab must remain open")
    page = get_navigation_page(context, tab_id, task_id, customer_key)
    await page.close()
    return {"tab_id": tab_id, "status": "closed"}


async def _reset_tabs(args, context):
    state = _state(context)
    primary = state["tabs"]["tab-1"]
    page = primary["page"]
    url = _same_origin(args["url"], page.url, context)
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment:
        raise PolicyError("Safe context reset URL must not contain task/customer parameters")
    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
    if page.url != url:
        raise PolicyError("Safe reset route redirected; verify and approve its actual destination first")
    checkpoint = await _boundary(page, context)
    for identity in primary.get("customer_identity", []):
        try:
            locator, _, _ = await _resolve(page, identity["locator"], context)
        except NavigationStop as exc:
            if exc.code == "locator_unavailable":
                continue
            raise
        if (await locator.evaluate("n=>n.tagName")) not in {"INPUT", "TEXTAREA"} and (await locator.inner_text(timeout=1000)).strip() == identity["value"].strip():
            raise PolicyError("Safe reset route still displays the previous customer identity")
    snapshot = await _snapshot(page, context, 8, 100)
    if any(re.search(r"\b(?:customer|account) (?:profile|details)\b", heading, re.I) for heading in snapshot["headings"]):
        raise PolicyError("Customer profile pages are not safe context reset destinations")
    for tab_id, tab in state["tabs"].items():
        if tab_id != "tab-1" and not tab["page"].is_closed():
            await tab["page"].close()
    primary.update({"task_id": args["task_id"], "customer_key": None, "customer_verified": False})
    primary.pop("customer_identity", None)
    state["tabs"] = {"tab-1": primary}
    state["guards"] = {page: guard for page, guard in state.get("guards", {}).items() if not page.is_closed()}
    state["plans"].clear()
    state["site_maps"].clear()
    state.setdefault("map_source_urls", {}).clear()
    return {"status": "reset", "task_id": args["task_id"], "tab_id": "tab-1", "verified_state": checkpoint,
            "prior_context_cleared": True, "tabs": _tab_list(context)}


def _tab_list(context):
    return [{"tab_id": key, "purpose": tab["purpose"], "primary": tab["primary"],
             "url": safe_url(tab["page"].url), "state": "closed" if tab["page"].is_closed() else "open",
             "task_bound": bool(tab["task_id"]), "customer_bound": bool(tab["customer_key"]),
             "customer_verified": tab["customer_verified"]}
            for key, tab in _state(context)["tabs"].items()]


def plan_hash(args):
    immutable = {key: value for key, value in args.items() if key != "resume_token"}
    return hashlib.sha256(json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _compact_recon(snapshot, context):
    """Keep the broad map and categories within the tool result envelope budget."""
    result = json.loads(json.dumps(snapshot))
    budget = min(12000, max(1000, config_value(context.get("config", {}), "max_output_chars", 12000)))-300
    omitted = {}
    categories = ("controls", "links", "documents", "forms", "tables", "landmarks", "headings", "frames", "boundaries", "notices")
    while len(json.dumps(result, ensure_ascii=False)) > budget:
        arrays = [(key, result[key]) for key in categories if result.get(key)]
        routes = result["site_map"]["routes"]
        if routes:
            arrays.append(("site_map.routes", routes))
        # Preserve at least one entry in each discovery category while possible;
        # lower-scoring tail routes/controls disappear first.
        candidates = [(key, values) for key, values in arrays if len(values) > 1]
        if not candidates:
            if len(result.get("text", "")) > 100:
                result["text"] = result["text"][:max(100, len(result["text"])//2)]
                result["text_truncated"] = True
                continue
            candidates = arrays
        if not candidates:
            break
        key, values = max(candidates, key=lambda entry: len(json.dumps(entry[1], ensure_ascii=False)))
        values.pop()
        omitted[key] = omitted.get(key, 0)+1
    if omitted:
        result["omitted_counts"] = omitted
        result["elements_truncated"] = True
    return result


async def _execute_plan(args, context):
    state = _state(context)
    digest = plan_hash(args)
    tab_id = args.get("tab_id", "tab-1")
    page = get_navigation_page(context, tab_id, args["task_id"], args.get("customer_key"))
    tab = state["tabs"][tab_id]
    if (tab["customer_key"] or context.get("customer_key")) and not args.get("customer_key"):
        raise PolicyError("Customer-context plans require explicit customer identity checkpoints")
    if args.get("resume_token"):
        record = state["plans"].get(args["resume_token"])
        if not record or record["hash"] != digest:
            raise PolicyError("Resume token does not match the exact approved plan")
        if record["uncertain_step"]:
            raise PolicyError("Uncertain side effect requires inspection and a new explicit plan")
        tab_id = record.get("verified_tab_id", tab_id)
        page = get_navigation_page(context, tab_id, args["task_id"], args.get("customer_key"))
        if page.url != record["verified_raw_url"]:
            raise PolicyError("Page moved away from the last verified resumable state")
        if record.get("verified_fingerprint") and await _fingerprint(page) != record["verified_fingerprint"]:
            raise PolicyError("Page changed since the last verified state; inspect and approve a fresh plan")
        # Reverify every prior checkpoint at its current state only if it was the
        # last completed top-level transition; earlier pages may no longer exist.
        if record.get("last_assertions"):
            await _verify(page, record["last_assertions"], context, 1000)
        token = args["resume_token"]
    else:
        if len(state["plans"]) >= 30:
            raise PolicyError("Session plan retention limit reached")
        token = uuid.uuid4().hex
        record = {"hash": digest, "plan_id": uuid.uuid4().hex, "completed": set(), "results": [],
                  "uncertain_step": None, "verified_raw_url": page.url, "last_assertions": [],
                  "origin_url": page.url, "decisions": {}, "total_actions": 0,
                  "verified_fingerprint": await _fingerprint(page),
                  "last_verified": {"url": safe_url(page.url), "state": "not_verified"}}
        state["plans"][token] = record
    initial_origin_url = record["origin_url"]
    counters = {"actions": 0, "locator_retries": 0}
    active_path = None
    effect_in_progress = False
    timeout = args.get("timeout_seconds", 60)
    deadline = time.monotonic()+timeout

    def limits():
        _check_cancelled(context)
        if time.monotonic() >= deadline:
            raise NavigationStop("time_limit", "Plan execution time limit reached")
        if record["total_actions"] >= args.get("max_actions", 80):
            raise NavigationStop("action_limit", "Plan action limit reached")

    async def sequence(items, prefix=""):
        nonlocal page, tab_id, active_path, effect_in_progress
        for step in items:
            path = prefix+step["id"]
            active_path = path
            if path in record["completed"]:
                continue
            limits()
            if step.get("tab_id"):
                tab_id = step["tab_id"]
                page = get_navigation_page(context, tab_id, args["task_id"], args.get("customer_key"))
            await _boundary(page, context)
            if args.get("customer_key"):
                await _identity(page, args["identity"], context)
                state["tabs"][tab_id]["customer_verified"] = True
            op = step["op"]
            counters["actions"] += 1
            record["total_actions"] += 1
            started = time.monotonic()
            result = {"step_id": path, "op": op, "tab_id": tab_id, "verification": "pending", "retry_count": 0}
            if op == "branch":
                branch = record["decisions"].get(path)
                if branch is None:
                    branch = "then" if await _assertion(page, step["condition"], context) else "else"
                    record["decisions"][path] = branch
                result["branch"] = branch
                await sequence(step.get(branch, []), path+"/"+branch+"/")
            elif op == "loop":
                terminated = False
                for iteration in range(step["max_iterations"]):
                    limits()
                    decision_id = path+f"/{iteration}"
                    if decision_id not in record["decisions"]:
                        record["decisions"][decision_id] = await _assertion(page, step["condition"], context)
                    if not record["decisions"][decision_id]:
                        terminated = True
                        break
                    await sequence(step["steps"], path+f"/{iteration}/")
                if not terminated and await _assertion(page, step["condition"], context):
                    raise NavigationStop("loop_limit", "Loop condition remained true at its strict limit")
            elif op == "assert":
                await _verify(page, step["expect"], context, step.get("timeout_ms", 3000))
            elif op == "open_tab":
                tab_id = await _open_tab({**step, "task_id": args["task_id"], "customer_key": args.get("customer_key")}, context, initial_origin_url)
                page = get_navigation_page(context, tab_id, args["task_id"], args.get("customer_key"))
                result["tab_id"] = tab_id
                result["opened_tab_id"] = tab_id
            elif op == "close_tab":
                await _close_tab(step["tab_id"], context, args["task_id"], args.get("customer_key"))
                tab_id = args.get("tab_id", "tab-1")
                page = get_navigation_page(context, tab_id, args["task_id"], args.get("customer_key"))
            elif op == "navigate":
                target = _same_origin(step["url"], initial_origin_url, context)
                _check_cancelled(context)
                effect_in_progress = True
                await page.goto(target, wait_until="domcontentloaded", timeout=step.get("timeout_ms", 15000))
                _same_origin(page.url, initial_origin_url, context)
            else:
                if op == "wait":
                    # Resolve with fallbacks during hydration, without acting.
                    end = min(deadline, time.monotonic()+step.get("timeout_ms", 5000)/1000)
                    while True:
                        try:
                            locator, strategy, attempted = await _resolve(page, step["locator"], context)
                            break
                        except NavigationStop as exc:
                            if exc.code != "locator_unavailable" or time.monotonic() >= end:
                                raise
                            await asyncio.sleep(.1)
                else:
                    locator, strategy, attempted = await _resolve(page, step["locator"], context, step.get("locator_retries", 1))
                result["locator_strategy"] = strategy
                result["retry_count"] = max(item["retry"] for item in attempted)
                counters["locator_retries"] += result["retry_count"]
                if op == "capture":
                    if (await locator.evaluate("n=>n.tagName")) in {"INPUT", "TEXTAREA"} or await locator.get_attribute("contenteditable") == "true":
                        raise PolicyError("Capture cannot expose editable input contents")
                    result["capture"] = (await locator.inner_text(timeout=1000))[:step.get("max_chars", 1000)]
                elif op != "wait":
                    if (await locator.get_attribute("type") or "").lower() in {"password", "file"}:
                        raise PolicyError("Password and upload controls are unavailable to navigation plans")
                    if not await locator.is_enabled():
                        raise NavigationStop("control_disabled", "Selected control is disabled")
                    consequential = step.get("effect") == "consequential" or await _consequential_control(locator, op)
                    if consequential and context.get("consequential_approved_plan_hash") != digest:
                        raise NavigationStop("confirmation_required", "Consequential action requires a separate exact local approval")
                    if op == "click":
                        href = await locator.get_attribute("href")
                        if href:
                            _same_origin(href, page.url, context)
                            if await locator.get_attribute("target") == "_blank":
                                raise NavigationStop("explicit_tab_required", "Open this link with an explicit managed-tab step")
                        await locator.click(trial=True, timeout=step.get("timeout_ms", 3000))
                        _check_cancelled(context)
                        effect_in_progress = True
                        await locator.click(timeout=step.get("timeout_ms", 3000))
                    elif op == "fill":
                        _check_cancelled(context)
                        effect_in_progress = True
                        await locator.fill(step["value"], timeout=step.get("timeout_ms", 3000))
                        if await locator.input_value(timeout=1000) != step["value"]:
                            raise NavigationStop("verification_failed", "Entered field value did not match")
                    elif op == "select":
                        _check_cancelled(context)
                        effect_in_progress = True
                        await locator.select_option(value=step["value"], timeout=step.get("timeout_ms", 3000))
                        if await locator.input_value(timeout=1000) != step["value"]:
                            raise NavigationStop("verification_failed", "Selected option did not remain selected")
                    elif op == "press":
                        _check_cancelled(context)
                        effect_in_progress = True
                        await locator.press(step["key"], timeout=step.get("timeout_ms", 3000))
                    _same_origin(page.url, initial_origin_url, context)
            await _verify(page, step.get("expect", []), context, step.get("timeout_ms", 3000))
            if args.get("customer_key"):
                await _identity(page, args["identity"], context)
                state["tabs"][tab_id]["customer_verified"] = True
            record["last_verified"] = await _boundary(page, context)
            record["verified_raw_url"] = page.url
            record["last_assertions"] = step.get("expect", [])
            record["verified_tab_id"] = tab_id
            record["verified_fingerprint"] = await _fingerprint(page)
            effect_in_progress = False
            active_path = path
            result.update({"verification": "passed", "duration_ms": round((time.monotonic()-started)*1000),
                           "url": safe_url(page.url)})
            record["results"].append(result)
            record["completed"].add(path)

    status = "verified"
    error = None
    try:
        tab["task_id"] = args["task_id"]
        if args.get("customer_key"):
            await _identity(page, args["identity"], context)
            tab["customer_key"] = args["customer_key"]
            tab["customer_verified"] = True
            tab["customer_identity"] = args["identity"]
        async with asyncio.timeout(timeout):
            await sequence(args["steps"])
            await _verify(page, args["success"], context, 3000)
            record["last_verified"] = await _boundary(page, context)
            record["verified_raw_url"] = page.url
            record["verified_fingerprint"] = await _fingerprint(page)
    except asyncio.CancelledError:
        status = "cancelled"
        if effect_in_progress:
            record["uncertain_step"] = active_path
        error = {"code": "cancelled", "step_id": active_path,
                 "message": "Plan cancellation preserved its last verified state"}
    except Exception as exc:
        status = "interrupted"
        code = exc.code if isinstance(exc, NavigationStop) else "policy_denied" if isinstance(exc, PolicyError) else "timeout" if isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutError" else "operation_failed"
        if effect_in_progress:
            record["uncertain_step"] = active_path
        error = {"code": code, "step_id": active_path,
                 "message": str(exc) if isinstance(exc, (NavigationStop, PolicyError)) else "Browser operation failed; inspect the verified partial state"}
    output = {"status": status, "plan_id": record["plan_id"], "task_id": args["task_id"],
              "plan_hash": digest, "resume_token": token, "completed_steps": len(record["completed"]),
              "results": list(record["results"]), "last_verified_state": dict(record["last_verified"]),
              "uncertain_step": record["uncertain_step"], "metrics": counters,
              "side_effects_uncertain": bool(record["uncertain_step"]),
              "total_actions": record["total_actions"],
              "next_action": "complete" if status == "verified" else "inspect_and_prepare_new_plan" if record["uncertain_step"] else "repair_precondition_then_resume_exact_plan"}
    if error:
        output["error"] = error
    return output


async def execute_navigation(name, args, context, policy=None):
    validate_navigation(name, args, context)
    _check_cancelled(context)
    if NAVIGATION_SPECS[name][1] != "read_only" and not context.get("approved"):
        raise PolicyError("Navigation plan/tab/customer operation requires explicit approval")
    if name == "browser.tabs" and args["operation"] == "reset":
        state = _state(context)
        primary = state["tabs"]["tab-1"]
        page = get_navigation_page(context, "tab-1", primary["task_id"], primary["customer_key"])
    else:
        page = get_navigation_page(context, args.get("tab_id"), args.get("task_id"), args.get("customer_key"))
    await _install_origin_guard(page, context, page.url)
    if name == "browser.recon":
        snapshot = await _snapshot(page, context, args.get("max_elements", 60), args.get("max_text_chars", 1200))
        tokens = set(re.findall(r"[a-z0-9]+", args.get("goal", "").lower()))
        routes = [link for link in snapshot["links"] if link["same_origin"]]
        for route in routes:
            route["relevance"] = len(tokens & set(re.findall(r"[a-z0-9]+", (route["label"]+" "+route["url"]).lower())))
        routes.sort(key=lambda route: (-route["relevance"], route["url"], route["label"]))
        snapshot["documents"] = [link for link in snapshot["links"] if link["same_origin"] and (link["document"] or link["download"])]
        site_map = {"schema_version": "1", "origin": snapshot["origin"], "source_url": snapshot["url"],
                    "observed_at": snapshot["observed_at"], "expires_at": snapshot["observed_at"]+1800,
                    "scope": "ephemeral_authorised_session", "routes": routes[:40], "page_purpose": snapshot["headings"][:3],
                    "authentication": snapshot["state"], "confidence": "observed"}
        _state(context)["site_maps"][args.get("tab_id", "tab-1")] = site_map
        _state(context).setdefault("map_source_urls", {})[args.get("tab_id", "tab-1")] = page.url
        snapshot["site_map"] = site_map
        snapshot.pop("password", None)
        snapshot.pop("challenge", None)
        return _compact_recon(snapshot, context)
    if name == "browser.route":
        knowledge = _state(context)["site_maps"].get(args.get("tab_id", "tab-1"))
        if not knowledge:
            return {"status": "recon_required", "routes": []}
        original_url = _state(context).setdefault("map_source_urls", {}).get(args.get("tab_id", "tab-1"))
        if knowledge["expires_at"] < time.time() or original_url != page.url:
            return {"status": "stale", "routes": [], "next_action": "browser.recon"}
        tokens = set(re.findall(r"[a-z0-9]+", args["goal"].lower()))
        matches = []
        for route in knowledge["routes"]:
            score = len(tokens & set(re.findall(r"[a-z0-9]+", (route["label"]+" "+route["url"]).lower())))
            if score:
                matches.append({"url": route["url"], "label": route["label"], "locator": route["locator"],
                                "score": score, "confidence": "observed", "navigation_requires_locator": route["query_omitted"] or route["fragment_omitted"]})
        matches.sort(key=lambda route: (-route["score"], route["url"]))
        return {"status": "observed" if matches else "no_observed_route", "routes": matches[:8], "source_url": knowledge["source_url"], "observed_at": knowledge["observed_at"]}
    if name == "browser.tabs":
        if args["operation"] == "reset":
            return await _reset_tabs(args, context)
        if args["operation"] == "open":
            tab_id = await _open_tab(args, context, page.url)
            return {"status": "opened", "tab_id": tab_id, "tabs": _tab_list(context)}
        if args["operation"] == "close":
            return await _close_tab(args["tab_id"], context, args.get("task_id"), args.get("customer_key"))
        return {"tabs": _tab_list(context)}
    if name == "browser.plan":
        return await _execute_plan(args, context)
    if name == "browser.customer_summary":
        tab = _state(context)["tabs"][args.get("tab_id", "tab-1")]
        await _boundary(page, context)
        await _identity(page, args["identity"], context)
        tab.update({"task_id": args["task_id"], "customer_key": args["customer_key"], "customer_verified": True,
                    "customer_identity": args["identity"]})
        facts = []
        missing = []
        for field in args["fields"]:
            try:
                locator, strategy, _ = await _resolve(page, field["locator"], context)
                if (await locator.evaluate("n=>n.tagName")) in {"INPUT", "TEXTAREA"} or await locator.get_attribute("contenteditable") == "true":
                    raise PolicyError("Summary cannot expose editable input contents")
                text = (await locator.inner_text(timeout=1000)).strip()[:1000]
                facts.append({"field": field["name"], "value": text, "source_url": safe_url(page.url), "locator_strategy": strategy, "evidence": "observed"})
            except NavigationStop as exc:
                missing.append({"field": field["name"], "reason": exc.code})
        return {"status": "verified" if not missing else "partial", "identity_verified": True,
                "side_effects_uncertain": False,
                "facts": facts, "missing": missing, "inferences": [], "persistence": "ephemeral_only"}
    raise ValueError("Unknown navigation capability")
