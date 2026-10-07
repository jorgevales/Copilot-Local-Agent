"""Consent-bound, per-device navigation memory; no customer observations.

This module is synchronous. The orchestrator alone injects approval context,
``site_knowledge_reviewed`` and (for saves) ``site_knowledge_consent`` after its
real local approval prompt. Tool arguments cannot supply these capabilities.
Bindings live only in the current session's shared ``site_knowledge_bindings``
dictionary. A resumed/new session must obtain a fresh local namespace grant.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from .policy import PathPolicy, PolicyError, URLPolicy, reject_path_redirection
from .protocol import validate_schema

SCHEMA_VERSION = 1
MAX_BYTES = 131072
MAX_ITEMS = 120
CATEGORIES = ("routes", "locators", "forms", "document_areas", "recovery")
EXCLUDED_DATA = [
    "Customer identities, names, identifiers, contact details and document content",
    "Concrete customer/account/case/document route parameters, URL queries and fragments",
    "Form values, credentials, tokens, cookies, secrets and sensitive page text",
]


def _object(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def _string(length=160):
    return {"type": "string", "minLength": 1, "maxLength": length}


def _enum(values):
    return {"type": "string", "enum": list(values)}


PURPOSES = ("landing", "navigation", "search", "profile", "accounts", "cases",
            "transactions", "documents", "settings", "help")
PATH = _string(320)
LABEL = _string(100)
ROUTE = _object({"path": PATH, "purpose": _enum(PURPOSES), "label": LABEL,
                 "parent_path": PATH}, ["path", "purpose"])
LOCATOR = _object({"path": PATH, "purpose": _enum(PURPOSES),
                   "strategy": _enum(("role", "label", "test_id", "css")),
                   "value": LABEL,
                   "role": _enum(("button", "link", "textbox", "searchbox", "combobox",
                                  "tab", "checkbox", "radio", "menuitem", "heading"))},
                  ["path", "purpose", "strategy", "value"])
FIELD = _object({"label": LABEL, "required": {"type": "boolean"},
                 "input_type": _enum(("text", "search", "email", "tel", "number",
                                      "date", "select", "checkbox", "radio"))})
FORM = _object({"path": PATH, "purpose": _enum(("customer_search", "navigation", "document_filter")),
                "fields": {"type": "array", "items": FIELD, "minItems": 1, "maxItems": 20}})
DOCUMENT_AREA = _object({"path": PATH, "label": LABEL,
                         "file_types": {"type": "array", "maxItems": 10, "uniqueItems": True,
                                        "items": _enum(("pdf", "docx", "xlsx", "csv", "txt", "zip", "png", "jpg"))}},
                        ["path"])
RECOVERY = _object({"path": PATH,
                    "failure": _enum(("layout_changed", "selector_missing", "slow_render", "overlay",
                                      "auth_expired", "access_denied", "captcha", "rate_limited",
                                      "navigation_timeout", "document_unavailable", "download_failed")),
                    "steps": {"type": "array", "minItems": 1, "maxItems": 5,
                              "items": _enum(("reinspect_page", "wait_ready", "use_locator_fallback",
                                              "return_to_safe_route", "ask_user", "stop"))}})
CATEGORY_SCHEMAS = dict(zip(CATEGORIES, (ROUTE, LOCATOR, FORM, DOCUMENT_AREA, RECOVERY)))
KNOWLEDGE = _object({key: {"type": "array", "items": schema, "minItems": 1, "maxItems": 40}
                     for key, schema in CATEGORY_SCHEMAS.items()}, [])
ORIGIN = _string(280)
SCOPE_LABEL = {"type": "string", "minLength": 1, "maxLength": 64,
               "pattern": r"^[a-z][a-z0-9-]{0,63}$"}
BIND = _object({"origin": ORIGIN, "tenant": SCOPE_LABEL, "user_scope": SCOPE_LABEL,
                "environment": _enum(("production", "test", "staging", "development"))})
SAVE = _object({"origin": ORIGIN,
                "categories": {"type": "array", "items": _enum(CATEGORIES), "minItems": 1,
                               "maxItems": len(CATEGORIES), "uniqueItems": True},
                "knowledge": KNOWLEDGE,
                "ttl_days": {"type": "integer", "minimum": 1, "maximum": 90}},
               ["origin", "categories", "knowledge"])
QUERY = _object({"origin": ORIGIN, "category": _enum(CATEGORIES), "route": PATH}, ["origin"])

KNOWLEDGE_SPECS = {
    "site_knowledge.bind": (BIND, "user_approval", "Select the current HTTPS site's exact tenant, user/sharing scope and environment through local approval. Scope labels are user-declared; never infer an authenticated identity. No website knowledge is saved."),
    "site_knowledge.retrieve": (_object({"origin": ORIGIN}), "read_only", "Retrieve unexpired approved navigation knowledge for the current locally selected site namespace; a namespace must first be bound by the user."),
    "site_knowledge.query": (QUERY, "read_only", "Filter approved fresh navigation knowledge by category and/or exact generic route template inside the selected namespace."),
    "site_knowledge.save": (SAVE, "user_approval", "Ask the local user whether to save the exact approved categories of sanitized navigation knowledge on this Windows user/device. Declining leaves the current task usable. Customer data and secrets are rejected. Replaces the namespace's prior knowledge after approval."),
    "site_knowledge.invalidate": (_object({"origin": ORIGIN}), "user_approval", "After local approval, mark the selected namespace's knowledge unusable. It remains on disk as an invalidated record; never automatically re-use it."),
    "site_knowledge.export": (_object({"origin": ORIGIN}), "read_only", "Return a bounded structured summary of fresh knowledge for the approved namespace through the tool result; no arbitrary file export."),
}

KNOWLEDGE_EXAMPLES = {
    "site_knowledge.bind": {"origin": "https://example.com", "tenant": "tenant-a", "user_scope": "private-user", "environment": "test"},
    "site_knowledge.retrieve": {"origin": "https://example.com"},
    "site_knowledge.query": {"origin": "https://example.com", "category": "routes"},
    "site_knowledge.save": {"origin": "https://example.com", "categories": ["routes"],
                            "knowledge": {"routes": [{"path": "/customers/search", "purpose": "search", "label": "Customer search"}]},
                            "ttl_days": 30},
    "site_knowledge.invalidate": {"origin": "https://example.com"},
    "site_knowledge.export": {"origin": "https://example.com"},
}

# Deliberately closed vocabulary: generic navigation knowledge must not become
# a free-text customer store. Unusual website labels can stay in ephemeral maps.
SAFE_WORDS = frozenset("""
    a an the to of for and or by with all my your our current previous next first last
    home landing dashboard portal workspace main index navigation menu breadcrumb
    customer customers client clients investor investors user users member members
    account accounts profile profiles case cases transaction transactions policy policies
    contact contacts person people employee employees organisation organisations organization organizations
    document documents file files attachment attachments report reports statement statements
    product products history activity activities summary overview details detail status
    search lookup find filter filters result results list lists table tables page pages pagination
    new create add edit update delete remove save submit cancel reset clear close open view show
    select selected choose selection download downloads upload uploads export exports import
    settings preferences configuration manage management admin administration operations
    compliance audit kyc cdd onboarding support help knowledge center centre information
    sign login logout authentication access denied expired session retry recover recovery
    refresh reload wait ready loading error errors warning warnings empty continue back forward
    public private shared secure security identity identifier reference id number name email phone
    telephone mobile address date birth first last full given family surname required optional
    text number checkbox radio select date email tel pdf docx xlsx csv txt zip png jpg
    link button textbox searchbox combobox tab tabs menuitem heading label role test testid
    data field fields form forms input inputs content section sections area areas record records
    retail business finance financial service services organisation tenant environment production
    staging development test account-search customer-search client-search search-customer search-client
""".split())
SAFE_SEGMENTS = SAFE_WORDS | frozenset({"customer-search", "client-search", "account-search",
                                      "document-search", "sign-in", "sign-out", "help-center",
                                      "customer-service", "case-management"})
PLACEHOLDERS = frozenset({"{customer}", "{account}", "{case}", "{document}", "{item}"})
ENTITY_SEGMENTS = frozenset("customer customers client clients investor investors user users member members account accounts profile profiles case cases transaction transactions policy policies contact contacts person people employee employees document documents file files record records".split())
STATIC_CHILDREN = frozenset("search lookup find list overview details summary status documents files history activity transactions accounts cases settings new create edit download downloads reports statements products contacts profile profiles landing index".split())


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _origin(value):
    if type(value) is not str:
        raise ValueError("A canonical HTTPS origin is required")
    try:
        host = URLPolicy.website_domain(value)
        parsed = urlsplit(value)
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.netloc.lower().rstrip(".") != host:
            raise ValueError("Use a canonical HTTPS origin without paths, credentials or URL parameters")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?", host):
            raise ValueError("A plain HTTPS hostname is required")
    except (ValueError, TypeError) as error:
        raise ValueError("Use a canonical HTTPS origin without paths, credentials or URL parameters") from error
    return "https://" + host


def _current_origin(context):
    browser = context.get("browser")
    page = getattr(browser, "tool_page", None)
    value = getattr(page, "url", None)
    if not isinstance(value, str):
        raise PolicyError("An active owned website tab is required for website memory")
    isolated = getattr(browser, "tool_context", None)
    if (isolated is None or getattr(page, "context", None) is not isolated
            or page is getattr(browser, "page", None) or page is getattr(browser, "chat_page", None)):
        raise PolicyError("Website memory requires a tab owned by the isolated website context")
    if hasattr(page, "is_closed") and page.is_closed():
        raise PolicyError("The owned website tab is closed")
    try:
        parsed = urlsplit(value)
        URLPolicy.website_domain(value)
        return _origin("https://" + parsed.hostname.lower().rstrip("."))
    except (ValueError, TypeError) as error:
        raise PolicyError("Website memory requires the current owned HTTPS tab") from error


def _session(context):
    directory = context.get("session_dir")
    if not directory:
        raise PolicyError("A local session identity is required")
    return _hash(str(Path(directory).absolute()))


def knowledge_directory(context):
    """Context-only test override; never an LLM tool argument or shared runtime."""
    selected = context.get("knowledge_directory")
    if selected is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise PolicyError("Per-user LocalAppData storage is unavailable; keep website knowledge ephemeral")
        selected = Path(local) / "CopilotLocalAgent" / "site-knowledge"
    raw = Path(selected).expanduser().absolute()
    reject_path_redirection(raw)
    return raw


def _scope(name, args, context):
    origin = _origin(args["origin"])
    if origin != _current_origin(context):
        raise PolicyError("Website memory origin differs from the current owned tab")
    if name == "site_knowledge.bind":
        return {"origin": origin, "tenant": args["tenant"], "user_scope": args["user_scope"],
                "environment": args["environment"], "schema_version": SCHEMA_VERSION}
    bindings = context.get("site_knowledge_bindings")
    binding = bindings.get(origin) if type(bindings) is dict else None
    if (type(binding) is not dict or binding.get("session") != _session(context)
            or not _digest(binding.get("approval_hash")) or not _digest(binding.get("review_sha256"))
            or type(binding.get("scope")) is not dict):
        raise PolicyError("The local user must bind this site's tenant, user scope and environment first")
    scope = binding["scope"]
    expected = {"origin", "tenant", "user_scope", "environment", "schema_version"}
    if set(scope) != expected or scope.get("origin") != origin or scope.get("schema_version") != SCHEMA_VERSION:
        raise PolicyError("The website namespace binding is invalid; obtain a fresh local grant")
    if validate_schema({key: scope[key] for key in BIND["properties"]}, BIND):
        raise PolicyError("The website namespace binding is invalid; obtain a fresh local grant")
    return deepcopy(scope)


def _safe_route(value):
    if (not value.startswith("/") or "//" in value or value != value.strip()
            or any(char in value for char in "?&=#%@.:;\\") or len(value) > 320):
        raise ValueError("Persist only generic route templates without URL parameters or concrete identifiers")
    parts = [part for part in value.split("/") if part]
    if len(parts) > 12 or any(part not in SAFE_SEGMENTS and part not in PLACEHOLDERS for part in parts):
        raise ValueError("Route contains unsupported or customer-specific segments; use generic navigation routes and parameter placeholders")
    for parent, child in zip(parts, parts[1:]):
        if parent in ENTITY_SEGMENTS and child not in STATIC_CHILDREN and child not in PLACEHOLDERS:
            raise ValueError("Concrete entity route parameters are excluded; use a generic parameter placeholder")
    return value


def _safe_label(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z /()_-]{0,99}", value):
        raise ValueError("Navigation labels must exclude identifiers, contact details and secrets")
    words = re.findall(r"[a-z]+", value.lower())
    if not words or any(word not in SAFE_WORDS for word in words):
        raise ValueError("Only generic navigation labels are reusable; customer names and free text are excluded")


def _safe_locator(item):
    value = item["value"]
    if item["strategy"] == "role" and "role" not in item:
        raise ValueError("Role locators require an explicit accessibility role")
    if item["strategy"] != "css":
        _safe_label(value)
        return
    # Structural tags and generic static identifiers only; never attribute
    # values, XPath, input values, URL matching or script/pseudo selectors.
    if not re.fullmatch(r"[A-Za-z.#_ -]+", value):
        raise ValueError("Persistent CSS locators require simple structural tags or generic static identifiers")
    for component in re.split(r"[.#_ -]+", value.lower()):
        if component and component not in SAFE_WORDS | {"a", "button", "input", "form", "nav", "main", "div", "section", "ul", "li", "span"}:
            raise ValueError("Persistent CSS selectors contain unsupported or customer-specific identifiers")


def _sanitize_knowledge(args):
    categories = args["categories"]
    knowledge = args["knowledge"]
    if set(categories) != set(knowledge):
        raise ValueError("Saved knowledge must contain exactly the categories requested for local consent")
    if sum(len(items) for items in knowledge.values()) > MAX_ITEMS:
        raise ValueError("Website memory exceeds the bounded record limit")
    for category, items in knowledge.items():
        for item in items:
            _safe_route(item["path"])
            if "parent_path" in item:
                _safe_route(item["parent_path"])
            if "label" in item:
                _safe_label(item["label"])
            if category == "locators":
                _safe_locator(item)
            if category == "forms":
                for field in item["fields"]:
                    _safe_label(field["label"])
            if category == "recovery" and item["failure"] in {"auth_expired", "access_denied", "captcha"}:
                if any(step not in {"ask_user", "stop"} for step in item["steps"]):
                    raise ValueError("Authentication, access-denied and CAPTCHA recovery must stop for the user")
    if len(_canonical(knowledge).encode("utf-8")) > MAX_BYTES // 2:
        raise ValueError("Website memory exceeds its bounded payload size")
    return deepcopy(knowledge)


def validate_knowledge(name, args, context, policy=None):
    """Side-effect-free schema/privacy/namespace preflight; grants checked at execution."""
    if name not in KNOWLEDGE_SPECS:
        raise ValueError("Unknown website knowledge tool")
    errors = validate_schema(args, KNOWLEDGE_SPECS[name][0])
    if errors:
        # Do not echo rejected customer data into errors or diagnostic logs.
        raise ValueError("Invalid website knowledge arguments; use the documented bounded schema")
    _scope(name, args, context)
    knowledge_directory(context)
    if name == "site_knowledge.save":
        _sanitize_knowledge(args)
    if name == "site_knowledge.query" and "route" in args:
        _safe_route(args["route"])


def prepare_knowledge(args, context, name=None):
    """Pure approval contract: validates/normalizes; no writes or content reads.

    Call with ``name=`` for bind/save/invalidate. Save consent is bound to the
    exact safe payload, categories, namespace, device directory and TTL.
    """
    if name is None:
        name = "site_knowledge.save" if "knowledge" in args else "site_knowledge.bind" if "tenant" in args else "site_knowledge.invalidate"
    validate_knowledge(name, args, context)
    scope = _scope(name, args, context)
    prepared = {"kind": name, "scope": scope, "namespace_id": _hash(scope),
                "storage_scope": "This Windows user on this device only; outside OneDrive and developer memory",
                "directory": str(knowledge_directory(context)), "excluded_data": list(EXCLUDED_DATA),
                "decline": "Decline this grant; the current task and ephemeral website map can continue."}
    if name == "site_knowledge.save":
        knowledge = _sanitize_knowledge(args)
        prepared.update(categories=sorted(args["categories"]), payload_sha256=_hash(knowledge),
                        item_counts={key: len(knowledge[key]) for key in sorted(knowledge)},
                        ttl_days=args.get("ttl_days", 30),
                        consent_question="Save these exact categories of sanitized website navigation knowledge locally for later sessions?",
                        expiry_rule="Expired or invalidated records are excluded from reuse; expiry does not delete the local record.")
    elif name == "site_knowledge.bind":
        prepared.update(categories=[], consent_question="Allow this exact website namespace to be accessed during this local session? No knowledge is saved by binding.")
    elif name == "site_knowledge.invalidate":
        prepared.update(categories=list(CATEGORIES), consent_question="Invalidate all reusable knowledge in this exact selected namespace?")
    return prepared


def _approval(name, args, context):
    prepared = prepare_knowledge(args, context, name=name)
    if (context.get("approved") is not True or not _digest(context.get("approval_hash"))
            or type(context.get("site_knowledge_reviewed")) is not dict
            or context["site_knowledge_reviewed"] != prepared):
        raise PolicyError("A real local user grant must match the exact displayed website knowledge scope")
    if name == "site_knowledge.save" and context.get("site_knowledge_consent") != prepared:
        raise PolicyError("Explicit local save consent is required; an LLM consent flag is never authority")
    return prepared


def _now(context):
    clock = context.get("site_knowledge_clock")
    value = clock() if callable(clock) else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Website knowledge requires a timezone-aware local timestamp")
    return value.astimezone(timezone.utc)


def _timestamp(value):
    return value.isoformat(timespec="seconds")


def _record_path(context, scope):
    directory = knowledge_directory(context)
    return PathPolicy([directory]).resolve(_hash(scope) + ".json")


def _json_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate stored knowledge key")
        value[key] = item
    return value


def _reject_json_constant(value):
    raise ValueError("Non-finite stored knowledge value")


def _digest(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _read(context, scope):
    path = _record_path(context, scope)
    if not path.exists():
        return None
    checked = PathPolicy([path.parent]).resolve(path, True)
    if not checked.is_file() or checked.stat().st_size > MAX_BYTES:
        raise PolicyError("The stored website knowledge record is not a bounded regular file")
    try:
        value = json.loads(checked.read_text(encoding="utf-8"), object_pairs_hook=_json_pairs,
                           parse_constant=_reject_json_constant)
    except (ValueError, UnicodeError) as error:
        raise PolicyError("Stored website knowledge is damaged; replace it after local review") from error
    expected = {"schema_version", "namespace_id", "scope_fingerprint", "knowledge", "consent",
                "provenance", "observed_at", "expires_at", "invalidated_at", "payload_sha256"}
    if (type(value) is not dict or set(value) != expected or value.get("schema_version") != SCHEMA_VERSION
            or value.get("namespace_id") != _hash(scope) or value.get("scope_fingerprint") != _fingerprint(scope)
            or type(value.get("consent")) is not dict or type(value.get("provenance")) is not dict):
        raise PolicyError("Stored website knowledge does not match the selected namespace and schema")
    consent = value["consent"]
    if (set(consent) != {"categories", "timestamp", "approval_hash", "review_sha256", "ttl_days"}
            or not _digest(consent.get("approval_hash")) or not _digest(consent.get("review_sha256"))
            or type(consent.get("ttl_days")) is not int
            or not 1 <= consent["ttl_days"] <= 90):
        raise PolicyError("Stored website knowledge has no valid consent record")
    payload_args = {"origin": scope["origin"], "categories": consent["categories"], "knowledge": value["knowledge"], "ttl_days": consent["ttl_days"]}
    if validate_schema(payload_args, SAVE):
        raise PolicyError("Stored website knowledge has an invalid bounded schema")
    try:
        _sanitize_knowledge(payload_args)
        observed = datetime.fromisoformat(value["observed_at"])
        expires = datetime.fromisoformat(value["expires_at"])
        now = _now(context)
        if (observed.tzinfo is None or expires.tzinfo is None or observed > now + timedelta(seconds=30)
                or expires - observed != timedelta(days=consent["ttl_days"])
                or consent["timestamp"] != value["observed_at"]):
            raise ValueError("Invalid freshness metadata")
        if value["invalidated_at"] is not None:
            invalidated = datetime.fromisoformat(value["invalidated_at"])
            if invalidated.tzinfo is None:
                raise ValueError("Invalid invalidation timestamp")
    except (ValueError, TypeError, KeyError) as error:
        raise PolicyError("Stored website knowledge failed privacy or freshness validation") from error
    if value["payload_sha256"] != _hash(value["knowledge"]):
        raise PolicyError("Stored website knowledge payload integrity failed")
    provenance = value["provenance"]
    if (set(provenance) != {"source_urls", "session", "request", "source"}
            or provenance["source"] != "local_user_approved_navigation_templates"
            or not _digest(provenance["session"]) or not _digest(provenance["request"])
            or provenance["source_urls"] != _sources(scope, value["knowledge"])):
        raise PolicyError("Stored website knowledge provenance is invalid")
    return value


def _fingerprint(scope):
    # Namespace labels need not appear in stored documents or file names.
    return {"origin": scope["origin"], "tenant_sha256": _hash(scope["tenant"]),
            "user_scope_sha256": _hash(scope["user_scope"]),
            "environment": scope["environment"], "schema_version": SCHEMA_VERSION}


def _sources(scope, knowledge):
    return sorted({scope["origin"] + item["path"] for items in knowledge.values() for item in items})


def _write(context, scope, value):
    path = _record_path(context, scope)
    encoded = _canonical(value) + "\n"
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Website knowledge record exceeds the storage limit")
    # This private app store intentionally has one active bounded record per
    # namespace; app document/history helpers retain user-file versions forever.
    path.parent.mkdir(parents=True, exist_ok=True)
    checked = PathPolicy([path.parent]).resolve(path)
    temporary = checked.with_name(checked.name + "." + uuid.uuid4().hex + ".pending")
    temporary = PathPolicy([checked.parent]).resolve(temporary)
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        PathPolicy([checked.parent]).resolve(checked)
        os.replace(temporary, checked)
    finally:
        if temporary.exists():
            PathPolicy([checked.parent]).resolve(temporary, True).unlink()


def _retrieve(context, scope):
    value = _read(context, scope)
    base = {"namespace_id": _hash(scope), "schema_version": SCHEMA_VERSION}
    if value is None:
        return dict(base, status="missing", knowledge={})
    if value["invalidated_at"] is not None:
        return dict(base, status="invalidated", knowledge={}, invalidated_at=value["invalidated_at"])
    now = _now(context)
    if datetime.fromisoformat(value["expires_at"]) <= now:
        return dict(base, status="expired", knowledge={}, expires_at=value["expires_at"])
    return dict(base, status="fresh", knowledge=deepcopy(value["knowledge"]),
                observed_at=value["observed_at"], expires_at=value["expires_at"],
                confidence="locally_reviewed_templates",
                requires_current_page_verification=True,
                age_seconds=max(0, int((now - datetime.fromisoformat(value["observed_at"])).total_seconds())),
                provenance=deepcopy(value["provenance"]))


def execute_knowledge(name, args, context, policy=None):
    """Execute synchronously; return the raw result for ToolRegistry's envelope."""
    validate_knowledge(name, args, context, policy)
    scope = _scope(name, args, context)
    if name == "site_knowledge.bind":
        prepared = _approval(name, args, context)
        bindings = context.get("site_knowledge_bindings")
        if type(bindings) is not dict:
            raise PolicyError("The orchestrator must initialize a shared session namespace binding store")
        # One origin has exactly one active scope. Switching scope cannot make
        # the earlier customer's/user's namespace silently available.
        bindings.clear()
        bindings[scope["origin"]] = {"scope": deepcopy(scope), "session": _session(context),
                                      "approval_hash": context["approval_hash"],
                                      "review_sha256": _hash(prepared)}
        return {"status": "bound", "namespace_id": _hash(scope), "scope": scope,
                "knowledge_saved": False, "binding_lifetime": "current local session only"}
    if name == "site_knowledge.save":
        prepared = _approval(name, args, context)
        knowledge = _sanitize_knowledge(args)
        now = _now(context)
        value = {"schema_version": SCHEMA_VERSION, "namespace_id": _hash(scope),
                 "scope_fingerprint": _fingerprint(scope), "knowledge": knowledge,
                 "observed_at": _timestamp(now), "expires_at": _timestamp(now + timedelta(days=prepared["ttl_days"])),
                 "invalidated_at": None, "payload_sha256": _hash(knowledge),
                 "consent": {"categories": prepared["categories"], "timestamp": _timestamp(now),
                             "approval_hash": context["approval_hash"], "review_sha256": _hash(prepared),
                             "ttl_days": prepared["ttl_days"]},
                 "provenance": {"source_urls": _sources(scope, knowledge), "session": _session(context),
                                "request": _hash(context.get("source_request_id", "local")),
                                "source": "local_user_approved_navigation_templates"}}
        _write(context, scope, value)
        verified = _read(context, scope)
        if verified != value:
            raise PolicyError("Website knowledge save did not verify against the approved payload")
        return {"status": "saved", "namespace_id": _hash(scope), "categories": prepared["categories"],
                "item_counts": prepared["item_counts"], "expires_at": value["expires_at"],
                "payload_sha256": value["payload_sha256"], "locally_verified": True}
    if name == "site_knowledge.invalidate":
        _approval(name, args, context)
        value = _read(context, scope)
        if value is None:
            return {"status": "missing", "namespace_id": _hash(scope)}
        value["invalidated_at"] = _timestamp(_now(context))
        _write(context, scope, value)
        if _read(context, scope) != value:
            raise PolicyError("Website knowledge invalidation did not verify")
        return {"status": "invalidated", "namespace_id": _hash(scope),
                "invalidated_at": value["invalidated_at"], "retained_locally": True}
    result = _retrieve(context, scope)
    if result["status"] != "fresh":
        return result
    if name == "site_knowledge.query":
        category = args.get("category")
        route = args.get("route")
        result["knowledge"] = {key: [item for item in items if route is None or item["path"] == route]
                               for key, items in result["knowledge"].items() if category is None or key == category}
    elif name == "site_knowledge.export":
        knowledge = result.pop("knowledge")
        result["summary"] = {"item_counts": {key: len(items) for key, items in knowledge.items()},
                             "route_templates": sorted({item["path"] for items in knowledge.values() for item in items}),
                             "categories": sorted(knowledge)}
    return result
