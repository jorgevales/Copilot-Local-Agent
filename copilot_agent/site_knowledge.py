"""Session-authorized navigation memory; no credentials or customer records.

This module is synchronous. The orchestrator alone injects approval context,
``site_knowledge_reviewed`` and a session-bound knowledge grant, or an exact
per-save grant for compatibility. Tool arguments cannot supply capabilities.
Bindings live only in the current session's shared ``site_knowledge_bindings``
dictionary. A resumed/new session must obtain a fresh local namespace grant.
"""
from __future__ import annotations
import getpass

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import ntpath
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from .policy import PathPolicy, PolicyError, URLPolicy, mapped_s_drive_root, reject_path_redirection
from .protocol import validate_schema

SCHEMA_VERSION = 1
MAX_BYTES = 131072
MAX_ITEMS = 40
CATEGORIES = ("routes", "locators", "forms", "document_areas", "recovery", "navigation_methods")
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
METHOD_STEP = _object({'path': PATH, 'strategy': _enum(('navigate', 'role', 'label', 'test_id', 'css')),
                       'value': LABEL, 'role': LOCATOR['properties']['role']}, ['path', 'strategy'])
METHOD = _object({'path': PATH, 'purpose': _enum(PURPOSES), 'label': LABEL,
                  'steps': {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': METHOD_STEP},
                  'source_call_ids': {'type': 'array', 'minItems': 1, 'maxItems': 20,
                                      'uniqueItems': True, 'items': _string(200)},
                  'duration_ms': {'type': 'integer', 'minimum': 1, 'maximum': 3600000}},
                 ['path', 'purpose', 'label', 'steps', 'source_call_ids'])
CATEGORY_SCHEMAS['navigation_methods'] = METHOD
KNOWLEDGE = {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": MAX_ITEMS}}
ORIGIN = _string(280)
SCOPE_LABEL = {"type": "string", "minLength": 1, "maxLength": 64,
               "pattern": r"^[a-z][a-z0-9-]{0,63}$"}
BIND = _object({"origin": ORIGIN, "tenant": SCOPE_LABEL, "user_scope": SCOPE_LABEL,
                "environment": _enum(("production", "test", "staging", "development")),
                "application": SCOPE_LABEL}, ['origin', 'tenant', 'user_scope', 'environment'])
SAVE = _object({"origin": ORIGIN,
                "allow_partial": {"type": "boolean"},
                "categories": {"type": "array", "items": _string(100), "minItems": 1,
                               "maxItems": MAX_ITEMS, "uniqueItems": True},
                "knowledge": KNOWLEDGE,
                "ttl_days": {"type": "integer", "minimum": 1, "maximum": 90}},
               ["origin", "categories", "knowledge"])
QUERY = _object({"origin": ORIGIN, "category": _string(100), "route": PATH}, ["origin"])

KNOWLEDGE_SPECS = {
    "site_knowledge.bind": (BIND, "user_approval", "Select the current HTTPS site's exact tenant, user/sharing scope and environment through local approval. Scope labels are user-declared; never infer an authenticated identity. No website knowledge is saved."),
    "site_knowledge.retrieve": (_object({"origin": ORIGIN}), "read_only", "Retrieve unexpired approved navigation knowledge for the current locally selected site namespace; a namespace must first be bound by the user."),
    "site_knowledge.query": (QUERY, "read_only", "Filter approved fresh navigation knowledge by category and/or exact generic route template inside the selected namespace."),
    "site_knowledge.save": (SAVE, "user_approval", "Merge concise sanitized navigation knowledge under the session knowledge grant without another save prompt. Skip duplicates; source_call_ids for navigation_methods must reference completed successful local browser evidence. Ledger retains revisions and centralized per-site readable views."),
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

# These words help distinguish navigation labels from possible personal names.
# Route segments are validated by shape and context rather than this vocabulary.
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
    staging development test inicio clinical forms appointments calendar patients menus
    formularios clinicos consultas agendadas agendar consulta pacientes calendario
    ajustes avisos reportes porciones menu personalizado
    account-search customer-search client-search search-customer search-client
""".split())
SAFE_SEGMENTS = SAFE_WORDS | frozenset({"inicio", "customer-search", "client-search", "account-search",
                                      "document-search", "sign-in", "sign-out", "help-center",
                                      "customer-service", "case-management", "formularios-clinicos",
                                      "consultas", "agendar-consulta"})
SAFE_WORDS = SAFE_WORDS | frozenset('interested party parties literature advanced submitted completed corporate actions work progress investment investments filter output balance holdings business box'.split())
SAFE_SEGMENTS = SAFE_SEGMENTS | SAFE_WORDS
PLACEHOLDERS = frozenset({"{customer}", "{account}", "{case}", "{document}", "{item}"})
ENTITY_SEGMENTS = frozenset("customer customers client clients investor investors user users member members account accounts profile profiles case cases transaction transactions policy policies contact contacts person people employee employees document documents file files record records".split())
STATIC_CHILDREN = frozenset("search lookup find list overview details summary status documents files history activity transactions accounts cases settings new create edit download downloads reports statements products contacts profile profiles landing index".split())


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


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
    owned_context = getattr(browser, "tool_context", None)
    if (owned_context is None or getattr(page, "context", None) is not owned_context
            or page not in getattr(browser, "_tool_pages", [page])
            or page is getattr(browser, "page", None) or page is getattr(browser, "chat_page", None)):
        raise PolicyError("Website memory requires an owned website tab")
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


def knowledge_session_grant(context):
    """Bind a locally issued in-memory grant to this session and approval hash."""
    if not _digest(context.get('approval_hash')):
        raise PolicyError('A local session approval hash is required')
    return {'session': _session(context), 'approval_hash': context['approval_hash']}


def session_knowledge_authorized(context):
    from .policy import config_value
    if (context.get('knowledge_session_authorized') is not True
            or config_value(context.get('config', {}), '_knowledge_session_confirmed', False) is not True):
        return False
    try:
        return context.get('knowledge_session_grant') == knowledge_session_grant(context)
    except PolicyError:
        return False


def knowledge_directory(context):
    """Resolve the single durable knowledge root beside the S: project."""
    # This private context hook exists only for isolated unit fixtures. It is
    # never populated from model arguments or normal runtime configuration.
    selected = context.get("knowledge_directory")
    if selected is None:
        configured = context.get('config')
        if getattr(configured, '_local_knowledge_test_mode', False):
            selected = getattr(configured, 'knowledge_directory', None)
            storage_root = Path(getattr(configured, 'storage_dir', '')).resolve()
            if (selected is None or Path(selected).resolve().parent != storage_root
                    or Path(selected).drive.upper() != 'C:'):
                raise PolicyError('The explicit local knowledge test directory is outside its approved C: test store')
            raw = Path(selected).expanduser().absolute()
            reject_path_redirection(raw)
            return raw
        project = configured.get('root') if isinstance(configured, dict) else getattr(configured, 'root', None)
        project_root = Path(project or Path(__file__).resolve().parents[1]).expanduser()
        try:
            share = mapped_s_drive_root().resolve()
        except (PolicyError, OSError) as error:
            raise PolicyError("The mapped S: share is unavailable; durable knowledge remains in session evidence") from error
        from .policy import is_s_drive_path
        if is_s_drive_path(project_root):
            project_root = share / Path(ntpath.relpath(str(project_root), 'S:\\'))
        reject_path_redirection(project_root)
        project_root = project_root.resolve()
        if project_root != share and share not in project_root.parents:
            raise PolicyError("The project is not located on the mapped S: share; durable knowledge remains in session evidence")
        selected = project_root.parent / "Discoveries knowledge"
        configured_directory = (configured.get('knowledge_directory') if isinstance(configured, dict)
                                else getattr(configured, 'knowledge_directory', None))
        if configured_directory is not None:
            configured_path = Path(configured_directory).expanduser()
            if is_s_drive_path(configured_path):
                configured_path = share / Path(ntpath.relpath(str(configured_path), 'S:\\'))
            reject_path_redirection(configured_path)
            if configured_path.resolve() != selected.resolve():
                raise PolicyError("Persistent knowledge must use the S: project sibling Discoveries knowledge folder")
    raw = Path(selected).expanduser().absolute()
    reject_path_redirection(raw)
    return raw


def _scope(name, args, context):
    origin = _origin(args["origin"])
    if origin != _current_origin(context):
        raise PolicyError("Website memory origin differs from the current owned tab")
    if name == "site_knowledge.bind":
        selected = {"origin": origin, "tenant": args["tenant"], "user_scope": args["user_scope"],
                    "environment": args["environment"], "schema_version": SCHEMA_VERSION}
        if 'application' in args:
            selected['application'] = args['application']
        return selected
    from .session_mode import fast_mode
    bindings = context.get("site_knowledge_bindings")
    binding = bindings.get(origin) if type(bindings) is dict else None
    if binding is None and (fast_mode(context.get('config', {})) or session_knowledge_authorized(context)):
        # Namespace organization is automatic, not a separate access grant.
        scope = {'origin': origin, 'tenant': 'signed-in-account',
                 'user_scope': 'local-' + _hash(getpass.getuser())[:24],
                 'environment': 'session', 'schema_version': SCHEMA_VERSION}
        return scope
    if (type(binding) is not dict or binding.get("session") != _session(context)
            or not _digest(binding.get("approval_hash")) or not _digest(binding.get("review_sha256"))
            or type(binding.get("scope")) is not dict):
        raise PolicyError("The local user must bind this site's tenant, user scope and environment first")
    scope = binding["scope"]
    expected = {"origin", "tenant", "user_scope", "environment", "schema_version"}
    if (not expected <= set(scope) <= expected | {'application'}
            or scope.get("origin") != origin or scope.get("schema_version") != SCHEMA_VERSION):
        raise PolicyError("The website namespace binding is invalid; obtain a fresh local grant")
    if validate_schema({key: scope[key] for key in BIND["properties"] if key in scope}, BIND):
        raise PolicyError("The website namespace binding is invalid; obtain a fresh local grant")
    return deepcopy(scope)


def _safe_route(value):
    original=value
    value=re.sub(r'\.(?:aspx|html?|jsp)$','',value,flags=re.I)
    if (not value.startswith("/") or "//" in value or value != value.strip()
            or any(char in value for char in "?&=#%@.:;\\") or len(value) > 320):
        raise ValueError("Persist only generic route templates without URL parameters or concrete identifiers")
    parts = [part for part in value.split("/") if part]
    def generic(part):
        # Application route names are open vocabulary. A fixed English word
        # list rejected real FNZ pages and pages in other languages.
        return (part in PLACEHOLDERS or
                bool(re.fullmatch(r'[A-Za-z][A-Za-z_-]{0,63}', part)) or
                bool(re.fullmatch(r'v[0-9]{1,2}', part, re.I)))
    if len(parts) > 16 or any(part in {'.', '..'} or not generic(part) for part in parts):
        raise ValueError("Route contains concrete identifiers or unsupported segments; use parameter placeholders")
    for parent, child in zip(parts, parts[1:]):
        if parent.lower() in ENTITY_SEGMENTS and child.lower() not in STATIC_CHILDREN and child not in PLACEHOLDERS:
            raise ValueError("Concrete entity route parameters are excluded; use a generic parameter placeholder")
    return original


def _template_route(value, origin):
    """Turn an observed same-origin URL into a reusable path before review."""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != 'https' or parsed.netloc.lower() != urlsplit(origin).netloc:
            raise ValueError('Only routes on the approved website can be saved')
        path = parsed.path or '/'
    else:
        path = parsed.path
    if not path.startswith('/') or '%' in path or '\\' in path:
        raise ValueError('A plain same-origin route path is required')
    parts = path.split('/')
    for index in range(1, len(parts)):
        part = parts[index]
        parent = parts[index - 1].lower()
        if not part or part in PLACEHOLDERS:
            continue
        if parent in ENTITY_SEGMENTS and part.lower() not in STATIC_CHILDREN | SAFE_SEGMENTS:
            entity = parent.rstrip('s')
            parts[index] = '{' + (entity if '{' + entity + '}' in PLACEHOLDERS else 'item') + '}'
        elif re.search(r'[0-9]', part) and not re.fullmatch(r'v[0-9]{1,2}', part, re.I):
            parts[index] = '{item}'
    templated = '/'.join(parts)
    _safe_route(templated)
    return templated


def _safe_label(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z /()_-]{0,99}", value):
        raise ValueError("Navigation labels must exclude identifiers, contact details and secrets")
    words = re.findall(r"[a-z]+", value.lower())
    if (not words or re.search(r'\b(?:token|bearer|password|secret|cookie|api.?key)\b', value, re.I)
            or (not any(word in SAFE_WORDS for word in words)
                and not re.search(r'\b[A-Z]{2,}\b', value))):
        raise ValueError("Navigation labels must contain a generic navigation term or application acronym")


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


class KnowledgeValidationError(ValueError):
    def __init__(self,path,value,reason):
        value = value if path.endswith(('.purpose','.strategy','.role')) else '[excluded sha256='+_hash(value)+']'
        self.detail={'path':path,'value':value,'reason':reason}
        super().__init__(path+' rejected '+repr(value)+': '+reason)


class KnowledgeWriteError(RuntimeError):
    def __init__(self, uncertain: bool, stage: str = "verification", cause: Exception | None = None):
        self.side_effects_uncertain = uncertain
        self.stage = stage
        # Exception class is useful for local diagnosis and contains no path,
        # payload, or site data. Never include the raw exception message.
        self.cause_type = (getattr(cause, "cause_type", None) or
                           (type(cause).__name__ if cause is not None else None))
        state = ('active record may have changed' if uncertain
                 else 'active record was unchanged')
        super().__init__(f'Website knowledge write failed at {stage}; {state}' +
                         (f' ({self.cause_type})' if self.cause_type else ''))


def _sanitize_knowledge(args):
    """Validate bounded JSON structure; content approval belongs to the safety layer."""
    knowledge = args["knowledge"]
    from .knowledge_views import reusable_value
    if reusable_value(knowledge) != knowledge:
        raise ValueError('Knowledge must use normalized sanitized URLs and nonempty content')
    categories = args["categories"]
    if type(knowledge) is not dict or set(categories) != set(knowledge):
        raise ValueError("Knowledge categories must match the approved payload")
    count = 0
    for category, items in knowledge.items():
        if type(category) is not str or not category.strip() or len(category) > 100:
            raise ValueError("Knowledge category must be a bounded nonempty string")
        if type(items) is not list or not items or any(type(item) is not dict for item in items):
            raise ValueError("Knowledge categories must contain nonempty arrays of objects")
        count += len(items)
        # Executable website hints retain their established privacy and
        # authentication boundaries. Ordinary custom categories and standalone
        # Discoveries notes do not depend on this navigation vocabulary.
        if category in CATEGORY_SCHEMAS:
            for item in items:
                errors = validate_schema(item, CATEGORY_SCHEMAS[category])
                if errors:
                    raise ValueError('Invalid bounded website hint structure')
                _safe_route(item['path'])
                if 'parent_path' in item:
                    _safe_route(item['parent_path'])
                if 'label' in item:
                    _safe_label(item['label'])
                if category == 'locators':
                    _safe_locator(item)
                if category == 'forms':
                    for field in item['fields']:
                        _safe_label(field['label'])
                if category == 'recovery' and item['failure'] in {'auth_expired', 'access_denied', 'captcha'}:
                    if any(step not in {'ask_user', 'stop'} for step in item['steps']):
                        raise ValueError('Authentication and access recovery require user intervention')
                if category == 'navigation_methods':
                    for step in item['steps']:
                        _safe_route(step['path'])
                        if step['strategy'] != 'navigate':
                            if 'value' not in step:
                                raise ValueError('Locator method steps require a sanitized locator value')
                            _safe_locator(step)
    try:
        encoded = _canonical(knowledge).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("Knowledge serialization failed: finite JSON is required") from error
    if count > MAX_ITEMS or len(encoded) > MAX_BYTES // 2:
        raise ValueError("Knowledge exceeds the bounded payload limit")
    return deepcopy(knowledge)


def safe_proposal(args):
    errors = validate_schema(args, SAVE)
    if errors:
        raise KnowledgeValidationError("knowledge", None, "Invalid bounded knowledge structure")
    if set(args['categories']) != set(args['knowledge']):
        raise ValueError('Consent categories must match submitted knowledge categories')
    cleaned, safe, rejected = deepcopy(args), {}, []
    for category, items in args['knowledge'].items():
        for index, item in enumerate(items):
            try:
                from .knowledge_views import reusable_value
                candidate = reusable_value(deepcopy(item))
                if category in CATEGORY_SCHEMAS:
                    for key in ('path', 'parent_path'):
                        if isinstance(candidate.get(key), str):
                            candidate[key] = _template_route(candidate[key], args['origin'])
                    if category == 'navigation_methods':
                        for step in candidate.get('steps', []):
                            if isinstance(step.get('path'), str):
                                step['path'] = _template_route(step['path'], args['origin'])
                _sanitize_knowledge({'categories': [category], 'knowledge': {category: [candidate]}})
                safe.setdefault(category, []).append(candidate)
            except ValueError as error:
                detail = {'path': 'knowledge.item[' + str(index) + ']',
                          'value': '[excluded sha256=' + _hash(item) + ']',
                          'reason': 'Website hint failed structural or privacy validation; use an ordinary sanitized discovery note.'}
                if args.get('allow_partial', True) is False:
                    raise ValueError(detail['reason']) from error
                rejected.append(detail)
    if not safe:
        raise ValueError('No valid items remain; save ordinary sanitized discoveries with knowledge.note')
    cleaned['knowledge'], cleaned['categories'] = safe, list(safe)
    _sanitize_knowledge(cleaned)
    return cleaned, rejected


def validate_knowledge(name, args, context, policy=None):
    """Side-effect-free schema/privacy/namespace preflight; grants checked at execution."""
    if name not in KNOWLEDGE_SPECS:
        raise ValueError("Unknown website knowledge tool")
    if name=='site_knowledge.save': args,_=safe_proposal(args)
    errors = validate_schema(args, KNOWLEDGE_SPECS[name][0])
    if errors:
        # Do not echo rejected customer data into errors or diagnostic logs.
        raise ValueError('Invalid website knowledge arguments: '+'; '.join(errors[:5]))
    _scope(name, args, context)
    knowledge_directory(context)
    if name == "site_knowledge.save":
        _sanitize_knowledge(args)


def _verified_methods(incoming, context, scope):
    """Bind method claims to successful local navigation and final URL evidence."""
    methods = incoming.get('navigation_methods', [])
    if not methods:
        return incoming
    state = context.get('session_state')
    calls = getattr(state, 'data', {}).get('calls', {})
    for method in methods:
        observations = []
        elapsed = 0
        for identifier in method['source_call_ids']:
            call = calls.get(identifier)
            if (type(call) is not dict or call.get('status') != 'completed'
                    or call.get('result', {}).get('ok') is not True
                    or call.get('request', {}).get('name') not in {
                        'browser.open', 'browser.plan', 'browser.click',
                        'browser.tabs.open', 'browser.tabs'}):
                raise ValueError('Verified methods require completed successful local navigation call IDs')
            name = call['request']['name']
            output = call['result'].get('result', {})
            if (output.get('side_effects_uncertain') or output.get('error')
                    or name == 'browser.plan' and output.get('status') != 'verified'
                    or name == 'browser.tabs' and call['request'].get('arguments', {}).get('operation') != 'open'):
                raise ValueError('A partial, failed or observation-only result cannot verify a navigation method')
            observations.append(call)
            try:
                start = datetime.fromisoformat(call['started_at'].replace('Z', '+00:00'))
                finish = datetime.fromisoformat(call['finished_at'].replace('Z', '+00:00'))
                elapsed += max(0, int((finish - start).total_seconds() * 1000))
            except (KeyError, TypeError, ValueError):
                pass
        def urls(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {'url', 'final_url', 'target_url', 'current_url'} and isinstance(item, str):
                        yield item
                    elif isinstance(item, (list, dict)):
                        yield from urls(item)
            elif isinstance(value, list):
                for item in value:
                    yield from urls(item)
        observed = set()
        for call in observations:
            output = call.get('result', {}).get('result', {})
            destination = output.get('last_verified_state', {}) if call['request']['name'] == 'browser.plan' else output
            for url in urls(destination):
                try:
                    observed.add(_template_route(url, scope['origin']))
                except ValueError:
                    pass
        if method['path'] not in observed:
            raise ValueError('Method destination must be confirmed by successful local navigation output')
        requests = []
        for call in observations:
            args = call['request'].get('arguments', {})
            if call['request']['name'] != 'browser.plan':
                requests.append(args)
                continue
            results = call['result']['result'].get('results', [])
            def executed_steps(items, prefix=''):
                for item in items:
                    path = prefix + item.get('id', '')
                    if any(result.get('step_id') == path and result.get('verification') == 'passed'
                           for result in results):
                        # Branch/loop containers contain unexecuted alternatives;
                        # only their individually verified child steps count.
                        if item.get('op') not in {'branch', 'loop'}:
                            yield item
                    if item.get('op') == 'branch':
                        for branch in ('then', 'else'):
                            yield from executed_steps(item.get(branch, []), path + '/' + branch + '/')
                    elif item.get('op') == 'loop':
                        for index in range(min(100, item.get('max_iterations', 0))):
                            yield from executed_steps(item.get('steps', []), path + '/' + str(index) + '/')
            requests.extend(executed_steps(args.get('steps', [])))
        encoded_requests = _canonical(requests)
        # Intermediate plan destinations count for the steps, while only its
        # final verified state can establish the method's stated destination.
        steps_observed = set(observed)
        for call in observations:
            for url in urls(call['result'].get('result', {}).get('results', [])):
                try:
                    steps_observed.add(_template_route(url, scope['origin']))
                except ValueError:
                    pass
        for step in method['steps']:
            if step['strategy'] == 'navigate':
                if step['path'] not in encoded_requests and step['path'] not in steps_observed:
                    raise ValueError('Every navigation method step requires observed local evidence')
            else:
                def matches(request):
                    locator = request.get('locator', {})
                    if step['strategy'] == 'role':
                        return locator.get('role') == step.get('role') and locator.get('name') == step['value']
                    key = {'test_id': 'testid', 'label': 'label', 'css': 'css'}[step['strategy']]
                    return locator.get(key) == step['value'] or key == 'css' and request.get('selector') == step['value']
                if not any(matches(request) for request in requests):
                    raise ValueError('Every method locator must match an executed successful local navigation step')
        # Measured elapsed time comes from the local ledger, never a claimed
        # model speedup. Hash untrusted call labels before durable persistence.
        method.pop('duration_ms', None)
        if elapsed:
            method['duration_ms'] = min(elapsed, 3600000)
        method['source_call_ids'] = [_hash(identifier) for identifier in method['source_call_ids']]
    return incoming


def _item_identity(category, item):
    if category == 'navigation_methods':
        from .knowledge_views import method_identity
        return method_identity(item)
    if category == 'recovery':
        return item.get('path'), item.get('failure')
    if category == 'locators':
        return item.get('path'), item.get('strategy'), item.get('role'), item.get('value')
    if category == 'forms':
        return item.get('path'), item.get('purpose')
    return (item.get('path'),) if item.get('path') is not None else (_hash(item),)


def _semantic_knowledge(knowledge):
    """Ignore method proof labels/timing when deciding whether intake changed."""
    result = deepcopy(knowledge)
    for method in result.get('navigation_methods', []):
        method.pop('source_call_ids', None)
        # A newly measured faster method is meaningful; ordinary repeated
        # timings for an otherwise identical method are not new knowledge.
        method.pop('duration_ms', None)
    return {key: sorted(items, key=_canonical) for key, items in result.items()}



def prepare_knowledge(args, context, name=None):
    """Approval contract: validate and merge the current namespace without writes.

    Call with ``name=`` for bind/save/invalidate. Save consent is bound to the
    exact safe payload, categories, namespace, device directory and TTL.
    """
    if name is None:
        name = "site_knowledge.save" if "knowledge" in args else "site_knowledge.bind" if "tenant" in args else "site_knowledge.invalidate"
    rejected=[]
    if name=='site_knowledge.save': args,rejected=safe_proposal(args)
    validate_knowledge(name, args, context)
    scope = _scope(name, args, context)
    local_test_store = getattr(context.get('config'), '_local_knowledge_test_mode', False)
    prepared = {"kind": name, "scope": scope, "namespace_id": _hash(scope),
                "storage_scope": "Explicit local C: navigation test store" if local_test_store else "Configured shared Discoveries knowledge store",
                "storage_mode": "local_c_test" if local_test_store else "shared_s",
                "directory": str(knowledge_directory(context)), "excluded_data": list(EXCLUDED_DATA),
                "decline": "Decline this grant; the current task and ephemeral website map can continue."}
    from .storage import discoveries_storage_paths
    if local_test_store or context.get('knowledge_directory') is not None:
        # Explicit C: test mode must preview the actual target even on machines
        # where the production S: mapping is available.
        fixture_path = str(knowledge_directory(context))
        paths = {'s_path': fixture_path, 'unc_path': fixture_path}
    else:
        try:
            paths = discoveries_storage_paths(getattr(context.get('config'), 'root', Path(__file__).resolve().parents[1]))
        except (OSError, ValueError):
            # A caller may have supplied a test mapping resolver while
            # storage.py still has the platform resolver. Reconstruct the
            # mapped-drive alias from the already validated canonical path.
            if context.get('knowledge_directory') is not None:
                fixture_path = str(knowledge_directory(context))
                paths = {'s_path': fixture_path, 'unc_path': fixture_path}
            elif getattr(context.get('config'), '_local_knowledge_test_mode', False):
                fixture_path = str(knowledge_directory(context))
                paths = {'s_path': fixture_path, 'unc_path': fixture_path}
            else:
                directory = knowledge_directory(context).resolve()
                share = mapped_s_drive_root().resolve()
                relative = ntpath.relpath(str(directory), str(share))
                if relative == '..' or relative.startswith('..\\'):
                    raise PolicyError('The Discoveries knowledge folder resolved outside the live S: share')
                paths = {'s_path': str(Path('S:/') / Path(relative)), 'unc_path': str(directory)}
    prepared.update(storage_path_s=paths['s_path'], storage_path_unc=paths['unc_path'])
    if name == "site_knowledge.save":
        incoming = _verified_methods(_sanitize_knowledge(args), context, scope)
        existing = _retrieve(context, scope)
        prior = existing['knowledge'] if existing['status'] == 'fresh' else {}
        knowledge = {key: deepcopy(items) for key, items in prior.items()}
        for category, items in incoming.items():
            current = knowledge.setdefault(category, [])
            for item in items:
                identity = _item_identity(category, item)
                current[:] = [old for old in current if _item_identity(category, old) != identity]
                current.append(deepcopy(item))
        _sanitize_knowledge({'categories': list(knowledge), 'knowledge': knowledge})
        unchanged = bool(prior) and _semantic_knowledge(prior) == _semantic_knowledge(knowledge)
        prepared.update(categories=sorted(knowledge), knowledge=knowledge, rejected_items=rejected,
                        revision=existing.get('revision',0) + (0 if unchanged else 1),
                        unchanged=unchanged,
                        prior_payload_sha256=_hash(prior) if prior else None,
                        payload_sha256=_hash(knowledge),
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
    if (name == "site_knowledge.save" and context.get("site_knowledge_consent") != prepared
            and not session_knowledge_authorized(context)):
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


class KnowledgeStorageError(PolicyError):
    """Sanitized technical storage failure; never include paths or payloads."""
    def __init__(self, code):
        self.code = code
        super().__init__("Knowledge storage: " + code)


def storage_error_code(error):
    import sqlite3
    code = getattr(error, "code", None)
    if code in {"knowledge_integrity", "evidence_integrity"}:
        return "integrity_failure"
    if code == "store_version":
        return "incompatible_store_version"
    if code:
        return code
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, FileNotFoundError):
        return "missing_root"
    if isinstance(error, sqlite3.OperationalError):
        text = str(error).lower()
        return "storage_locked" if "locked" in text else "read_only" if "readonly" in text else "storage_unavailable"
    if isinstance(error, sqlite3.DatabaseError):
        return "integrity_failure"
    if isinstance(error, (ValueError, TypeError, UnicodeError)):
        return "serialization_error"
    return "filesystem_unavailable"


def _read(context, scope):
    # Both discovery knowledge generations share the selected Discoveries root.
    # Never search an old user storage root: migration must be explicitly reviewed.
    from .discovery_store import Store
    store = None
    try:
        store = Store(context, persistent=True, readonly=True, allow_missing=True)
        value = store.site_knowledge(_hash(scope))
    except Exception as error:
        raise KnowledgeStorageError(storage_error_code(error)) from error
    finally:
        if store is not None:
            store.close()
    if value is None:
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
    if (type(value) is not dict or not expected.issubset(value) or type(value.get("schema_version")) is not int or value.get("schema_version") < 1
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
        raise KnowledgeStorageError("integrity_failure")
    provenance = value["provenance"]
    if (set(provenance) != {"source_urls", "session", "request", "source"}
            or provenance["source"] != "local_user_approved_navigation_templates"
            or not _digest(provenance["session"]) or not _digest(provenance["request"])
            or provenance["source_urls"] != _sources(scope, value["knowledge"])):
        raise PolicyError("Stored website knowledge provenance is invalid")
    return value


def _fingerprint(scope):
    # Namespace labels need not appear in stored documents or file names.
    value = {"origin": scope["origin"], "tenant_sha256": _hash(scope["tenant"]),
             "user_scope_sha256": _hash(scope["user_scope"]),
             "environment": scope["environment"], "schema_version": SCHEMA_VERSION}
    if 'application' in scope:
        value['application_sha256'] = _hash(scope['application'])
    return value


def _sources(scope, knowledge):
    return sorted({scope["origin"] + item["path"] for items in knowledge.values() for item in items if isinstance(item.get("path"), str) and item["path"].startswith("/")})


def _write(context, scope, value):
    # The SQLite transaction is the atomic promotion point shared with the
    # newer discovery knowledge index. The old namespace JSON is read-only
    # migration input and is never overwritten or deleted.
    from .discovery_store import Store
    stage = "central_store_open"
    store = None
    try:
        store = Store(context, persistent=True)
        stage = "atomic_database_transaction"
        revision = value.get("revision", 1)
        invalidation = value.get("invalidated_at") is not None
        current = store.site_knowledge(_hash(scope))
        expected = revision if invalidation and current is not None else revision - 1
        store.save_site_knowledge(_hash(scope), expected, value,
                                  allow_invalidate=invalidation)
    except Exception as error:
        raise _KnowledgeStageError(stage, error) from error
    finally:
        if store is not None:
            store.close()


class _KnowledgeStageError(OSError):
    def __init__(self, stage, cause):
        self.stage = stage
        self.cause_type = type(cause).__name__
        super().__init__(stage)


def _verified_write(context, scope, value):
    """Classify failures from an authoritative readback of the active record."""
    before = _read(context, scope)
    last_error = None
    for attempt in range(1, 4):
        callback = context.get('storage_attempt_notice')
        if callable(callback):
            callback(attempt, 3, knowledge_directory(context))
        try:
            _write(context, scope, value)
        except Exception as error:
            last_error = error
            stage = getattr(error, "stage", "storage_access")
            try:
                after = _read(context, scope)
            except Exception as read_error:
                raise KnowledgeWriteError(True, "readback_after_failure", read_error) from error
            if after == value:
                return
            if after != before:
                raise KnowledgeWriteError(True, stage, error) from error
            if attempt < 3:
                continue
            raise KnowledgeWriteError(False, stage, error) from error
        try:
            if _read(context, scope) == value:
                return
            raise KnowledgeWriteError(True, "readback_mismatch")
        except KnowledgeWriteError:
            raise
        except Exception as error:
            raise KnowledgeWriteError(True, "readback", error) from error
    if last_error is not None:
        raise KnowledgeWriteError(False, "storage_access", last_error) from last_error


def reconciliation_baseline(args, context, prepared):
    """Retain only hashes needed to resolve a later uncertain approved save."""
    scope = _scope('site_knowledge.save', args, context)
    before = _read(context, scope)
    return {'kind': 'knowledge_save', 'namespace_id': _hash(scope),
            'before_sha256': _hash(before) if before is not None else None,
            'payload_sha256': prepared['payload_sha256'], 'revision': prepared['revision'],
            'approval_sha256': context['approval_hash'], 'review_sha256': _hash(prepared),
            'request_sha256': _hash(context.get('source_request_id', 'local'))}


def reconcile_knowledge_call(state, context, call_id):
    """Use the active namespace record, never a model-provided outcome."""
    call = state.data['calls'].get(call_id)
    if call is None:
        from .web_privacy import private_id
        call_id = private_id(call_id)
        call = state.data['calls'].get(call_id)
    if call is None or call.get('status') != 'uncertain':
        raise ValueError('Choose one uncertain knowledge save')
    baseline = call.get('reconciliation_baseline') or {}
    if baseline.get('kind') != 'knowledge_save':
        raise ValueError('This operation has no recorded knowledge readback baseline')
    from .discovery_store import Store
    store = Store(context, persistent=True, readonly=True, allow_missing=True)
    try:
        current = store.site_knowledge(baseline['namespace_id'])
    finally:
        store.close()
    if current is not None and (current.get('namespace_id') != baseline['namespace_id']
            or current.get('payload_sha256') != _hash(current.get('knowledge'))):
        raise KnowledgeStorageError('integrity_failure')
    current_hash = _hash(current) if current is not None else None
    if current_hash == baseline['before_sha256']:
        outcome = 'not_executed'
    elif (current is not None and current.get('revision') == baseline['revision']
          and current.get('payload_sha256') == baseline['payload_sha256']
          and current.get('consent', {}).get('approval_hash') == baseline['approval_sha256']
          and current.get('consent', {}).get('review_sha256') == baseline['review_sha256']
          and current.get('provenance', {}).get('request') == baseline['request_sha256']):
        outcome = 'completed'
    else:
        raise PolicyError('Fresh knowledge readback conflicts with both recorded states')
    proof = {'kind': 'fresh_knowledge_readback', 'session_id': state.session_id,
             'call_id_sha256': hashlib.sha256(call_id.encode()).hexdigest(),
             'namespace_id': baseline['namespace_id'], 'record_sha256': current_hash,
             'payload_sha256': current.get('payload_sha256') if current else None,
             'revision': current.get('revision') if current else None,
             'approval_sha256': current.get('consent', {}).get('approval_hash') if current else None,
             'review_sha256': current.get('consent', {}).get('review_sha256') if current else None,
             'request_sha256': current.get('provenance', {}).get('request') if current else None,
             'outcome': outcome, 'observed_at': _timestamp(_now(context))}
    state.reconcile_call(call_id, outcome, proof=proof)
    return {'status': outcome, 'call_id': call_id, 'record_sha256': current_hash,
            'completion_credited': outcome == 'completed'}


def _retrieve(context, scope):
    value = _read(context, scope)
    base = {"namespace_id": _hash(scope), "schema_version": SCHEMA_VERSION}
    if value is not None: base['revision']=value.get('revision',0)
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


def _publish_view(context, scope, record):
    """Report a failed derived view honestly without hiding a committed ledger."""
    from .knowledge_views import publish_site_view
    from .discovery_store import Store
    store = None
    try:
        store = Store(context, persistent=True, readonly=True)
        history = store.site_knowledge_history(_hash(scope))
        return publish_site_view(context, scope, _hash(scope), record, history)
    except Exception as error:
        return {'status': 'view_unavailable', 'diagnostic': type(error).__name__,
                'authoritative_store': 'discovery-v1/ledger.sqlite3'}
    finally:
        if store is not None:
            store.close()


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
        if prepared['unchanged']:
            previous = _read(context, scope)
            return {'status': 'unchanged', 'namespace_id': _hash(scope),
                    'revision': previous['revision'], 'payload_sha256': previous['payload_sha256'],
                    'locally_verified': True, 'item_counts': prepared['item_counts'],
                    'readable_view': _publish_view(context, scope, previous),
                    'reason': 'No new reusable knowledge; duplicate revision skipped'}
        knowledge = deepcopy(prepared['knowledge'])
        now = _now(context)
        value = {"schema_version": SCHEMA_VERSION, "namespace_id": _hash(scope), 'revision':prepared['revision'],
                 "scope_fingerprint": _fingerprint(scope), "knowledge": knowledge,
                 "observed_at": _timestamp(now), "expires_at": _timestamp(now + timedelta(days=prepared["ttl_days"])),
                 "invalidated_at": None, "payload_sha256": _hash(knowledge),
                 "consent": {"categories": prepared["categories"], "timestamp": _timestamp(now),
                             "approval_hash": context["approval_hash"], "review_sha256": _hash(prepared),
                             "ttl_days": prepared["ttl_days"]},
                 "provenance": {"source_urls": _sources(scope, knowledge), "session": _session(context),
                                "request": _hash(context.get("source_request_id", "local")),
                                "source": "local_user_approved_navigation_templates"}}
        _verified_write(context, scope, value)
        return {"status": "saved", "namespace_id": _hash(scope), "categories": prepared["categories"],
                'revision':prepared['revision'],'rejected_items':prepared['rejected_items'],
                "item_counts": prepared["item_counts"], "expires_at": value["expires_at"],
                "payload_sha256": value["payload_sha256"], "locally_verified": True,
                "readable_view": _publish_view(context, scope, value)}
    if name == "site_knowledge.invalidate":
        _approval(name, args, context)
        value = _read(context, scope)
        if value is None:
            return {"status": "missing", "namespace_id": _hash(scope)}
        value["invalidated_at"] = _timestamp(_now(context))
        _verified_write(context, scope, value)
        return {"status": "invalidated", "namespace_id": _hash(scope),
                "invalidated_at": value["invalidated_at"], "retained_locally": True,
                "readable_view": _publish_view(context, scope, value)}
    result = _retrieve(context, scope)
    if result["status"] != "fresh":
        return result
    if result['knowledge'].get('navigation_methods'):
        from .knowledge_views import recommended_methods
        methods = result['knowledge']['navigation_methods']
        preferred = recommended_methods(methods)
        result['knowledge']['navigation_methods'] = preferred
        result['previous_methods_retained'] = len(methods) - len(preferred)
    if name == "site_knowledge.query":
        category = args.get("category")
        route = args.get("route")
        result["knowledge"] = {key: [item for item in items if route is None or item.get("path") == route]
                               for key, items in result["knowledge"].items() if category is None or key == category}
    elif name == "site_knowledge.export":
        knowledge = result.pop("knowledge")
        result["summary"] = {"item_counts": {key: len(items) for key, items in knowledge.items()},
                             "route_templates": sorted({item["path"] for items in knowledge.values() for item in items if isinstance(item.get("path"), str)}),
                             "categories": sorted(knowledge)}
    return result


def quarantine_knowledge_record(context, namespace_id):
    """Preserve an unreadable active record as evidence, then release its namespace.

    Called only by local operation-ledger recovery, never a model tool argument.
    A subsequent approved save starts a new record; this does not credit the old write.
    """
    if not _digest(namespace_id):
        raise ValueError('A retained namespace identifier is required')
    from .discovery_store import Store
    store = Store(context, persistent=True)
    try:
        return store.quarantine_site_knowledge(namespace_id)
    finally:
        store.close()
