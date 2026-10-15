"""Versioned local capabilities. Browser tools use guarded owned Edge tabs."""
import asyncio
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import uuid
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .policy import PathPolicy, URLPolicy, PolicyError, config_value, is_s_drive_path, resolve_s_drive_output
from .state import browser_inventory
from .session_mode import fast_mode, website_policy
from .local_navigation import SessionFileAccessPolicy
from .local_navigation import (SessionPathPolicy, SessionPathExtensionPolicy, SessionNavigationGrant,
                               FilesystemAccessError, filesystem_diagnostic, prepare_session_path_extension)
from .code_runner import CodeRunner, REQUIRED, FIELDS
from .sync import CreatedSync
from .logging_utils import redact, now
from .archives import ArchiveService, inspect_zip, ArchiveError
from .downloads import DownloadError
from .web_navigation import (NAVIGATION_SPECS, validate_navigation, execute_navigation,
                             clear_navigation_state, get_primary_navigation_tab_id)
from .browser_inspection import INSPECTION_SPECS, execute_inspection
from .site_discovery import SPEC as SITE_DISCOVERY_SPEC, discover as discover_site
from .screenshot_evidence import CAPTURE_PROPERTIES, capture_evidence
from .web_documents import DOCUMENT_SPECS, DOCUMENT_EXAMPLES, validate_documents, execute_documents
from .site_knowledge import KNOWLEDGE_SPECS, KNOWLEDGE_EXAMPLES, validate_knowledge, execute_knowledge, safe_proposal, KnowledgeValidationError, KnowledgeWriteError, reconcile_knowledge_call
from .discovery_engine import DISCOVERY_SPECS, validate_discovery, execute_discovery
from .reconciliation import (reconcile_browser_call, abandon_uncertain_browser_call,
                             ReconciliationRequired, browser_diagnostics)
from .research_permissions import PERMISSION_SPECS, execute_permissions, guard_customer_read
from .discovery_knowledge import (KNOWLEDGE_SPECS as DISCOVERY_KNOWLEDGE_SPECS,
                                  validate_knowledge_tool, execute_knowledge_tool)
from .discovery_contracts import DiscoveryError, DISCOVERY_ERROR_CODES
from .web_operations import (OPERATION_SPECS, OPERATION_EXAMPLES,
                             validate_operation, execute_operation)


def obj(properties, required=None):
    return {"type":"object", "properties":properties, "required":list(properties if required is None else required), "additionalProperties":False}

S = {"type":"string", "maxLength":4096}
N = {"type":"integer", "minimum":0,"maximum":10000}
PATH = {"path": S}
STRUCTURE_SCRIPT = r"""() => {
  const escape = value => CSS.escape(String(value));
  const quoted = value => '"' + escape(value) + '"';
  const unique = selector => { try { return document.querySelectorAll(selector).length === 1; } catch (_) { return false; } };
  const selectorFor = element => {
    if (element.id) { const selector='#'+escape(element.id); if(unique(selector)) return selector; }
    for(const attribute of ['data-testid','data-test-id','name']) {
      const value=element.getAttribute(attribute);
      if(value) { const selector=element.tagName.toLowerCase()+'['+attribute+'='+quoted(value)+']'; if(unique(selector)) return selector; }
    }
    const parts=[];
    for(let node=element; node && node.nodeType===1; node=node.parentElement) {
      const tag=node.tagName.toLowerCase();
      const siblings=node.parentElement?[...node.parentElement.children].filter(item=>item.tagName===node.tagName):[node];
      parts.unshift(tag+':nth-of-type('+(siblings.indexOf(node)+1)+')');
    }
    return parts.join(' > ');
  };
  const textOf = element => /^(input|textarea)$/i.test(element.tagName) || element.isContentEditable ? '' : String(element.innerText||'').trim().slice(0,200);
  const inferredRole = element => {
    if(element.getAttribute('role')) return element.getAttribute('role');
    const tag=element.tagName.toLowerCase(), type=(element.getAttribute('type')||'').toLowerCase();
    if(tag==='a') return 'link'; if(tag==='button') return 'button';
    if(tag==='select') return 'combobox'; if(tag==='textarea') return 'textbox';
    if(tag==='input') return ({checkbox:'checkbox',radio:'radio',number:'spinbutton',button:'button',submit:'button',reset:'button'})[type]||'textbox';
    return null;
  };
  return [...document.querySelectorAll('a,button,input,textarea,select,[role=button],[role=link],[role=textbox],[contenteditable=true]')]
    .filter(element=>element.getClientRects().length && getComputedStyle(element).visibility!=='hidden' && getComputedStyle(element).display!=='none')
    .slice(0,100).map(element=>{
      const attributes={};
      for(const key of ['id','name','data-testid','data-test-id']) { const value=element.getAttribute(key); if(value) attributes[key]=value.slice(0,250); }
      let href=null;
      if(element.tagName.toLowerCase()==='a' && element.getAttribute('href')!==null) { try { const url=new URL(element.getAttribute('href'),document.baseURI); if(['https:','http:'].includes(url.protocol)) href=url.protocol+'//'+url.host+url.pathname; } catch (_) {} }
      const labelNodes=element.getAttribute('aria-labelledby')?.split(/\s+/).map(id=>document.getElementById(id)).filter(Boolean)||[];
      const label=element.getAttribute('aria-label') || [...(element.labels||[]),...labelNodes].map(node=>node.innerText||'').join(' ').trim() || textOf(element);
      return {tag:element.tagName.toLowerCase(),type:element.getAttribute('type'),role:inferredRole(element),label:String(label).slice(0,200),text:textOf(element),attributes,
        visible:true,enabled:!element.matches(':disabled') && element.getAttribute('aria-disabled')!=='true',selector:selectorFor(element),href};
    });
}"""
CODE_RUNNER_PROPERTIES = {
    "script": {"type":"string", "maxLength":50000},
    "purpose": {"type":"string", "maxLength":4000},
    "language": {"type":"string", "maxLength":64},
    "working_directory": S,
    "read_paths": {"type":"array", "items":S, "maxItems":100},
    "create_paths": {"type":"array", "items":S, "maxItems":100},
    "modify_paths": {"type":"array", "items":S, "maxItems":100},
    "expected_outputs": {"type":"array", "items":S, "maxItems":100},
    "commands": {"type":"array", "items":S, "maxItems":100},
    "network_destinations": {"type":"array", "items":S, "maxItems":100},
    "permissions": {"type":"array", "items":S, "maxItems":100},
    "risk_summary": {"type":"string", "maxLength":4000},
    "recovery_notes": {"type":"string", "maxLength":4000},
    "source_path": S,
    "source_sha256": {"type":"string", "maxLength":64},
    "interpreter": S,
    "arguments": {"type":"array", "items":S, "maxItems":100},
    "imports": {"type":"array", "items":S, "maxItems":100},
    "timeout_seconds": {"type":"integer", "minimum":1, "maximum":30},
    "max_output_chars": {"type":"integer", "minimum":1, "maximum":12000},
    "expected_effects": {"type":"array", "items":S, "maxItems":100},
    "subprocesses": {"type":"array", "maxItems":20, "items":obj({
        "executable":S, "arguments":{"type":"array", "items":S, "maxItems":100},
        "persistent":{"type":"boolean"}, "purpose":{"type":"string", "maxLength":1000}})},
    "viewer_windows": {"type":"array", "maxItems":12, "items":obj({
        "title":{"type":"string", "maxLength":200}, "image_path":S,
        "display_index":{"type":"integer", "minimum":1, "maximum":32}})},
}

def schema_example(schema):
    if 'const' in schema: return schema['const']
    if 'enum' in schema: return schema['enum'][0]
    kind = schema.get('type')
    if kind == 'object':
        return {key: schema_example(schema['properties'][key]) for key in schema.get('required', [])}
    if kind == 'array': return [schema_example(schema['items']) for _ in range(schema.get('minItems', 0))]
    if kind == 'integer': return schema.get('minimum', 0)
    if kind == 'boolean': return False
    if kind == 'string':
        if '64' in schema.get('pattern', ''): return '0' * 64
        return 'example.txt'
    return None
SPECS = {
    "files.list": (obj(PATH), "read_only", "List up to 200 immediate children inside allowed roots."),
    "files.exists": (obj(PATH), "read_only", "Check a path inside allowed roots."),
    "files.read": (obj({"path":S,"max_chars":N},["path"]), "read_only", "Read bounded UTF-8 text; binary or oversized reads fail."),
    "files.create": (obj({"path":S,"text":{"type":"string","maxLength":100000}}), "user_approval", "Create a new UTF-8 file exclusively. Never overwrite. An exact approved S: output can resolve to its current UNC share."),
    "files.append": (obj({"path":S,"text":{"type":"string","maxLength":100000}}), "user_approval", "Append text to an existing file after explicit approval; preserves prior content."),
    "files.replace": (obj({"path":S,"expected_sha256":{"type":"string","pattern":"^[a-f0-9]{64}$"},"text":{"type":"string","maxLength":100000}}), "user_approval", "Atomically replace one existing UTF-8 file after explicit approval and an exact current SHA-256 check. The file must be inside allowed write roots and may not be a link or hardlink."),
    "files.copy": (obj({"source":S,"destination":S}), "user_approval", "Copy one bounded file to a new exclusive destination."),
    "files.metadata": (obj(PATH), "read_only", "Read size, modification time and type."),
    "files.hash": (obj(PATH), "read_only", "Calculate SHA-256 for a file up to 20 MB."),
    "files.mkdir": (obj(PATH), "user_approval", "Create a new directory with an existing allowed parent."),
    "files.grant_path": (obj({"path":S,"scope":{"type":"string","enum":["file","directory"]},"reason":{"type":"string","minLength":1,"maxLength":2000}}), "user_approval", "After a separate local approval, extend this session's file access to exactly one reachable existing file or directory and, for a directory, its descendants. Protected paths remain denied."),
    "system.versions": (obj({}), "read_only", "Read the exact current Python executable/version, operating system version and selected package versions; no environment variables."),
    "system.disk": (obj(PATH), "read_only", "Read filesystem capacity for an allowed path."),
    "system.processes": (obj({}), "read_only", "Report this agent PID and the explicitly launched owned Edge PID when available; no wider process or command-line inventory."),
    "browser.open": (obj({"url":S,"allowed_domains":{"type":"array","items":S,"maxItems":30}},["url"]), "user_approval", "After explicit approval, open the HTTPS website in an owned tab of the same verified Edge profile, window and CDP port as Copilot. Returns its stable primary tab_id with the final URL and title for follow-up browser.tabs or browser.recon calls. Existing site sign-ins are shared. Dependency hosts require explicit approval; focus returns to Copilot after the tool."),
    "browser.back": (obj({}), "user_approval", "Navigate backward only if the target history URL passes policy."),
    "browser.forward": (obj({}), "user_approval", "Navigate forward only if the target history URL passes policy."),
    "browser.info": (obj({}), "read_only", "Read tool-tab URL and title."),
    "browser.diagnostics": (obj({}), "read_only", "Read sanitized authoritative browser registration, connection, owned-tab count and uncertain/quarantined ledger states. No URLs, titles, cookies or page content."),
    "browser.reconcile": (obj({"call_id":S,"outcome":{"type":"string","enum":["completed","not_executed"]},"observed_url":S,"observed_title":{"type":"string","maxLength":300}},["call_id","outcome","observed_url"]), "read_only", "Resolve an uncertain navigation-only browser call automatically after fresh local inspection confirms the exact observed URL and pre-action fingerprint. No click or navigation; never use for forms or writes."),
    "browser.recover_uncertain": (obj({"call_id":S,"checkpoint_url":S}), "user_approval", "Quarantine one uncertain non-navigation browser action without outcome credit and establish a fresh approved checkpoint. If the original tab is absent/closed/blank, no original website is required; live-origin restrictions follow the session mode. Validation refusals are not_started, not uncertain actions. Never replay the original action."),
    "operation.quarantine": (obj({"call_id":S}), "user_approval", "Quarantine one uncertain non-browser operation without replay or outcome credit. The identical action remains barred; inspect effects before proposing a different action."),
    "operation.reconcile": (obj({"call_id":S}), "read_only", "Resolve an uncertain site-knowledge save from a fresh readback against the recorded pre-write and approved target hashes. Other operation types require their subsystem recovery."),
    "browser.read": (obj({"frame_selector":S},[]), "read_only", "Read bounded visible body text from the managed tab or one explicit iframe."),
    "browser.structure": (obj({"frame_selector":S},[]), "read_only", "Read visible controls without input values from the managed tab or one explicit iframe."),
    "browser.click": (obj({"selector":S,"frame_selector":S},["selector"]), "user_approval", "Click one unique selector in the managed tab or explicit iframe. May change third-party state."),
    "browser.fill": (obj({"selector":S,"text":{"type":"string","maxLength":10000},"frame_selector":S},["selector","text"]), "user_approval", "Fill one unique ordinary text field; password fields are forbidden."),
    "browser.wait": (obj({"selector":S,"state":{"type":"string"},"timeout_ms":{"type":"integer","minimum":1,"maximum":15000},"frame_selector":S},["selector"]), "read_only", "Wait for a selector to be visible, attached, hidden or detached; bounded to 15 seconds."),
    "browser.select": (obj({"selector":S,"value":S,"frame_selector":S},["selector","value"]), "user_approval", "Select an option in one unique select control."),
    "browser.press": (obj({"selector":S,"key":S,"frame_selector":S},["selector","key"]), "user_approval", "Press an allowlisted key on one unique non-password control; Enter may submit and is never retried automatically."),
    "browser.frames": (obj({}), "read_only", "List iframe selectors and query-free source URLs."),
    "browser.scroll": (obj({"pixels":{"type":"integer","minimum":-10000,"maximum":10000}}), "user_approval", "Scroll the owned tool page."),
    "browser.screenshot": (obj(CAPTURE_PROPERTIES, []), "user_approval", "Capture a personalized screenshot batch in one call. All pictures become one labeled PDF automatically attached to Copilot. Default: top/middle/bottom sampling (short pages need fewer shots). Optional shots specify label, element selector, page/container scroll, viewport clip or full_page. Scroll positions restore by default."),
    "browser.errors": (obj({}), "read_only", "Report captured tool-page console errors if the browser adapter supplies them."),
    "browser.downloads": (obj({}), "read_only", "Report observed tool-page download events; absence is not delivery proof."),
    "ocr.image": (obj(PATH), "user_approval", "Check a local image; OCR requires an explicitly available integrated image capability."),
    "created.snapshot": (obj({}), "read_only", "When explicitly enabled, record a baseline of files in the user-configured Created directory. Otherwise report disabled without filesystem access."),
    "created.wait": (obj({"baseline_id":S,"pattern":S,"expected_names":{"type":"array","items":S,"maxItems":100}},[]), "read_only", "When explicitly enabled, wait for stable readable new or changed files in the configured Created directory. Report disabled without filesystem access otherwise."),
    "copilot.download": (obj({"expected_name":S,"link_text":S,"expected_sha256":S},["expected_name","link_text"]), "user_approval", "Download one real clickable artifact link in this exact Copilot response. Set link_text to its exact visible label and expected_name to a plain basename. Set expected_sha256 only when independently known. Inspect Edge settings without changing them; use the approved staging path or verified browser download event. Plaintext and sandbox links are not delivery."),
    "archives.inspect": (obj(PATH), "read_only", "Inspect a bounded ZIP manifest, archive SHA-256 and native Office container type without extracting."),
    "archives.extract": (obj({"path":S,"destination":S,"expected_files":{"type":"array","items":S,"maxItems":1000},"expected_sha256":S},["path","destination","expected_sha256"]), "user_approval", "Extract a reviewed SHA-256-bound ZIP exclusively inside allowed roots; preflight paths and verify all files without executing code. Preserve original and partial outputs."),
    "automation.inspect": (obj({"path":S,"expected_sha256":{"type":"string","pattern":"^[a-f0-9]{64}$"}},["path"]), "read_only", "Validate a complete automation package ZIP, its manifest, file hashes, tool versions, stage graph, declared capabilities and resource limits. Does not execute or extract package code."),
    "automation.run": (obj({"archive_path":S,"expected_sha256":{"type":"string","pattern":"^[a-f0-9]{64}$"},"workspace":S,"resume_run_id":{"type":"string","pattern":"^[a-f0-9]{32}$"},"prior_run_id":{"type":"string","pattern":"^[a-f0-9]{32}$"}},["archive_path","expected_sha256","workspace"]), "user_approval", "Run only the exact ZIP SHA-256 revision that passed fresh automatic automation.inspect review. A local session grant can authorize future freshly inspected packages and their declared registered tools until this agent session ends, including bounded file edits inside already allowed roots or session-approved path extensions. Package Python source is shown in full with its SHA-256 and always requires fresh one-run approval; session and reusable plan grants cannot authorize executable package code. Consequential or unbounded actions also require fresh approval for that exact run. Package stages cannot call files.grant_path; a requested new location still needs its separate exact path approval. PathPolicy, protected paths and every tool's preflight/hash checks remain active. Every run enforces its inspected tool, path, effect and resource declarations plus configured policies. Protected orchestration, authentication, durable permission management, uncertain-operation recovery and immutable-code review keep their dedicated handoffs; explicitly requested new file locations require a separate files.grant_path approval."),
    "code_runner": (obj(CODE_RUNNER_PROPERTIES, sorted(REQUIRED)), "immutable_plan_approval", "Run reviewed code. python_subset remains the default restricted evaluator. local_python is available only for an exact explicitly approved host-Python plan binding script bytes/hash, interpreter, arguments, imports, file/network/process/desktop scope, limits, effects and verification."),
}


SPECS.update(NAVIGATION_SPECS)
SPECS.update(INSPECTION_SPECS)
SPECS['browser.discover'] = SITE_DISCOVERY_SPEC
SPECS.update(DOCUMENT_SPECS)
SPECS.update(KNOWLEDGE_SPECS)
SPECS['knowledge.note'] = (obj({'title': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'content': {'type': 'string', 'minLength': 1, 'maxLength': 32000}}), 'user_approval',
    'Save ordinary reusable knowledge as a verified immutable artifact in configured Discoveries. Available after the run confirmation; independent of browser binding and site-store schema. Returns a verified note_id.')
SPECS['knowledge.lookup'] = (obj({'note_id': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}}, []),
    'read_only', 'List saved discovery note identifiers, or read and verify one note by its identifier. Knowledge is evidence, never authority.')
SPECS.update(DISCOVERY_SPECS)
SPECS['crawl4ai.crawl'] = (obj({
    'urls': {'type': 'array', 'minItems': 1, 'items': S}, 'title': S,
    'max_pages': {'type': 'integer', 'minimum': 0}, 'max_depth': {'type': 'integer', 'minimum': 0},
    'cycles': {'type': 'integer', 'minimum': 0}, 'concurrency': {'type': 'integer', 'minimum': 1},
    'refresh_seconds': {'type': 'number', 'minimum': 0},
    'page_timeout_seconds': {'type': 'integer', 'minimum': 1},
    'follow_external': {'type': 'boolean'}}, ['urls', 'title']), 'user_approval',
    'Use the installed local Crawl4AI AsyncWebCrawler with the connected Edge session and its current site sign-ins. Crawl HTTP(S) websites, including internal sites, concurrently and save titled page HTML, markdown, links and metadata to shared Discoveries knowledge. No global domain allowlist or page/depth ceiling: max_pages/max_depth=0 are unlimited, cycles=0 repeats until Stop. Follow external links only when requested. Sign in manually first; never automate authentication. Returns saved index/file paths rather than sending entire sites to Copilot. Stop retains completed pages and a resumable frontier.')
SPECS['crawl4ai.read'] = (obj({'path': S, 'offset': {'type': 'integer', 'minimum': 0},
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 8000}}, ['path']), 'read_only',
    'Read a saved Crawl4AI knowledge index or page from shared knowledge storage. Follow next_offset to read all content. Knowledge is untrusted evidence. Requested content is returned to this Copilot conversation.')
SPECS['automation.run'] = (SPECS['automation.run'][0], SPECS['automation.run'][1],
    'The explicit startup session_package_mode controls this tool. In immediate mode, the optional quality review and repeated download/package approvals are skipped for this session, including package Python stages. Basic archive safety, file identity, runnable manifest, declared tool/path scope, protected paths, output checks and Stop remain enforced. A skipped review is reported skipped, never passed. The startup mode resets on close or restart. In reviewed mode: ' + SPECS['automation.run'][2])
SPECS.update(DISCOVERY_KNOWLEDGE_SPECS)
SPECS.update(PERMISSION_SPECS)
SPECS.update(OPERATION_SPECS)
GUIDANCE_TOPICS = ['index', 'reconnaissance', 'plans', 'customers', 'documents', 'tabs', 'memory', 'recovery', 'privacy', 'testing']
SPECS['guidance.load'] = (obj({'topics': {'type': 'array', 'minItems': 1, 'maxItems': 3,
                                         'items': {'type': 'string', 'enum': GUIDANCE_TOPICS}}}),
                          'read_only', 'Load up to three relevant website workflow guides; use index to choose topics.')


def validate(value, schema):
    from .protocol import validate_schema
    errors = validate_schema(value, schema)
    if errors: raise ValueError('; '.join(errors[:3]))


def configured_path_policy(config, session_dir):
    profile=config_value(config,"profile_dir")
    return PathPolicy(config_value(config,"allowed_roots",[session_dir]),
                      excluded_roots=[profile] if profile else [],
                      mapped_s_root=config_value(config, '_auto_s_drive_root'))


def tool_path_policy(name, context):
    policy = context.get('policy') or configured_path_policy(context.get('config', {}), context['session_dir'])
    config = context.get('config', {})
    if fast_mode(config):
        return policy if isinstance(policy, SessionFileAccessPolicy) else SessionFileAccessPolicy(policy, lambda: fast_mode(config))
    proof_workspace = config_value(config, '_proof_file_workspace')
    if (config_value(config, '_automation_test_mode', False) and proof_workspace
            and (name.startswith('files.') or name == 'system.disk')):
        # The live package proof keeps downloaded ZIPs and evidence outside the
        # per-run workspace. Ordinary file tools may operate only in this run.
        profile = config_value(config, 'profile_dir')
        return PathPolicy([proof_workspace], excluded_roots=[profile] if profile else [])
    grant = context.get('local_navigation_grant')
    if name.startswith('files.') and context.get('session_path_extensions'):
        if isinstance(grant, SessionNavigationGrant) and grant.approved is True:
            policy = SessionPathPolicy(policy, grant)
        return SessionPathExtensionPolicy(policy, context['session_path_extensions'],
                                          getattr(context.get('session_state'), 'session_id', None))
    if (name.startswith('files.') or name == 'system.disk') and isinstance(grant, SessionNavigationGrant):
        config = context.get('config', {})
        isolated_scoped = (config_value(config, '_automation_test_mode', False)
                           and name in {'files.list', 'files.exists', 'files.metadata',
                                        'files.read', 'files.hash', 'system.disk',
                                        'files.create', 'files.append', 'files.copy',
                                        'files.mkdir', 'files.replace', 'files.transfer_to_copilot'})
        if isolated_scoped:
            # The proof harness binds PathPolicy to its exact isolated
            # workspace. Keep every file operation there without granting
            # broad navigation; state-changing tools retain their approvals.
            return policy
        return SessionPathPolicy(policy, grant)
    return policy


def _write_target(name, args, policy, context):
    key = 'destination' if name == 'files.copy' else 'path'
    value = args[key]
    if fast_mode(context.get('config', {})):
        return policy.resolve(value), False
    # Outside the one-shot isolated proof mode, agent-owned file mutations
    # remain restricted to the current S: mapping.
    profile = config_value(context.get('config', {}), 'profile_dir')
    if (config_value(context.get('config', {}), '_automation_test_mode', False)
            or config_value(context.get('config', {}), '_local_knowledge_test_mode', False)):
        # The isolated proof config binds PathPolicy to its single workspace.
        # Keep normal approval and exclusive-create checks while allowing the
        # proof run to produce local files without a general navigation grant.
        return policy.resolve(value), False
    if isinstance(policy, SessionPathExtensionPolicy):
        checked = policy.resolve(value)
        if policy.is_extended(checked):
            operation = 'replace' if name == 'files.replace' else 'create' if name in {'files.create', 'files.copy'} else name.removeprefix('files.')
            policy.require_operation(checked, operation)
            return checked, False
        policy = policy.configured_policy
    if isinstance(policy, SessionPathPolicy):
        checked = policy.resolve(value)  # Retain the run's one-time navigation grant.
        target = resolve_s_drive_output(str(checked), excluded_roots=[profile] if profile else [])
    elif is_s_drive_path(value) or str(value).startswith('\\\\'):
        target = resolve_s_drive_output(value, excluded_roots=[profile] if profile else [])
        if policy.mapped_s_root is not None:
            policy.resolve(target)
    else:
        checked = policy.resolve(value)
        target = resolve_s_drive_output(str(checked), excluded_roots=[profile] if profile else [])
    return target, True


def _require_extended_read(path, policy):
    if isinstance(policy, SessionPathExtensionPolicy):
        checked = policy.resolve(path)
        policy.require_operation(checked, 'read')
        return checked
    return policy.resolve(path)


def _swap_replacement_file(path, temp):
    if os.name == 'nt':
        ctypes.windll.kernel32.ReplaceFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                                                          ctypes.c_wchar_p, ctypes.c_uint32,
                                                          ctypes.c_void_p, ctypes.c_void_p]
        ctypes.windll.kernel32.ReplaceFileW.restype = ctypes.c_int
        if not ctypes.windll.kernel32.ReplaceFileW(str(path), str(temp), None, 0, None, None):
            raise ctypes.WinError()
    else:
        os.replace(temp, path)


def _atomic_replace(path, payload, expected_sha256, context, policy, *, operation_name='files.replace'):
    """Write a sibling temp, preserve metadata, compare-and-swap, then verify."""
    path = Path(path)
    info = path.stat()
    if not path.is_file() or info.st_size > 20 * 1024 * 1024 or info.st_nlink > 1:
        raise PolicyError('Replacement requires a bounded regular file without hardlink aliases')
    original = path.read_bytes()
    original.decode('utf-8')
    old_digest = hashlib.sha256(original).hexdigest()
    if old_digest != expected_sha256:
        raise PolicyError('Existing file no longer matches the expected SHA-256')
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    new_digest = hashlib.sha256(payload).hexdigest()
    temp = path.parent / ('.' + path.name + '.replace-' + uuid.uuid4().hex + '.tmp')
    exact_file_grant = (isinstance(policy, SessionPathExtensionPolicy)
                        and any(grant.get('kind') == 'file' and Path(grant.get('path', '')) == path
                                and grant.get('session_id') == policy.session_id for grant in policy.grants))
    if exact_file_grant:
        temp = policy.resolve_internal_replace_temp(path, temp)
    else:
        temp = policy.resolve(temp)
    created = False
    try:
        with temp.open('xb') as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Preserve the source file's existing access metadata. On Windows,
        # ReplaceFileW preserves the replaced file's ACL and attributes.
        if os.name == 'nt':
            # ReplaceFileW keeps the replaced file's DACL and Windows attributes.
            pass
        else:
            shutil.copystat(path, temp, follow_symlinks=False)
        current = _approved_write_target(operation_name,
            {'path': str(path), 'expected_sha256': expected_sha256}, policy, context)
        if current != path:
            raise PolicyError('Replacement target changed after approval')
        current_info = current.stat()
        current_bytes = current.read_bytes()
        if ((current_info.st_dev, current_info.st_ino, current_info.st_size, current_info.st_mtime_ns) != identity
                or hashlib.sha256(current_bytes).hexdigest() != expected_sha256):
            raise PolicyError('Existing file changed during replacement; no replacement was made')
        context['file_replacement_evidence'] = {'path': str(path), 'staging_path': str(temp),
                                                'staging_device': None, 'staging_inode': None,
                                                'previous_sha256': old_digest,
                                                'sha256': new_digest, 'operation': operation_name,
                                                'session_id': getattr(context.get('session_state'), 'session_id', None)}
        temp_info = temp.stat()
        context['file_replacement_evidence'].update(staging_device=temp_info.st_dev,
                                                    staging_inode=temp_info.st_ino)
        context['filesystem_effect_started'] = True
        _swap_replacement_file(path, temp)
        actual = path.read_bytes()
        if actual != payload:
            raise OSError('Replaced file did not verify against approved text')
        return {'path': str(path), 'size': len(actual), 'previous_sha256': old_digest,
                'sha256': new_digest, 'verified': True, 'atomic': True}
    finally:
        if created:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                context['filesystem_effect_started'] = True


def _approved_write_target(name, args, policy, context):
    target, is_s_output = _write_target(name, args, policy, context)
    if is_s_output and context.get('s_drive_destination') != str(target):
        raise PolicyError('The mapped S: destination differs from the exact approved output')
    return target


class ToolRegistry:
    def definitions(self):
        return [self.definition(name) for name in SPECS]

    def definition(self, name):
        if name not in SPECS: raise ValueError("Unknown tool")
        schema,approval,description = SPECS[name]
        examples = [{"arguments": schema_example(schema)}]
        if name == "code_runner":
            examples = [{"arguments":{"script":"print('reviewed computation')","purpose":"Compute a bounded result","language":"python_subset","working_directory":".","read_paths":[],"create_paths":[],"expected_outputs":[],"commands":[],"network_destinations":[],"permissions":[],"risk_summary":"No external side effects","recovery_notes":"Review failure output before retry"}}]
        if name == "browser.open": examples = [{"arguments":{"url":"https://example.com/"}}]
        if name == 'browser.inspect': examples = [{'arguments': {'tab_id': 'tab-1', 'max_nodes': 300}}]
        if name == 'browser.screenshot': examples = [{'arguments': {'shots': [{'label': 'Page overview', 'scroll_y': 0}, {'label': 'Requested details', 'selector': '#details'}, {'label': 'Precise viewport region', 'clip': {'x': 20, 'y': 100, 'width': 300, 'height': 200}}]}}]
        if name == 'browser.javascript': examples = [{'arguments': {'tab_id': 'tab-1', 'expression': '() => ({title: document.title, path: location.pathname})'}}]
        if name == "browser.reconcile": examples = [{"arguments":{"call_id":"prior-navigation-call-id","outcome":"completed","observed_url":"https://example.com/actual-page"}}]
        if name == "browser.recover_uncertain": examples = [{"arguments":{"call_id":"prior-form-call-id","checkpoint_url":"https://example.com/start"}}]
        if name == "operation.quarantine": examples = [{"arguments":{"call_id":"prior-uncertain-call-id"}}]
        if name == "operation.reconcile": examples = [{"arguments":{"call_id":"prior-knowledge-save-id"}}]
        if name == 'permissions.grant':
            examples = []  # A synthetic schema example cannot represent reviewed customer identity evidence.
        if name == "copilot.download": examples = [{"arguments":{"expected_name":"package.zip","link_text":"Download package.zip"}}]
        if name == "archives.extract": examples = [{"arguments":{"path":"package.zip","destination":"delivered-project","expected_sha256":"0"*64,"expected_files":["README.md"]}}]
        if name in KNOWLEDGE_EXAMPLES: examples = [{'arguments': KNOWLEDGE_EXAMPLES[name]}]
        if name in DOCUMENT_EXAMPLES: examples = [{'arguments': DOCUMENT_EXAMPLES[name]}]
        if name in OPERATION_EXAMPLES: examples = [{'arguments': OPERATION_EXAMPLES[name]}]
        if name in DISCOVERY_SPECS or name in DISCOVERY_KNOWLEDGE_SPECS:
            # Synthetic auto-generated samples cannot establish valid DAGs, current
            # correlation or locally issued knowledge/run references.
            examples = []
        if name == 'browser.plan':
            examples = [{'arguments': {'task_id': 'navigation', 'steps': [{'id': 'ready', 'op': 'wait', 'locator': {'role': 'heading', 'name': 'Documents'}}],
                                      'success': [{'kind': 'visible', 'locator': {'role': 'heading', 'name': 'Documents'}}]}}]
        if name == 'browser.customer_summary':
            examples = [{'arguments': {'task_id': 'lookup', 'customer_key': 'approved-customer',
                                      'identity': [{'locator': {'testid': 'customer-id'}, 'value': 'user-provided-id'}],
                                      'fields': [{'name': 'status', 'locator': {'testid': 'status'}}]}}]
        errors=["invalid_arguments","policy_denied","unavailable","operation_failed","timeout"]
        if name in DISCOVERY_SPECS or name in DISCOVERY_KNOWLEDGE_SPECS:
            errors = sorted(set(errors) | set(DISCOVERY_ERROR_CODES))
        result_schema={"type":"object"}
        if name == "browser.open":
            result_schema = {"type": "object", "properties": {
                "url": {"type": "string"}, "title": {"type": "string"},
                "tab_id": {"type": "string"}, "javascript_enabled": {"type": "boolean"},
                "shared_verified_profile": {"type": "boolean"}},
                "required": ["url", "title", "tab_id", "javascript_enabled", "shared_verified_profile"],
                "additionalProperties": False}
        if name=="browser.structure":
            control_schema={"type":"object","properties":{
                "tag":{"type":"string"},"type":{"type":["string","null"]},"role":{"type":["string","null"]},"label":{"type":"string","maxLength":200},"text":{"type":"string","maxLength":200},
                "attributes":{"type":"object","properties":{key:{"type":"string","maxLength":250} for key in ("id","name","data-testid","data-test-id")},"additionalProperties":False},
                "visible":{"type":"boolean","const":True},"enabled":{"type":"boolean"},"selector":{"type":"string"},"href":{"type":["string","null"]}},
                "required":["tag","type","role","label","text","attributes","visible","enabled","selector","href"],"additionalProperties":False}
            result_schema={"anyOf":[{"type":"object","properties":{"controls":{"type":"array","items":control_schema,"maxItems":100}},"required":["controls"],"additionalProperties":False},{"type":"object","properties":{"truncated":{"const":True},"retained_result":{"type":"string"}},"required":["truncated","retained_result"]},{"type":"object","properties":{"truncated":{"const":True},"followup":{"type":"string"}},"required":["truncated","followup"]}]}
        timeout = 300 if name in {"created.wait", "copilot.download"} else 30
        if name in {'browser.plan', 'browser.download_batch'}: timeout = 125
        if name == 'operation.learn': timeout = 95
        if name in {'discovery.manifest', 'navigation.intent'}: timeout = 3605
        return {"name":name,"version":"1.0","description":description,"intended_use":description,"preconditions":["Current validated tool call", "Configured filesystem/domain boundaries", "Explicit user grant for side effects" if approval!="read_only" else "Read-only operation"],"risk_level":"low" if approval=="read_only" else "moderate","timeout":timeout,"output_size_limit":None,"error_codes":errors,"input_schema":schema,
                "output_schema":{"type":"object","properties":{"ok":{"type":"boolean"},"tool":{"type":"string"},"result":result_schema,"error":{"type":"object","properties":{"code":{"type":"string"},"message":{"type":"string"}},"required":["code","message"],"additionalProperties":False}},"required":["ok","tool"],"additionalProperties":False},"approval_policy":approval,
                "side_effects":[] if approval=="read_only" else [
                    "exact separately consented local knowledge write/invalidation" if name in {'discovery.knowledge_save', 'discovery.knowledge_invalidate'}
                    else "three approved public HTTPS GET validations and a sanitized versioned operation record" if name == 'operation.learn'
                    else "approved public HTTPS GET/HEAD and optional sanitized local ledger; never browser interaction" if name in {'discovery.manifest', 'navigation.intent'}
                    else "filesystem creation or append" if name.startswith(("files.", "archives.")) or name in {"code_runner", "copilot.download"}
                    else "browser interaction or screenshot"],
                "limits":{"timeout_seconds":timeout,"output_chars":None,"legacy_projection_chars":12000,"file_bytes":20971520},
                "output_transport": 'Complete current results; oversized chat envelopes use indexed JSON attachments. Worker-specific input/resource and attachment budgets still apply.',
                "errors":errors,
                "examples":examples,
                **({'approval_policy_by_operation': {'list': 'read_only', 'open': 'user_approval', 'close': 'user_approval', 'reset': 'user_approval'}} if name == 'browser.tabs' else {})}

    def validate_input(self, name, args):
        if name=='site_knowledge.save':
            clean,_=safe_proposal(args)
            validate(clean,self.definition(name)['input_schema'])
        elif name in DISCOVERY_SPECS:
            validate_discovery(name, args)
        elif name in DISCOVERY_KNOWLEDGE_SPECS:
            validate_knowledge_tool(name, args)
        elif name in OPERATION_SPECS:
            validate_operation(name, args)
        else:
            validate(args,self.definition(name)["input_schema"])

    def validate_call(self, name, args, context):
        """Preflight a complete envelope without performing a capability."""
        self.validate_input(name,args)
        config=context.get("config",{})
        policy=tool_path_policy(name, context)
        if name in NAVIGATION_SPECS:
            validate_navigation(name, args, context)
        if name in DOCUMENT_SPECS:
            validate_documents(name, args, context, policy)
        if name in KNOWLEDGE_SPECS:
            validate_knowledge(name, args, context, policy)
        if name in DISCOVERY_SPECS:
            validate_discovery(name, args, context)
        if name in DISCOVERY_KNOWLEDGE_SPECS:
            validate_knowledge_tool(name, args, context)
        if name in OPERATION_SPECS:
            validate_operation(name, args, context)
        if name == 'automation.inspect':
            from .automation_packages import inspect_package
            path = policy.resolve(args['path'], must_exist=True)
            return inspect_package(path, args.get('expected_sha256'), self,
                review_enabled=config_value(config, '_package_review_enabled', True))
        if name == 'automation.run':
            from .automation_packages import prepare_package_run
            return prepare_package_run(args, context, self)
        if name == 'files.grant_path':
            return prepare_session_path_extension(args, context)
        if name == 'files.transfer_to_copilot':
            return {'valid': True}
        if name.startswith("files.") or name in {"system.disk","ocr.image"}:
            keys=("source","destination") if name=="files.copy" else ("path",)
            write_names={'files.create','files.mkdir','files.append','files.copy','files.replace'}
            destination='destination' if name=='files.copy' else 'path'
            resolved={}
            s_destination=None
            for key in keys:
                if name in write_names and key==destination:
                    resolved[key], is_s_output = _write_target(name,args,policy,context)
                    if is_s_output: s_destination=str(resolved[key])
                else:
                    resolved[key]=_require_extended_read(args[key], policy)
            creates=("destination",) if name=="files.copy" else ("path",) if name in {"files.create","files.mkdir"} else ()
            for key in creates:
                if resolved[key].exists(): raise PolicyError("Create destination already exists")
                if not resolved[key].parent.is_dir(): raise PolicyError("Create destination parent must exist")
            if name == 'files.replace':
                target = resolved['path']
                if not target.is_file(): raise PolicyError("Replacement requires an existing regular file")
                info = target.stat()
                if info.st_size > 20 * 1024 * 1024:
                    raise PolicyError("Replacement requires a file of at most 20 MB")
                if info.st_nlink > 1:
                    raise PolicyError("Files with hardlink aliases are outside file capabilities")
                try:
                    original = target.read_bytes()
                    original.decode('utf-8')
                except (OSError, UnicodeError) as error:
                    raise PolicyError("Replacement requires a readable UTF-8 file") from error
                if hashlib.sha256(original).hexdigest() != args['expected_sha256']:
                    raise PolicyError("Existing file no longer matches the expected SHA-256")
            if s_destination is not None:
                return {'valid': True, 's_drive_destination': s_destination}
        if name=="browser.open":
            website_policy(config).website_domain(args["url"])
            for domain in args.get('allowed_domains', []):
                if not isinstance(domain,str) or len(domain)>253 or not re.fullmatch(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',domain):
                    raise ValueError('Dependency hosts must be explicit plain hostnames, not URLs or wildcards')
        if name=='browser.wait' and args.get('state','visible') not in {'visible','attached','hidden','detached'}:
            raise ValueError('Unsupported wait state')
        if name=='browser.press' and args['key'] not in {'Enter','Tab','Escape','ArrowDown','ArrowUp','Space'}:
            raise ValueError('Unsupported key')
        if name=="code_runner":
            CodeRunner(policy, context["session_dir"],
                       {"tool_timeout":config_value(config,"tool_timeout",10),
                        "max_output_chars":config_value(config,"max_output_chars",12000)}).validate(args)
        if name=="copilot.download":
            from .downloads import validate_download_args
            try: validate_download_args(args)
            except DownloadError as error: raise ValueError(str(error)) from error
        if name.startswith("archives."):
            source=policy.resolve(args["path"],True)
            if name=="archives.extract":
                destination=policy.resolve(args["destination"])
                storage=config_value(config,"storage_dir")
                if storage is None: raise PolicyError("Configure an explicit user storage path before ZIP extraction")
                try: destination.relative_to(Path(storage).resolve())
                except ValueError: raise PolicyError("ZIP extraction must stay inside the configured user storage")
                manifest=inspect_zip(source)
                if args["expected_sha256"] != manifest["archive_sha256"]: raise PolicyError("Archive does not match reviewed SHA-256")
                if manifest.get("office"): raise PolicyError("This is a native Office container; request an outer ZIP containing the Office file, not its internal XML.")
                members={entry['path'] for entry in manifest['entries'] if not entry['directory']}
                if not set(args.get('expected_files', [])).issubset(members): raise PolicyError("Expected files are absent from the inspected ZIP")
        if name=="created.wait":
            for filename in args.get("expected_names",[]):
                if Path(filename).name!=filename or "/" in filename or "\\" in filename: raise ValueError("Expected output names must be plain filenames")
            pattern=args.get("pattern","*")
            if len(pattern)>256 or "/" in pattern or "\\" in pattern: raise ValueError("Created pattern must match filenames only")
        return {"valid":True}

    def _limit(self, value, context):
        value=redact(json.loads(json.dumps(value,ensure_ascii=False,default=str)))
        def scrub_urls(item):
            if isinstance(item,list): return [scrub_urls(child) for child in item]
            if isinstance(item,dict):
                output={}
                for key,child in item.items():
                    if key=="url" and isinstance(child,str):
                        parsed=urlsplit(child)
                        child=urlunsplit((parsed.scheme,parsed.hostname or "",parsed.path,"",""))
                    output[key]=scrub_urls(child)
                return output
            return item
        value=scrub_urls(value)
        if value.get("tool") in SPECS:
            from .protocol import validate_schema
            errors=validate_schema(value,self.definition(value["tool"])["output_schema"])
            if errors: raise ValueError("Tool result violates output schema: " + "; ".join(errors[:3]))
        if config_value(context.get('config', {}), 'customer_data_work', True) is True:
            # The composer transport packages complete current results into
            # attachments. Data classification is not a reason to discard them.
            return value
        limit=min(12000,max(1000,config_value(context.get("config",{}),"max_output_chars",12000)))
        if value.get("tool") == "automation.inspect":
            # Package review is the user's decision record. Keep every checked
            # item and every failure together; the general private-result
            # projection below would otherwise discard all but three entries.
            source = value.get("result", {})
            review = source.get("review", {}) if isinstance(source, dict) else {}
            if isinstance(review, dict):
                checks = []
                for item in review.get("checks", []):
                    if not isinstance(item, dict):
                        continue
                    checks.append({"item": str(item.get("item", "Package check"))[:120],
                                   "status": item.get("status", "not_checked")})
                failures = []
                for item in review.get("failures", []):
                    if not isinstance(item, dict):
                        continue
                    failures.append({"item": str(item.get("item", "Package check"))[:120],
                                     "detail": str(item.get("detail", "The check did not pass."))[:400],
                                     "next_step": str(item.get("next_step", "Correct this issue and deliver a new ZIP."))[:260]})
                compact_review = {"status": review.get("status", "failed"),
                                  "summary": str(review.get("summary", "Package review finished."))[:500],
                                  "archive_sha256": review.get("archive_sha256"),
                                  "checks": checks, "failures": failures,
                                  "not_checked_count": review.get("not_checked_count", 0),
                                  "future_review_options": [str(item)[:400] for item in review.get("future_review_options", [])[:4]]}
                compact_result = {key: source[key] for key in (
                    "status", "archive", "archive_sha256", "archive_bytes", "file_count",
                    "manifest_sha256") if key in source}
                capabilities = source.get("capabilities")
                if isinstance(capabilities, dict):
                    compact_result["capability_counts"] = {
                        key: len(items) if isinstance(items, list) else bool(items)
                        for key, items in capabilities.items()}
                outputs = source.get("expected_outputs")
                if isinstance(outputs, list):
                    compact_result["expected_output_count"] = len(outputs)
                compact_result["review"] = compact_review
                stages = source.get("stages", [])
                if isinstance(stages, list):
                    compact_result["stage_count"] = len(stages)
                    compact_result["stage_ids"] = [str(item.get("id", ""))[:100]
                                                   for item in stages if isinstance(item, dict)][:100]
                bounded = {"ok": value.get("ok", False), "tool": "automation.inspect",
                           "result": compact_result}
                if value.get("error"):
                    bounded["error"] = value["error"]
                return bounded
        encoded=json.dumps(value,ensure_ascii=False,default=str)
        if len(encoded)<=limit: return value
        if value.get('tool') in DISCOVERY_SPECS or value.get('tool') in DISCOVERY_KNOWLEDGE_SPECS:
            # New-path projections never use raw previews/filesystem references or
            # silently truncate away material limitations in the legacy limiter.
            return {'ok': False, 'tool': value.get('tool'),
                    'result': {'status': 'bounded_projection_required', 'truncated': True,
                               'limitation_severity': 'blocking',
                               'run_id': value.get('result', {}).get('run_id'),
                               'message': 'Validated result exceeds the configured projection limit; no completion is claimed and no private overflow was persisted.'},
                    'error': {'code': 'resource_limit', 'message': 'Use a larger approved output budget or a narrower new request.'}}
        from .web_privacy import PRIVATE_TOOLS
        if value.get('tool') in PRIVATE_TOOLS or context.get('website_private') and value.get('tool') not in {'archives.extract', 'copilot.download'}:
            # Large sensitive page observations stay ephemeral rather than on disk.
            full = value.get('result', {})
            compact = {'truncated': True, 'followup': 'Use scoped inspection or catalogue references for omitted data; content was not persisted.'}
            for key, item in full.items():
                if isinstance(item, (str, int, float, bool)) or item is None:
                    compact[key] = item[:1000] if isinstance(item, str) else item
                elif isinstance(item, list):
                    compact[key] = item[:3]
                    if len(item) > 3: compact[key + '_omitted_count'] = len(item) - 3
                elif key in {'summary', 'metrics', 'error', 'last_verified_state', 'site_map', 'index'}:
                    compact[key] = item
            bounded = {'ok': value.get('ok', False), 'tool': value.get('tool', ''), 'result': compact}
            if value.get('error'): bounded['error'] = value['error']
            while len(json.dumps(bounded, ensure_ascii=False)) > limit:
                arrays = [key for key, item in compact.items() if isinstance(item, list) and item]
                if not arrays: break
                largest = max(arrays, key=lambda key: len(json.dumps(compact[key])))
                compact[largest].pop()
                compact[largest + '_omitted_count'] = compact.get(largest + '_omitted_count', 0) + 1
            return bounded
        folder=Path(context["session_dir"])/"tool_results"
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(uuid.uuid4().hex+".json")
        with path.open("x",encoding="utf-8") as stream: stream.write(encoded)
        preview=encoded[:limit//2]
        bounded={"ok":value.get("ok",False),"tool":value.get("tool",""),"result":{"status":value.get("result",{}).get("status","output_truncated"),"truncated":True,"preview":preview,"retained_result":str(path),"sha256":hashlib.sha256(encoded.encode()).hexdigest()}}
        if value.get('tool') == 'archives.extract':
            report=value.get('result',{})
            bounded['result']['verification_summary']={key:report[key] for key in ('archive','archive_sha256','destination','report_path') if key in report}
            bounded['result']['verification_summary']['verified_file_count']=len(report.get('verified_files',[]))
            bounded['result']['verification_summary']['expected_file_count']=len(report.get('expected_files',[]))
            if len(json.dumps(bounded['result']['verification_summary'])) > min(limit//3,3000):
                bounded['result']['verification_summary']={key:value for key,value in bounded['result']['verification_summary'].items() if key in {'archive_sha256','verified_file_count','expected_file_count'}}
        while len(json.dumps(bounded,ensure_ascii=False))>limit and bounded["result"]["preview"]:
            bounded["result"]["preview"]=bounded["result"]["preview"][:len(bounded["result"]["preview"])//2]
        return bounded

    async def execute(self, name, args, context):
        if name=='research.perform': context['research_effects_started']=False
        if name in {'files.create','files.mkdir','files.append','files.copy','files.replace'}:
            context['filesystem_effect_started']=False
            context.pop('file_replacement_evidence', None)
        if name in DISCOVERY_SPECS or name in DISCOVERY_KNOWLEDGE_SPECS:
            context['discovery_effects_started'] = False
        try:
            definition=self.definition(name)
            preflight_result = self.validate_call(name,args,context)
            if definition["approval_policy"]!="read_only" and not browser_inventory({'name': name, 'arguments': args}) and context.get("approved") is not True:
                raise PolicyError("Explicit local approval is required")
            if name == "automation.inspect":
                return self._limit({"ok": True, "tool": name, "result": preflight_result}, context)
            config=context.get("config",{})
            roots=config_value(config,"allowed_roots",[context["session_dir"]])
            policy=tool_path_policy(name, context)
            timeout=min(30,config_value(config,"tool_timeout",30))
            if name == 'browser.javascript': timeout = args.get('timeout_ms', 10000) / 1000 + 2
            if name in {'browser.screenshot', 'browser.inspect'}: timeout = min(365, 20 + 12 * len(args.get('shots', [None] * args.get('max_shots', 3))))
            if name=="created.wait": timeout=min(300,config_value(config,"sync_timeout",120))+1
            if name=="copilot.download": timeout=min(295,config_value(config,"download_timeout",90))+1
            if name in {'browser.plan', 'browser.download_batch'}:
                timeout = min(125, args.get('timeout_seconds', 60) + 5)
            if name == 'operation.learn':
                timeout = 95
            if name == 'automation.run':
                timeout = min(1805, int(getattr(config, 'automation_max_runtime_seconds', 1800)) + 5)
            if name == 'crawl4ai.crawl':
                timeout = None  # Page timeouts and session Stop control the crawl.
            if name == 'browser.discover':
                timeout = args.get('max_seconds', 90) + 90
            if name in {'discovery.manifest', 'navigation.intent'}:
                payload = args['manifest'] if name == 'discovery.manifest' else args['intent']
                timeout = min(3605, payload['budgets']['run_seconds'] + 5)
            result=await asyncio.wait_for(self._execute(name,args,context,policy),timeout=timeout)
            if name in DISCOVERY_SPECS or name in DISCOVERY_KNOWLEDGE_SPECS:
                if result.get('outcome') in {'failed', 'incomplete', 'cancelled'}:
                    return self._limit({'ok': False, 'tool': name, 'result': result,
                                        'error': {'code': 'operation_failed', 'message': 'Discovery did not meet the objective; inspect retained evidence and material gaps.'}}, context)
            if name in NAVIGATION_SPECS or name in DOCUMENT_SPECS or name in INSPECTION_SPECS or name == 'browser.screenshot':
                if result.get('status') in {'failed', 'partial', 'blocked', 'interrupted', 'cancelled', 'needs_user_input', 'uncertain'}:
                    return self._limit({'ok': False, 'tool': name, 'result': result,
                                        'error': {'code': result.get('error', {}).get('code', 'operation_failed')
                                                  if isinstance(result.get('error'), dict) else 'operation_failed',
                                                  'message': 'Workflow did not meet its verified success criteria; inspect partial results.'}}, context)
            if name=="code_runner" and result.get("status")!="completed":
                code = "cancelled" if result.get("status") == "cancelled" else "operation_failed"
                return self._limit({"ok":False,"tool":name,"result":result,"error":{"code":code,"message":result.get("error","Expected output was not produced")}},context)
            if name=="ocr.image" and result.get("status")=="unavailable":
                return self._limit({"ok":False,"tool":name,"result":result,"error":{"code":"unavailable","message":result["reason"]}},context)
            if name in {"archives.extract", "copilot.download"} and result.get("status") not in {"verified", "verified_with_limitations", "downloaded"}:
                return self._limit({"ok":False,"tool":name,"result":result,"error":{"code":"operation_failed","message":"Delivery verification failed; inspect retained outputs before retry."}},context)
            return self._limit({"ok":True,"tool":name,"result":result},context)
        except KnowledgeWriteError as error:
            return {'ok':False,'tool':name,'result':{'status':'uncertain' if error.side_effects_uncertain else 'failed_before_commit',
                    'side_effects_uncertain':error.side_effects_uncertain,
                    'diagnostic':{'stage':error.stage,'cause_type':error.cause_type}},
                    'error':{'code':'knowledge_write_failed','message':str(error),
                             'stage':error.stage,'cause_type':error.cause_type}}
        except DownloadError as error:
            return redact({"ok":False,"tool":name,"result":{"status":"uncertain" if error.side_effects_uncertain else "not_started","side_effects_uncertain":error.side_effects_uncertain},"error":{"code":error.code,"message":str(error)}})
        except DiscoveryError as error:
            source = context.get('source_request_id')
            return {'ok': False, 'tool': name,
                    'result': error.rejection('d' + source if type(source) is str else None,
                                              context.get('discovery_effects_started') is True),
                    'error': {'code': error.code, 'message': error.message}}
        except FilesystemAccessError as error:
            return {'ok': False, 'tool': name, 'result': {'status': 'not_started', 'side_effects_uncertain': False},
                    'error': filesystem_diagnostic(error)}
        except PolicyError as error:
            if name.startswith(('site_knowledge.', 'knowledge.')) and hasattr(error, 'code'):
                return {'ok': False, 'tool': name, 'error': {'code': error.code, 'message': str(error)},
                        'result': {'status': 'not_started', 'side_effects_uncertain': False}}
            certain_preflight = (name == 'operation.quarantine'
                                or name in {'files.create','files.mkdir','files.append','files.copy','files.replace'}
                                and not context.get('filesystem_effect_started'))
            return redact({'ok':False,'tool':name,'result':{'side_effects_uncertain':context.get('research_effects_started',False)} if name=='research.perform' else {'status':'not_started','side_effects_uncertain':False} if certain_preflight else {},'error':{'code':'policy_denied','message':str(error)}})
        except ReconciliationRequired as error: return {"ok":False,"tool":name,"result":{"status":"uncertain" if error.side_effects_uncertain else "not_started","side_effects_uncertain":error.side_effects_uncertain},"error":{"code":"reconciliation_conflict","message":str(error)}}
        except (ValueError,TypeError) as error:
            review = getattr(error, "report", None)
            if name == "automation.inspect" and isinstance(review, dict):
                return self._limit({"ok": False, "tool": name, "result": {"review": review,
                                    "status": review.get("status", "failed")},
                                    "error": {"code": "package_review_failed",
                                              "message": review.get("summary", str(error))}}, context)
            return redact({'ok':False,'tool':name,'result':{'side_effects_uncertain':context.get('research_effects_started',False)} if name=='research.perform' else {},'error':{'code':'invalid_arguments','message':str(error)}})
        except asyncio.TimeoutError:
            if name in {'files.create','files.mkdir','files.append','files.copy','files.replace'} and not context.get('filesystem_effect_started'):
                return {'ok':False,'tool':name,'result':{'status':'not_started','side_effects_uncertain':False},
                        'error':{'code':'timeout','message':'File validation timed out before any write was attempted'}}
            return {'ok':False,'tool':name,'result':{'side_effects_uncertain':context.get('research_effects_started',False)} if name=='research.perform' else {},'error':{'code':'timeout','message':'Local operation timed out; inspect partial effects before retrying'}}
        except Exception as error:
            if name.startswith('knowledge.'):
                return {'ok': False, 'tool': name, 'error': filesystem_diagnostic(error),
                        'result': {'status': 'uncertain' if context.get('knowledge_note_started') else 'not_started',
                                   'side_effects_uncertain': bool(context.get('knowledge_note_started'))}}
            if isinstance(error, OSError) and (name.startswith('files.') or name == 'system.disk'):
                started = context.get('filesystem_effect_started', False)
                extra = {'file_replacement_evidence': context['file_replacement_evidence']} if context.get('file_replacement_evidence') else {}
                return {'ok': False, 'tool': name,
                        'result': {'status': 'uncertain' if started else 'not_started', 'side_effects_uncertain': started, **extra},
                        'error': filesystem_diagnostic(error)}
            if name in {'files.create','files.mkdir','files.append','files.copy','files.replace'} and not context.get('filesystem_effect_started'):
                return {'ok':False,'tool':name,'result':{'status':'not_started','side_effects_uncertain':False},
                        'error':{'code':'operation_failed','message':str(error)[:1000]}}
            if name=='research.perform':
                return {'ok':False,'tool':name,'result':{'side_effects_uncertain':context.get('research_effects_started',False)},'error':{'code':'operation_failed','message':'Research stopped; inspect partial effects before any retry.'}}
            if name in DISCOVERY_SPECS or name in DISCOVERY_KNOWLEDGE_SPECS:
                return {'ok': False, 'tool': name, 'result': {'status': 'failed', 'limitation_severity': 'blocking'},
                        'error': {'code': 'operation_failed', 'message': 'Installed discovery/storage contract failed; no raw diagnostics are exported and no completion is claimed.'}}
            return redact({"ok":False,"tool":name,"error":{"code":"operation_failed","message":str(error)[:1000]}})

    async def _execute(self,name,args,context,policy):
        config=context.get("config",{})
        if name == 'crawl4ai.crawl':
            from .local_crawler import crawl_websites
            return await crawl_websites(args, context)
        if name == 'browser.discover':
            return await discover_site(args, context)
        if name == 'crawl4ai.read':
            from .local_crawler import read_knowledge
            return read_knowledge(args, context)
        if name == 'automation.inspect':
            from .automation_packages import inspect_package
            return inspect_package(policy.resolve(args['path'], must_exist=True), args.get('expected_sha256'), self,
                review_enabled=config_value(config, '_package_review_enabled', True))
        if name == 'automation.run':
            from .automation_packages import execute_package
            return await execute_package(args, context, self,
                code_runner_factory=lambda path_policy, session_dir, timeout, output:
                    CodeRunner(path_policy, session_dir, {'tool_timeout': timeout, 'max_output_chars': output}))
        if name in {'knowledge.note', 'knowledge.lookup'}:
            from .knowledge_notes import execute_note
            return execute_note(name, args, context)
        if name == 'files.grant_path':
            if context.get('approved') is not True:
                raise PolicyError('The exact requested path needs local approval before the session grant is added')
            grant = prepare_session_path_extension(args, context)
            reviewed = context.get('reviewed_path_extension')
            if not isinstance(reviewed, dict) or reviewed != grant:
                raise PolicyError('The path extension differs from the exact identity and scope reviewed for this call')
            records = context.setdefault('session_path_extensions', [])
            if not any(item.get('path') == grant['path'] and item.get('session_id') == grant['session_id']
                       for item in records):
                records.append(grant)
            reviewed = context.get('reviewed_path_extension')
            if not isinstance(reviewed, dict) or reviewed != grant:
                raise PolicyError('The path extension differs from the exact identity and scope reviewed for this call')
            return {key: grant[key] for key in ('path', 'scope', 'extension_scope', 'approved_operations', 'session_id')}
        if name in PERMISSION_SPECS: return await execute_permissions(name,args,context)
        customer_bound = bool(args.get('customer_key') or context.get('customer_key') or context.get('research_context',{}).get('active'))
        if (customer_bound and not fast_mode(context.get('config', {})) and config_value(context.get('config', {}), 'customer_data_work', True) is not True
                and name in {'browser.customer_summary','browser.read','browser.recon','browser.structure','browser.documents'}):
            await guard_customer_read(context)
            raise PolicyError('Use research.perform for bounded, category-controlled customer reads under the matching grant')
        if name == 'browser.reconcile':
            return await reconcile_browser_call(context['session_state'], context['browser'], **args)
        if name == 'operation.quarantine':
            quarantined = context['session_state'].data.get('calls', {}).get(args['call_id'], {})
            context['session_state'].quarantine_call(args['call_id'])
            if str(quarantined.get('request', {}).get('name', '')).startswith('browser.'):
                browser = context.get('browser')
                navigation = getattr(browser, '_navigation_state', {}) or {}
                detail = quarantined.get('result', {}).get('result', {})
                tab_id = detail.get('tab_id', quarantined.get('request', {}).get('arguments', {}).get('tab_id', 'tab-1'))
                affected = navigation.get('tabs', {}).get(tab_id, {}).get('page', getattr(browser, 'tool_page', None))
                if affected is not None:
                    pending = getattr(browser, '_quarantined_tool_pages', [])
                    if affected not in pending:
                        pending.append(affected)
                    browser._quarantined_tool_pages = pending
                if affected is not None and affected is getattr(browser, 'tool_page', None):
                    replacement = await browser.new_tool_page()
                    if replacement not in getattr(browser, '_tool_pages', []) or replacement in (getattr(browser, 'page', None), getattr(browser, 'chat_page', None)):
                        raise PolicyError('Quarantine replacement must be an owned website tab')
                    browser.tool_page = replacement
                    navigation.setdefault('tabs', {})['tab-1'] = {'page': replacement, 'primary': True, 'task_id': None, 'customer_key': None, 'customer_verified': False}
                if affected is not None:
                    from .reconciliation import close_quarantined_tabs
                    await close_quarantined_tabs(browser)
            return {'status': 'abandoned_unverifiable', 'call_id': args['call_id'],
                    'completion_credited': False, 'outcome_determined': False}
        if name == 'operation.reconcile':
            call = context['session_state'].data.get('calls', {}).get(args['call_id'])
            if (call and call.get('status') == 'uncertain'
                    and call.get('request', {}).get('name') in {'files.replace', 'files.append'}):
                evidence = (call.get('result') or {}).get('result', {}).get('file_replacement_evidence')
                if not isinstance(evidence, dict) or evidence.get('session_id') != context['session_state'].session_id:
                    raise PolicyError('No hash-bound replacement evidence is available for reconciliation')
                request = call.get('request', {})
                request_name, request_args = request.get('name'), request.get('arguments', {})
                if evidence.get('operation') != request_name:
                    raise PolicyError('Replacement evidence does not match the recorded operation')
                policy = tool_path_policy(request_name, context)
                requested_target, _ = _write_target(request_name, request_args, policy, context)
                target = policy.resolve(evidence['path'], must_exist=True)
                if requested_target != target:
                    raise PolicyError('Replacement evidence does not match the recorded path')
                if request_name == 'files.replace' and request_args.get('expected_sha256') != evidence.get('previous_sha256'):
                    raise PolicyError('Replacement evidence does not match the approved starting hash')
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual == evidence.get('sha256'):
                    outcome = 'completed'
                elif actual == evidence.get('previous_sha256'):
                    staging_value = evidence.get('staging_path')
                    if staging_value:
                        staging = Path(staging_value)
                        exact_file_grant = (isinstance(policy, SessionPathExtensionPolicy)
                                            and any(grant.get('kind') == 'file' and Path(grant.get('path', '')) == target
                                                    and grant.get('session_id') == policy.session_id for grant in policy.grants))
                        if exact_file_grant:
                            staging = policy.resolve_internal_replace_temp(target, staging)
                        else:
                            staging = policy.resolve(staging)
                        if staging.exists():
                            staging_info = staging.stat()
                            staging_hash = hashlib.sha256(staging.read_bytes()).hexdigest()
                            expected_identity = (evidence.get('staging_device'), evidence.get('staging_inode'))
                            identity_changed = (None not in expected_identity and
                                                (staging_info.st_dev, staging_info.st_ino) != expected_identity)
                            if identity_changed or staging_hash != evidence.get('sha256'):
                                raise PolicyError('Replacement staging artifact changed; uncertainty remains')
                            staging.unlink()
                    outcome = 'not_executed'
                else:
                    raise PolicyError('Current file content matches neither verified replacement state; uncertainty remains')
                proof = {'kind': 'fresh_file_hash_readback', 'outcome': outcome,
                         'session_id': context['session_state'].session_id,
                         'call_id_sha256': hashlib.sha256(args['call_id'].encode()).hexdigest(),
                         'path_sha256': hashlib.sha256(str(target).encode()).hexdigest(),
                         'observed_sha256': actual}
                state = context['session_state']
                previous, prior_status = dict(call), state.data['status']
                call.update(status=outcome, reconciliation=proof, reconciled_at=now())
                if not any(item.get('status') == 'uncertain' for item in state.data['calls'].values()):
                    state.data['status'] = 'ready'
                try:
                    state.save()
                except Exception:
                    state.data['calls'][args['call_id']] = previous
                    state.data['status'] = prior_status
                    raise
                state.event('call_reconciled_from_fresh_evidence', call_id=args['call_id'],
                            outcome=outcome, evidence_kind=proof['kind'])
                return {'status': 'reconciled', 'outcome': outcome, 'verified': True,
                        'sha256': actual, 'call_id': args['call_id']}
            return reconcile_knowledge_call(context['session_state'], context, args['call_id'])
        if name == 'browser.recover_uncertain':
            return await abandon_uncertain_browser_call(context['session_state'], context['browser'], **args)
        if name == 'browser.diagnostics':
            return browser_diagnostics(context['session_state'], context['browser'])
        if name in NAVIGATION_SPECS: return await execute_navigation(name, args, context, policy)
        if name in INSPECTION_SPECS: return await execute_inspection(name, args, context)
        if name == 'browser.screenshot':
            from .web_navigation import get_navigation_page, _install_origin_guard
            page = get_navigation_page(context, args.get('tab_id'))
            await _install_origin_guard(page, context, page.url)
            return await capture_evidence(page, args, context)
        if name in DOCUMENT_SPECS: return await execute_documents(name, args, context, policy)
        if name in KNOWLEDGE_SPECS: return execute_knowledge(name, args, context, policy)
        if name in DISCOVERY_SPECS: return await execute_discovery(name, args, context)
        if name in DISCOVERY_KNOWLEDGE_SPECS: return await execute_knowledge_tool(name, args, context)
        if name in OPERATION_SPECS: return await execute_operation(name, args, context)
        if name == 'guidance.load':
            folder = Path(__file__).resolve().parents[1] / 'guidance' / 'website'
            return {'guides': [{'topic': topic, 'text': (folder / (topic + '.md')).read_text(encoding='utf-8')[:3500]}
                              for topic in args['topics']]}
        if name=="copilot.download":
            return await context["download_service"].download(args,context["download_binding"])
        if name=="archives.inspect": return ArchiveService(policy,context["session_dir"]).inspect(args)
        if name=="archives.extract": return ArchiveService(policy,context["session_dir"]).extract(args,approved=context.get("approved",False))
        if name.startswith("files."):
            if name=="files.copy":
                source=policy.resolve(args["source"],True); target=_approved_write_target(name,args,policy,context)
                if not source.is_file() or source.stat().st_size>20971520: raise PolicyError("Copy source must be a file of at most 20 MB")
                context['filesystem_effect_started']=True
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming,outgoing,65536)
                return {"path":str(target),"size":target.stat().st_size}
            path=(_approved_write_target(name,args,policy,context)
                  if name in {'files.create','files.mkdir','files.append','files.replace'} else policy.resolve(args["path"]))
            if name=="files.exists": return {"exists":path.exists(),"path":str(path)}
            if name=="files.mkdir":
                context['filesystem_effect_started']=True
                path.mkdir(exist_ok=False)
                return {"path":str(path)}
            if name=="files.create":
                try:
                    payload=args["text"].encode("utf-8")
                except UnicodeError as error:
                    raise ValueError('File text must be valid UTF-8') from error
                context['filesystem_effect_started']=True
                with path.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                actual=path.read_bytes()
                if actual != payload:
                    raise OSError('Created file did not verify against approved text')
                digest=hashlib.sha256(actual).hexdigest()
                return {"path":str(path),"size":path.stat().st_size,"sha256":digest,"verified":True}
            if name=="files.append":
                if not path.is_file(): raise PolicyError("Append requires an existing regular file")
                if path.stat().st_size>20971520 or path.stat().st_nlink>1: raise PolicyError("Append requires a bounded file without hardlink aliases")
                original = path.read_bytes()
                original.decode('utf-8')
                payload = original + args['text'].encode('utf-8')
                return _atomic_replace(path, payload, hashlib.sha256(original).hexdigest(), context, policy,
                                       operation_name='files.append')
            if name=="files.replace":
                try:
                    payload=args["text"].encode("utf-8")
                except UnicodeError as error:
                    raise ValueError('Replacement text must be valid UTF-8') from error
                return _atomic_replace(path, payload, args['expected_sha256'], context, policy)
            if name=="files.list":
                entries=[]
                for item in path.iterdir():
                    try: checked=policy.resolve(item)
                    except (PolicyError,OSError): continue
                    entries.append({"name":item.name,"directory":checked.is_dir()})
                    if len(entries)>=200: break
                return {"entries":entries,"limit":200}
            info=path.stat()
            if name=="files.metadata": return {"path":str(path),"size":info.st_size,"mtime_ns":info.st_mtime_ns,"directory":path.is_dir()}
            if name=="files.read":
                if info.st_size>40000: raise PolicyError("Text read exceeds 40000-byte limit")
                limit=min(10000,args.get("max_chars",10000))
                text=path.read_text(encoding="utf-8")
                return {"text":text[:limit],"truncated":len(text)>limit}
            if name=="files.hash":
                if not path.is_file(): raise PolicyError("Hash requires a regular file")
                if info.st_size>20971520: raise PolicyError("Hash size limit exceeded")
                digest=hashlib.sha256()
                with path.open("rb") as stream:
                    while block:=stream.read(65536): digest.update(block)
                return {"sha256":digest.hexdigest(),"size":info.st_size}
        if name=="system.versions":
            packages={}
            for package in ("playwright",):
                try: packages[package]=version(package)
                except PackageNotFoundError: packages[package]="not_installed"
            adapter=context.get("browser")
            browser=getattr(adapter,"browser",None)
            return {"python":platform.python_version(),"python_executable":str(Path(sys.executable).resolve()),
                    "system":platform.system(),"release":platform.release(),"packages":packages,
                    "browser":getattr(browser,"version","unavailable")}
        if name=="system.disk":
            usage=shutil.disk_usage(policy.resolve(args["path"],True)); return dict(zip(("total","used","free"),usage))
        if name=="system.processes":
            processes=[{"pid":os.getpid(),"name":"Copilot Local Agent","python":platform.python_version()}]
            owned=getattr(context.get("browser"),"_launched_process",None)
            if owned is not None and isinstance(getattr(owned,"pid",None),int):
                processes.append({"pid":owned.pid,"name":"Owned Microsoft Edge launcher","running":owned.poll() is None})
            return {"processes":processes,"scope":"current agent and explicitly launched owned Edge only"}
        if name=="code_runner":
            runner=CodeRunner(policy,context["session_dir"],{"tool_timeout":config_value(config,"tool_timeout",10),"max_output_chars":config_value(config,"max_output_chars",12000)})
            return await runner.run_async(args,context.get("approved_hash"),process_registry=context.get("process_registry"))
        if name=="ocr.image":
            path=policy.resolve(args["path"],True)
            if path.suffix.lower() not in {".png",".jpg",".jpeg",".webp",".bmp"}: raise ValueError("Expected supported image")
            if not path.is_file() or path.stat().st_size>min(20971520,config_value(config,"max_attachment_bytes",20971520)): raise PolicyError("Image exceeds the approved attachment limit")
            with path.open("rb") as stream: header=stream.read(16)
            if not (header.startswith((b"\x89PNG\r\n\x1a\n",b"\xff\xd8\xff",b"BM")) or header.startswith(b"RIFF") and header[8:12]==b"WEBP"): raise ValueError("File header is not a supported image")
            if context.get("browser") is not None and callable(getattr(context["browser"],"attach_files",None)):
                pending=context.setdefault("pending_image_attachments",[])
                if str(path) not in pending: pending.append(str(path))
                return {"status":"pending_attachment_for_analysis","path":str(path),"followup":"Attach this approved image on the next Copilot submission, then analyze visible text. Upload and OCR are not yet observed."}
            return {"status":"unavailable","path":str(path),"reason":"No local OCR engine is configured. Attach this approved image to Copilot for supported image analysis."}
        if name.startswith("created."):
            if not config_value(config,"created_sync_enabled",False):
                return {"status":"disabled","files":[],"reason":"Created monitoring is disabled until the user explicitly configures its path and enables it."}
            directory=config_value(config,"created_dir")
            if not directory: return {"status":"missing_directory","files":[]}
            watcher=CreatedSync(directory,poll_interval=config_value(config,"sync_poll_interval",.5))
            if name=="created.snapshot":
                baseline=watcher.baseline(); token=uuid.uuid4().hex
                snapshots=context.setdefault("created_snapshots",{})
                if len(snapshots)>=50: raise PolicyError("Created snapshot limit reached")
                snapshots[token]=baseline
                return {"status":"captured" if watcher.directory.is_dir() else "missing_directory","baseline_id":token,"file_count":len(baseline)}
            token=args.get("baseline_id")
            baseline=context.get("created_snapshots",{}).get(token) if token else context.get("created_baseline")
            if baseline is None: raise PolicyError("A baseline recorded before file creation is required")
            return await watcher.poll(baseline,pattern=args.get("pattern","*"),expected_names=args.get("expected_names"),timeout=config_value(config,"sync_timeout",120))
        if name.startswith("browser."):
            browser=context.get("browser")
            page=getattr(browser,"tool_page",None)
            if name == 'browser.info' and (page is None or page.is_closed()):
                return {'status': 'no_owned_page', 'owned_page_available': False,
                        'side_effects_uncertain': False, 'next_action': 'browser.open'}
            if name == "browser.open" and (page is None or page.is_closed()):
                # A login flow can replace or close an owned tab. The approved
                # URL is preflighted before opening another tab in this profile.
                website_policy(config, [*config_value(config,"allowed_domains",[]), *context.get("approved_domains",[])]).resolve(args["url"])
                page = await browser.new_tool_page()
                browser.tool_page = page
            if page is None or page.is_closed(): raise PolicyError("Owned tool page is unavailable")
            if page is getattr(browser,"page",None) or page is getattr(browser,"chat_page",None): raise PolicyError("Copilot control page cannot be a tool page")
            urls=website_policy(config, [*config_value(config,"allowed_domains",[]), *context.get("approved_domains",[])])
            # Request-time enforcement also blocks redirects, subresources and
            # fetches to unapproved destinations before network access occurs.
            async def guard(route):
                try: urls.resolve(route.request.url)
                except (PolicyError,ValueError): await route.abort("blockedbyclient")
                else: await route.fallback()
            previous=getattr(browser,"_tool_policy_route",None)
            if previous is not None: await page.unroute("**/*",previous)
            await page.route("**/*",guard)
            browser._tool_policy_route=guard
            if name=="browser.open":
                url=urls.resolve(args["url"])
                for domain in args.get('allowed_domains',[]):
                    urls.resolve('https://' + domain)
                    if domain not in browser.tool_domains:
                        browser.authorize_tool_domain(domain)
                if not fast_mode(config):
                    await clear_navigation_state(browser)
                await page.goto(url,wait_until="domcontentloaded",timeout=20000)
                urls.resolve(page.url)
                from .reconciliation import _origin
                final_origin = _origin(page.url)
                bindings=context.get('site_knowledge_bindings',{})
                same_bound_origin=final_origin in bindings
                for field in ('task_id', 'customer_key'):
                    context.pop(field, None)
                if not same_bound_origin:
                    for field in ('tenant_id', 'site_namespace_id'):
                        context.pop(field, None)
                    bindings.clear()
                for field in ('web_document_tickets', 'document_catalogues'):
                    context.get(field, {}).clear()
                return {"url":page.url,"title":await page.title(),"tab_id":get_primary_navigation_tab_id(context),
                        "javascript_enabled":True,"shared_verified_profile":True}
            if page.url!="about:blank": urls.resolve(page.url)
            if name in {"browser.back","browser.forward"}:
                session=await page.context.new_cdp_session(page)
                try: history=await session.send("Page.getNavigationHistory")
                finally: await session.detach()
                index=history["currentIndex"]+(-1 if name.endswith("back") else 1)
                if not 0<=index<len(history["entries"]): return {"status":"no_history"}
                urls.resolve(history["entries"][index]["url"])
                await (page.go_back if name.endswith("back") else page.go_forward)(wait_until="domcontentloaded",timeout=20000)
                urls.resolve(page.url)
                return {"url":page.url}
            if name=="browser.info": return {"url":page.url,"title":await page.title()}
            scope=page
            frame_selector=args.get('frame_selector')
            if frame_selector:
                iframe=page.locator(frame_selector)
                if await iframe.count()!=1 or (await iframe.evaluate('(n)=>n.tagName')).upper()!='IFRAME':
                    raise ValueError('frame_selector must identify exactly one iframe')
                src=await iframe.get_attribute('src')
                if src:
                    from urllib.parse import urljoin
                    urls.resolve(urljoin(page.url,src))
                scope=page.frame_locator(frame_selector)
            if name=="browser.read":
                text = await scope.locator("body").inner_text(timeout=10000)
                return {"text": text if fast_mode(config) or config_value(config, 'customer_data_work', True) is True else text[:10000]}
            if name=="browser.structure":
                return {"controls":await scope.locator("body").evaluate(STRUCTURE_SCRIPT)}
            if name=='browser.frames':
                return {'frames':await page.evaluate("""() => [...document.querySelectorAll('iframe')].slice(0,30).map((n,i)=>{let src=null;try{const u=new URL(n.src,location.href);src=u.protocol+'//'+u.host+u.pathname;}catch(_){}let parts=[];for(let node=n;node&&node.nodeType===1;node=node.parentElement){const tag=node.tagName.toLowerCase();const siblings=node.parentElement?[...node.parentElement.children].filter(s=>s.tagName===node.tagName):[node];parts.unshift(tag+':nth-of-type('+(siblings.indexOf(node)+1)+')');}return {selector:parts.join(' > '),id:n.id||null,name:n.name||null,src};})""")}
            if name=='browser.wait':
                await scope.locator(args['selector']).wait_for(state=args.get('state','visible'),timeout=args.get('timeout_ms',10000))
                return {'status':'observed','selector':args['selector'],'state':args.get('state','visible')}
            if name in {'browser.select','browser.press'}:
                locator=scope.locator(args['selector'])
                if await locator.count()!=1: raise ValueError('Selector must identify exactly one control')
                if (await locator.get_attribute('type') or '').lower()=='password': raise PolicyError('Password controls are unavailable')
                if name=='browser.select': await locator.select_option(value=args['value'],timeout=10000)
                else: await locator.press(args['key'],timeout=10000)
                if page.url!='about:blank': urls.resolve(page.url)
                return {'status':'performed','url':page.url}
            if name in {"browser.click","browser.fill"}:
                locator=scope.locator(args["selector"])
                if await locator.count()!=1: raise ValueError("Selector must identify exactly one element")
                if name=="browser.fill":
                    if (await locator.get_attribute("type") or "").lower()=="password": raise PolicyError("Password input is forbidden")
                    await locator.fill(args["text"],timeout=5000)
                else: await locator.click(timeout=5000)
                if page.url!="about:blank": urls.resolve(page.url)
                return {"status":"performed","url":page.url}
            if name=="browser.scroll": await page.evaluate("pixels=>window.scrollBy(0,pixels)",args["pixels"]); return {"status":"performed"}
            if name in {"browser.errors","browser.downloads"}:
                key="tool_errors" if name.endswith("errors") else "tool_downloads"
                values=getattr(browser,key,None)
                return {"status":"observed" if values is not None else "unavailable","events":list(values or [])[-20:]}
        raise ValueError("Unknown capability")


def definitions(): return ToolRegistry().definitions()


async def execute(name,args,context): return await ToolRegistry().execute(name,args,context)
