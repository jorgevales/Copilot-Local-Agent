"""Interactive setup, visible browser and continuous policy-controlled conversation."""
from __future__ import annotations
import argparse
import asyncio
from dataclasses import replace
import json
import os
import socket
import sys
from pathlib import Path
import uuid
from .browser import (BrowserAdapter, BrowserUIError, CaptureTimeoutError,
                      ExistingEdgeUnavailable,
                      ModelUnavailableError, SubmissionAmbiguousError,
                      SubmissionNotSentError, model_rank)
from .config import Config
from .knowledge_health import check_knowledge_health
from .orchestrator import Orchestrator
from .state import SessionState, latest_committed_request_id, recoverable_capture_request_id
from .tools import ToolRegistry
from .feedback import Feedback
from .file_picker import select_files
from .attachments import MAX_USER_FILES
from .diagnostics import DiagnosticReports
from .protocol import ProtocolError
from .policy import PolicyError, mapped_s_drive_root
from .storage import default_local_storage, machine_key, read_user_settings, save_user_settings, validate_user_storage_directory
from . import reused_browser as edge
from .setup_resources import choose_edge
from .temp_storage import configure_temp_directory

_TERMINAL = Feedback()
_UI_ASK = None
_UI_APPROVAL_DECIDER = None
_UI_EVENT_SINK = None
_UI_CANCEL_EVENT = None
_UI_STEERING_POLL = None
_UI_STEERING_COMPLETE = None
_UI_ACTIVE_RUN_ID = None
_UI_TAKE_ATTACHMENTS = None
_UI_UPLOAD_ROOT = None
_UI_PERMISSION_CONTEXT = None
_TERMINAL_INPUT = None

def system(message):
    _TERMINAL.emit('System', message)


def error(message):
    _TERMINAL.emit('Error', message)


async def ask(prompt: str) -> str:
    if _UI_ASK is not None:
        return await _UI_ASK(_TERMINAL.prompt('User', prompt))
    if _TERMINAL_INPUT is not None:
        return await _TERMINAL_INPUT.ask(_TERMINAL.prompt('User', prompt))
    return await asyncio.to_thread(input, _TERMINAL.prompt('User', prompt))


async def _terminal_approval_decider(_preview):
    is_package = _preview.get('approval_scope_type') == 'automation_package'
    options = ('Choose 1 = Deny, 2 = Allow once, 3 = Allow this displayed plan, '
               '4 = Allow freshly inspected packages for this agent session [1/2/3/4]: '
               if is_package else
               'Choose 1 = Deny, 2 = Allow this exact execution once, 3 = Allow this exact displayed plan [1/2/3]: ')
    prompt = _TERMINAL.prompt('User', options)
    return await _TERMINAL_INPUT.ask_approval(prompt)


def _record_bug_fix(state, config, exc, operation, stage, report_index=None):
    """Record a failure without interrupting the current user turn."""
    try:
        generated = DiagnosticReports(config.storage_dir, state.session_id,
                                      os.environ.get('COPILOT_AGENT_EXECUTION_MODE', 'live')).create(
            exc, operation=operation, stage=stage, events=_recent_events(state))
    except Exception as report_error:
        try:
            state.event('bug_report_write_failed', error=str(report_error))
            state.save()
        except Exception:
            pass
        return None
    record = {'report_id': generated['internal']['report_id'],
              'internal_path': str(generated['internal_path']),
              'external_path': str(generated['external_path']),
              'candidate_files': generated['internal']['candidate_files']}
    if report_index is not None:
        report_index.append(record)
    try:
        state.data['bug_fix'] = True
        state.data.setdefault('bug_report_ids', []).append(record['report_id'])
        state.event('bug_fix_report_created', report_id=record['report_id'],
                    category=generated['internal']['error_category'])
        state.save()
    except Exception:
        pass
    return record


def _record_turn_error(state, exc):
    try:
        state.fail_active_turn(type(exc).__name__)
    except Exception:
        pass
    try:
        state.event('turn_error', error=str(exc))
    except Exception:
        pass


def _show_bug_handoff(reports):
    if not reports:
        return
    system(f"Bug reports saved: {len(reports)}. Internal reports: {Path(reports[0]['internal_path']).parent}")
    system('Copilot handoff: attach the internal report(s), 08_GRAPHIFY_FINDINGS.md, and the recommended source/test files; keep total attachments within 20. See Copilot handoff/full-discovery/README.md.')
    system('Internal reports are for authorized Copilot only. Use sanitized reports for any external review.')


def _actionable(exc):
    return isinstance(exc, (BrowserUIError, ProtocolError, OSError)) or (
        isinstance(exc, RuntimeError) and not isinstance(exc, PolicyError)
        and str(exc) not in {'Previous submission has uncertain delivery; reconcile first',
                             'Reconcile uncertain submissions or state-changing calls before starting a new session.'})


def _recent_events(state):
    try:
        raw = (state.directory / 'events.jsonl').read_bytes()[-65536:]
        records = []
        for line in raw.splitlines()[-20:]:
            try:
                value = json.loads(line)
                records.append({'event': value.get('event'), 'timestamp': value.get('timestamp')})
            except (ValueError, TypeError):
                continue
        return records
    except OSError:
        return []


async def _choose_existing_endpoint(endpoints, prompt):
    """Ask whether to reuse one of the verified Edge sessions or launch a new one."""
    if not endpoints:
        return None
    while True:
        options = [f'{index}. Reuse the existing Edge session on port {item["port"]}'
                   for index, item in enumerate(endpoints, 1)]
        new_choice = len(endpoints) + 1
        options.append(f'{new_choice}. Start a new isolated Edge session')
        options.append('0. Cancel startup')
        selected = (await prompt(
            'Verified existing Edge sessions are available:\n'
            + '\n'.join(options)
            + f'\nChoose [1-{new_choice}, default 1]: '
        )).strip().lower()
        if not selected:
            return endpoints[0]
        if selected in {'0', 'c', 'cancel', 'q', 'quit', 'exit'}:
            raise ValueError('Startup canceled at the Edge session selection; no browser was launched.')
        if selected in {'new', 'n'}:
            return None
        if selected.isdecimal():
            choice = int(selected)
            if 1 <= choice <= len(endpoints):
                return endpoints[choice - 1]
            if choice == new_choice:
                return None
        system(f'Choose a number from 1 to {new_choice}, or 0 to cancel startup.')


async def choose_browser_endpoint(config, args, settings, *, interactive=False,
                                  prompt=ask, force_new=False):
    """Select a verified Edge session or a free loopback port for a new one.

    Changes the in-memory config/settings only. The caller persists settings before
    launch. The browser adapter still repeats endpoint/profile validation and
    guards the profile with its controller mutex, including startup races.
    """
    if not hasattr(config, '_new_session_profile_dir'):
        config._new_session_profile_dir = config.profile_dir
    if force_new:
        config.attach_existing = False
    if config.attach_existing and not force_new:
        return config
    debug_ports = settings.get('debug_ports', {})
    if not isinstance(debug_ports, dict):
        raise ValueError('Per-machine debug_ports settings must be an object')
    key = machine_key()
    remembered = debug_ports.get(key)
    candidates = []
    # Discover ownership even for an operator-specified port. Skipping process
    # discovery there loses the real Edge profile and makes safe attachment fail.
    discovered = await asyncio.to_thread(edge.discover_edge_debugging_endpoints)
    discovered_by_port = {item['port']: item for item in discovered}
    explicit_port = getattr(args, 'port', None)
    if not explicit_port:
        # Prefer the conventional local agent endpoint when available, while
        # still attaching only after exact Edge/profile ownership validation.
        candidates.append(9222)
        for item in discovered:
            if item['port'] not in candidates:
                candidates.append(item['port'])
        if type(remembered) is int and 1024 <= remembered <= 65535 and remembered not in candidates:
            candidates.append(remembered)
    if config.debug_port not in candidates:
        candidates.append(config.debug_port)
    if explicit_port:
        # An operator-specified endpoint is a strict target. Never reinterpret
        # a stale/mismatched dedicated port as permission to launch elsewhere.
        candidates = [explicit_port]
    selected = None
    verified = []
    endpoints = [edge.cdp_endpoint(port) for port in candidates]
    payloads = await asyncio.gather(*(
        asyncio.to_thread(edge.get_cdp_version, endpoint) for endpoint in endpoints))
    if not force_new:
        for port, endpoint, payload in zip(candidates, endpoints, payloads):
            if not payload:
                continue
            try:
                edge.validate_endpoint(endpoint, payload)
                discovered_item = discovered_by_port.get(port)
                if discovered_item is None and explicit_port == port:
                    # WMI/CIM process enumeration can be unavailable to a
                    # standard user. For the exact port they supplied, prove
                    # the listener directly from its owning Windows process.
                    profile = await asyncio.to_thread(edge.validate_edge_listener, port)
                    discovered_item = {'port': port, 'profile': profile}
                if explicit_port == port and getattr(config, '_profile_explicit', False):
                    expected_profile = getattr(config, '_configured_profile_dir', None) or config.profile_dir
                    actual_profile = discovered_item.get('profile') if discovered_item else None
                    if actual_profile is None:
                        actual_profile = await asyncio.to_thread(edge.validate_edge_listener, port)
                        discovered_item = {'port': port, 'profile': actual_profile}
                    if actual_profile is None or Path(actual_profile).resolve() != Path(expected_profile).resolve():
                        raise edge.EndpointError('The explicit Edge port belongs to a different or unknown profile')
                if discovered_item is not None:
                    await asyncio.to_thread(edge.validate_edge_listener, port, discovered_item['profile'])
                else:
                    await asyncio.to_thread(edge.validate_profile_ownership, port, config.profile_dir)
            except (edge.EndpointError, OSError, ValueError):
                # Unknown or mismatched listeners are never attached.
                continue
            verified.append({'port': port, 'profile': discovered_item.get('profile') if discovered_item else None,
                             'discovered': discovered_item is not None})

    selected_existing = None
    if verified:
        if explicit_port:
            selected_existing = verified[0]
        elif interactive:
            selected_existing = await _choose_existing_endpoint(verified, prompt)
        else:
            selected_existing = verified[0]
    if selected_existing is not None:
        selected = selected_existing['port']
        config.attach_existing = True
        config._new_edge_session = False
        if selected_existing['discovered']:
            config._discovered_edge_endpoint = True
            if selected_existing['profile'] is not None:
                config.profile_dir = selected_existing['profile']
        if interactive and not explicit_port:
            config._user_selected_existing = True
        system('Reusing a verified running Edge session on local port ' + str(selected) + '.')
    if selected is None:
        if explicit_port:
            explicit_payload = payloads[0] if payloads else None
            if explicit_payload:
                raise ValueError(f'Explicit Edge debugging port {explicit_port} is occupied by an unverified or mismatched listener.')
            if getattr(config, '_profile_explicit', False):
                raise ValueError(f'Cannot verify the explicitly requested Edge profile on port {explicit_port}.')
            # A free explicit port may be used for a new owned browser, but it
            # must remain exactly the requested port.
            try:
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', explicit_port))
            except OSError as exc:
                raise ValueError(f'Explicit Edge debugging port {explicit_port} is unavailable.') from exc
            selected = explicit_port
    if selected is None:
        for port in candidates:
            try:
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            selected = port
            break
    if selected is None:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            selected = probe.getsockname()[1]
    config.debug_port = selected
    settings['debug_ports'] = dict(debug_ports, **{key: selected})
    if not config.attach_existing:
        config._new_edge_session = True
        config._user_selected_existing = False
        if hasattr(config, '_discovered_edge_endpoint'):
            delattr(config, '_discovered_edge_endpoint')
        profile = Path(config._new_session_profile_dir).expanduser().resolve()
        profile_key = os.path.normcase(str(profile))
        known_busy = any(item.get('profile') is not None
                         and os.path.normcase(str(Path(item['profile']).resolve())) == profile_key
                         for item in discovered)
        if known_busy or await asyncio.to_thread(edge.profile_in_use, profile):
            profile = profile.with_name(profile.name + '-session-' + uuid.uuid4().hex[:12])
            system('The saved Edge profile is already open. Using a separate persistent profile for the new Edge session; sign in there if prompted.')
        config.profile_dir = profile
        system('Using an available local debugging port: ' + str(selected))
    return config


async def start_new_session(config, previous, model_label, registry=None):
    """Archive the old conversation and initialize an independent owned UI chat."""
    old = previous.state
    if old.data['pending_submission'] or any(call['status'] == 'uncertain' and call.get('state_changing', True)
                                             for call in old.data['calls'].values()):
        raise RuntimeError('Reconcile uncertain submissions or state-changing calls before starting a new session.')
    old.event('new_session_requested')
    owned_process = getattr(previous.browser, '_launched_process', None)
    await previous.close(preserve_browser_process=True)
    fresh_config = replace(config, attach_existing=True, model=model_label)
    for name in ('_ui_upload_root', '_automation_test_mode', '_local_knowledge_test_mode',
                 '_proof_exact_edge_endpoint', '_s_storage_verified',
                 '_profile_explicit', '_configured_profile_dir', '_auto_s_drive_root',
                 '_auto_local_drive_root'):
        if hasattr(config, name):
            setattr(fresh_config, name, getattr(config, name))
    fresh_config._local_navigation_confirmed = bool(getattr(config, '_local_navigation_confirmed', False))
    directory = config.runtime_dir / 'sessions' / uuid.uuid4().hex
    state = SessionState(directory)
    browser = BrowserAdapter(fresh_config)
    browser._launched_process = owned_process
    engine = None
    try:
        if getattr(fresh_config, '_automation_test_mode', False):
            fresh_config._knowledge_capability = {
                'available': False,
                'statement': 'Persistent knowledge is disabled in isolated proof mode; package execution uses its own exact review.'}
        else:
            fresh_config._knowledge_capability = await asyncio.to_thread(check_knowledge_health, {'config': fresh_config})
        state.data['knowledge_capability'] = fresh_config._knowledge_capability
        state.data['visible'] = True
        state.save()
        await browser.start()
        engine = Orchestrator(fresh_config, browser, registry or ToolRegistry(), state,
                              approval_decider=_UI_APPROVAL_DECIDER or (_terminal_approval_decider if _UI_ASK is None else None), display=_TERMINAL.sink,
                              event_sink=_UI_EVENT_SINK, cancel_event=_UI_CANCEL_EVENT,
                              steering_poll=_UI_STEERING_POLL,
                              steering_complete=_UI_STEERING_COMPLETE)
        engine.feedback.color=_TERMINAL.color
        globals()['_UI_PERMISSION_CONTEXT']=engine.base_context
        # Keep model discovery and initialization on the one owned Copilot tab.
        await browser.discover_models()
        await browser.select_model(model_label)
        await engine.prepare_initialization()
        state.event('model_selected', label=model_label, visible=True)
        await engine.initialize()
        if hasattr(browser, 'verify_interaction_ready'):
            await browser.verify_interaction_ready(model_label)
        if _UI_EVENT_SINK is not None:
            _UI_EVENT_SINK('session', {'title': 'Copilot session ' + state.session_id[:8]})
            _UI_EVENT_SINK('model', {'name': model_label, 'verified': True})
        return engine
    except Exception as exc:
        state.event('new_session_setup_failed', error=str(exc))
        state.data['status'] = 'blocked'
        state.save()
        await browser.close()
        raise RuntimeError('New session setup stopped; previous records and new diagnostics are retained in the configured local storage.') from exc


def read_runtime_settings(config):
    if os.environ.get('COPILOT_AGENT_EXECUTION_MODE') == 'testing':
        return read_user_settings(config.storage_dir, testing=True)
    return read_user_settings(config.storage_dir)


def persist_runtime_settings(config, settings):
    if os.environ.get('COPILOT_AGENT_EXECUTION_MODE') == 'testing':
        return save_user_settings(config.storage_dir, settings, testing=True)
    return save_user_settings(config.storage_dir, settings)


def configure_isolated_test_workspace(config, requested_path, *, resume_session=None):
    """Enable the one-shot C: proof harness without weakening production S: policy."""
    proof_parent = (Path(config.root) / 'runtime' / 'proof-runs').resolve()
    target = Path(requested_path).expanduser().resolve()
    if (target.drive.upper() != 'C:' or not target.is_relative_to(proof_parent)
            or target == proof_parent):
        raise ValueError('Isolated proof storage must be a new C: child of this project runtime/proof-runs folder.')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        resume_path = Path(resume_session).expanduser().resolve() if resume_session is not None else None
        sessions_root = (target / 'runtime' / 'sessions').resolve()
        if (resume_path is None or not resume_path.is_relative_to(sessions_root)
                or not (resume_path / 'session.json').is_file()):
            raise ValueError('Existing isolated proof storage can only be used to resume a session inside that workspace.')
    config.select_storage(target)
    config.knowledge_directory = target
    config._automation_test_mode = True
    config._s_storage_verified = False
    config.allowed_roots = [str(target)]
    return target


def configure_local_knowledge_test(config, requested_path):
    """Enable an explicitly selected local C: store without changing S: defaults."""
    local_app_data = os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        raise ValueError('A local AppData root is required for the C: knowledge test store.')
    allowed_parent = (Path(local_app_data) / 'CopilotLocalAgent' / 'live-navigation-tests').resolve()
    target = Path(requested_path).expanduser().resolve()
    if target.drive.upper() != 'C:' or target.parent != allowed_parent:
        raise ValueError('The local knowledge test store must be a direct child of LocalAppData\\CopilotLocalAgent\\live-navigation-tests.')
    if target.exists() and any(target.iterdir()):
        raise ValueError('The local knowledge test store must be empty; existing files are preserved.')
    config.select_storage(target)
    config.knowledge_directory = target / 'Discoveries knowledge'
    config._local_knowledge_test_mode = True
    config._s_storage_verified = False
    config.allowed_roots = [str(target)]
    return target


async def run(args):
    global _TERMINAL_INPUT, _UI_STEERING_POLL, _UI_TAKE_ATTACHMENTS
    terminal_input = None
    test_workspace = getattr(args, 'isolated_test_workspace', None)
    local_knowledge_test = getattr(args, 'local_knowledge_test_directory', None)
    storage_override = test_workspace or local_knowledge_test
    config = Config.load(args.config, storage_override=storage_override)
    if test_workspace is not None:
        test_workspace = configure_isolated_test_workspace(config, test_workspace, resume_session=args.resume)
        system('Isolated local proof mode: all agent storage and file roots are confined to ' + str(test_workspace))
    elif local_knowledge_test is not None:
        local_knowledge_test = configure_local_knowledge_test(config, local_knowledge_test)
        system('Explicit local knowledge test mode: this run uses only ' + str(local_knowledge_test))
    else:
        from .storage import discoveries_storage
        canonical_storage = discoveries_storage(config.root)
        if config.storage_dir.resolve() != canonical_storage.resolve():
            system('Configured storage is not the canonical S: project sibling; redirecting agent-owned storage to ' + str(canonical_storage))
            config.select_storage(canonical_storage)
        config.knowledge_directory = canonical_storage
        s_root = mapped_s_drive_root().resolve()
        config._s_storage_verified = True
        kept_roots = [root for root in config.allowed_roots
                      if Path(root).resolve() == s_root or s_root in Path(root).resolve().parents]
        if len(kept_roots) != len(config.allowed_roots):
            system('Removed configured file roots outside the live S: share; C: and unrelated locations are not agent write targets.')
        if str(s_root) not in kept_roots:
            kept_roots.append(str(s_root))
        config.allowed_roots = kept_roots
    if _UI_UPLOAD_ROOT is not None:
        config._ui_upload_root = Path(_UI_UPLOAD_ROOT).resolve()
    if config.visible is not True:
        raise ValueError('Copilot runs require a visible Microsoft Edge window; invisible operation is disabled.')
    if config.storage_dir is None:
        config.select_storage(default_local_storage())
    # Probe separate directories under the verified S: storage before settings,
    # Edge, Playwright, or uploads initialize; retry paths stay on that share.
    temp_directory = configure_temp_directory(config.storage_dir)
    settings = read_runtime_settings(config)
    if args.config is None and isinstance(settings.get('config'), dict):
        personal = settings['config']
        allowed_keys = {'allowed_domains', 'allowed_roots', 'model', 'response_timeout', 'response_max_duration', 'max_corrections', 'sync_timeout', 'max_delivery_retries', 'download_timeout', 'copilot_download_hosts'}
        for key in allowed_keys & personal.keys():
            setattr(config, key, personal[key])
        # Migrate the former two-attempt personal default to the production
        # response-recovery contract. Explicit operator config files may still
        # choose a lower value when deliberately required.
        config.max_corrections = 12
    # Remembered settings may predate the S:-only policy. Reapply it after
    # loading them so persisted C:/OneDrive roots cannot silently return.
    if getattr(config, '_local_knowledge_test_mode', False):
        # Runtime settings cannot broaden the one explicitly selected C: test root.
        config.allowed_roots = [str(local_knowledge_test.resolve())]
    elif not getattr(config, '_automation_test_mode', False):
        s_root = mapped_s_drive_root().resolve()
        config.allowed_roots = [str(Path(root).resolve()) for root in config.allowed_roots
                                if Path(root).resolve() == s_root or s_root in Path(root).resolve().parents]
        if str(s_root) not in config.allowed_roots:
            config.allowed_roots.append(str(s_root))
    if args.attach_existing:
        config.attach_existing = True
    if args.port:
        config.debug_port = args.port
    if args.profile:
        config.profile_dir = args.profile
        config._profile_explicit = True
    if args.model:
        config.model = args.model
    elif not isinstance(config.model, str) or not config.model.strip():
        # Migrate older per-user settings that persisted the former empty
        # model value so startup consistently preselects the product default.
        config.model = 'GPT-6 Sol'
    config.validate()
    if args.attach_existing and args.port and args.profile:
        # Bind the live-proof guard to the exact operator-supplied endpoint and
        # normalized profile before endpoint selection can return early.
        config._proof_exact_edge_endpoint = (args.port, str(config.profile_dir.resolve()))
    validate_user_storage_directory(config.storage_dir)
    if not config.profile_dir.is_relative_to(config.storage_dir) and not (config.attach_existing and config.root.drive.upper() != 'S:'):
        raise ValueError('The persistent Edge profile must be inside the configured user storage.')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    system('Verified temporary workspace: ' + str(temp_directory))
    await choose_edge(config, settings, ask, system, force=getattr(args, 'setup_only', False))
    settings['python_executable'] = sys.executable
    settings['config'] = {key: value for key, value in config.as_dict().items() if key in {
        'allowed_domains', 'allowed_roots', 'model', 'response_timeout', 'response_max_duration', 'max_corrections',
        'sync_timeout', 'max_delivery_retries', 'download_timeout', 'copilot_download_hosts'}}
    settings['config']['allowed_roots'] = [str(Path(path).relative_to(config.storage_dir))
                                          if Path(path).is_relative_to(config.storage_dir) else path
                                          for path in config.allowed_roots
                                          if path not in {getattr(config, '_auto_s_drive_root', None),
                                                          getattr(config, '_auto_local_drive_root', None)}]
    persist_runtime_settings(config, settings)
    if getattr(args, 'setup_only', False):
        system(('Setup verified. Isolated proof storage: ' if getattr(config, '_automation_test_mode', False)
                else 'Setup verified. S: Discoveries storage: ') + str(config.storage_dir))
        system('Python resource setup verified. Setup.cmd creates the project virtual environment and installs pinned dependencies before this storage step.')
        return
    await choose_browser_endpoint(
        config, args, settings,
        interactive=not bool(args.resume or getattr(args, 'isolated_test_workspace', None)
                              or getattr(args, 'local_knowledge_test_directory', None)),
        prompt=ask)
    persist_runtime_settings(config, settings)
    for root in config.allowed_roots:
        if root not in {getattr(config, '_auto_s_drive_root', None),
                        getattr(config, '_auto_local_drive_root', None)}:
            Path(root).mkdir(parents=True, exist_ok=True)
    directory = args.resume or config.runtime_dir / 'sessions' / uuid.uuid4().hex
    if args.resume and not Path(args.resume).resolve().is_relative_to(config.runtime_dir.resolve()):
        raise ValueError('Resume sessions must be inside your selected per-user runtime directory.')
    state = SessionState(directory, resume=bool(args.resume))
    browser = BrowserAdapter(config)
    orchestrator = None
    bug_reports = []
    system('Copilot Local Agent — reasoning through Microsoft 365 Copilot web UI')
    from .storage import discoveries_storage_paths
    storage_paths = ({'s_path': str(config.knowledge_directory), 'unc_path': str(config.knowledge_directory)}
                     if getattr(config, '_local_knowledge_test_mode', False)
                     else {'s_path': str(config.storage_dir), 'unc_path': str(config.storage_dir)}
                     if getattr(config, '_automation_test_mode', False)
                     else discoveries_storage_paths(config.root))
    system(('Local test knowledge target: ' if getattr(config, '_local_knowledge_test_mode', False)
            else 'Isolated proof storage target: ' if getattr(config, '_automation_test_mode', False)
            else 'Agent storage target for every save: ') + storage_paths['s_path'] + ' (resolved filesystem path: ' + storage_paths['unc_path'] + ').')
    if getattr(config, '_local_knowledge_test_mode', False):
        system('Direct reads and new-file/folder creation in the explicit local test store are granted for this run; deletion or overwrite requires separate confirmation.')
    elif not getattr(config, '_automation_test_mode', False):
        system('The fast session option permits ordinary file reads and edits without individual approval; file deletion remains blocked.')
    if config.customer_data_work:
        system('Customer and company data: local discovery, reads and requested business artifacts are enabled for every authorized customer.')
    system('Browser: Visible. Non-visible Copilot operation has not passed acceptance and is unavailable.')
    system('Permitted file roots: ' + ', '.join(Path(root).name for root in config.allowed_roots))
    system('Agent-owned writes are restricted to the explicit local C: test store.' if getattr(config, '_local_knowledge_test_mode', False)
           else 'Agent-owned writes are restricted to the isolated proof workspace.' if getattr(config, '_automation_test_mode', False)
           else 'Runtime and saved website knowledge use the shared Discoveries store. The fast session option permits ordinary file reads and edits elsewhere, subject to OS access.')
    system('The fast session option permits navigation across websites without a domain allowlist. Sign in manually when needed.')
    system('One fast session option skips package quality review and individual plan approvals. Stop remains available.')
    system('Useful Findings are saved on any valid turn; their file is attached every ten messages.')
    system('File delivery: actual Copilot UI downloads and verified ZIP extraction; no Created-folder monitoring.')
    isolated_proof = getattr(config, '_automation_test_mode', False)
    from .session_setup import guided_discovery
    from .session_mode import START_PROMPT, configure_session
    confirmed = False if isolated_proof else bool(args.yes_setup) or (await ask(START_PROMPT)).strip().lower() in {'', 'y', 'yes'}
    configure_session(config, confirmed)
    state.data['visible'] = True
    if not confirmed and not isolated_proof:
        state.data['status'] = 'cancelled'
        state.save()
        return
    if isolated_proof:
        config._knowledge_capability = {'available': False,
                                        'statement': 'Persistent knowledge is disabled in isolated proof mode; package execution uses its own exact review.'}
    else:
        config._knowledge_capability = await asyncio.to_thread(check_knowledge_health, {'config': config})
    state.data['knowledge_capability'] = config._knowledge_capability
    state.event('knowledge_startup_capability', **config._knowledge_capability)
    state.save()
    system(config._knowledge_capability['statement'])
    try:
        if state.data['pending_submission']:
            system('Previous delivery is uncertain. Inspect the previous chat before reconciling.')
            answer = (await ask('Was that exact pending request submitted [sent/not-sent/exit]? ')).strip()
            if answer not in {'sent', 'not-sent'}:
                return
            state.reconcile_submission(answer == 'sent')
        resume_existing = bool(args.resume and state.message_count > 0)
        recovery_request_id = recoverable_capture_request_id(state) if resume_existing else None
        resume_capture = bool(recovery_request_id)
        if resume_capture and state.data.get('status') != 'capture_failed':
            state.data['status'] = 'capture_failed'
            state.save()
        resume_request_id = latest_committed_request_id(state) if resume_existing else None
        try:
            await browser.start(resume_request_id=resume_request_id)
        except ExistingEdgeUnavailable:
            system('The selected existing Edge session could not be verified at attachment. Starting a new isolated Edge session.')
            config.attach_existing = False
            config._user_selected_existing = False
            config.profile_dir = config._new_session_profile_dir
            if hasattr(config, '_discovered_edge_endpoint'):
                delattr(config, '_discovered_edge_endpoint')
            await choose_browser_endpoint(config, args, settings, force_new=True)
            persist_runtime_settings(config, settings)
            browser = BrowserAdapter(config)
            await browser.start(resume_request_id=resume_request_id)
        if not isolated_proof and (not args.yes_setup or _UI_ASK is not None or getattr(args, 'discover_first', False)):
            config._guided_knowledge_paths = await guided_discovery(
                config, browser, state.directory, ask, system, _UI_CANCEL_EVENT)
        if _UI_ASK is None:
            from .terminal_input import TerminalInputBroker
            terminal_input = TerminalInputBroker()
            _TERMINAL_INPUT = terminal_input
            _UI_STEERING_POLL = terminal_input.poll_steering
            _UI_TAKE_ATTACHMENTS = terminal_input.take_attachments
        orchestrator = Orchestrator(config, browser, ToolRegistry(), state,
                                    approval_decider=_UI_APPROVAL_DECIDER or (_terminal_approval_decider if _UI_ASK is None else None), display=_TERMINAL.sink,
                                    event_sink=_UI_EVENT_SINK, cancel_event=_UI_CANCEL_EVENT,
                                    steering_poll=_UI_STEERING_POLL,
                                    steering_complete=_UI_STEERING_COMPLETE)
        orchestrator.initialized = resume_existing
        orchestrator.feedback.color=_TERMINAL.color
        globals()['_UI_PERMISSION_CONTEXT']=orchestrator.base_context
        # Use the single owned Copilot tab throughout startup. Opening and then
        # closing an auxiliary Copilot tab can terminate an attached Edge route.
        models = await browser.discover_models()
        browser.models = models
        ranked = model_rank(models)
        enabled = [m for m in ranked if m.get('enabled', True)]
        if not enabled:
            raise RuntimeError('No enabled Copilot models were discovered')
        system('Models actually discovered in this account:')
        for i, model in enumerate(models, 1):
            system(f"{i}. {model['label']}" + (' (unavailable)' if not model.get('enabled', True) else ''))
        configured_default = next((m for m in enabled if m['label'] == config.model), None)
        preferred = configured_default or enabled[0]
        if configured_default is None:
            system('Configured default ' + config.model + ' is unavailable; using the highest-ranked enabled model for this run.')
        system('Version ranking prefers newer versions within a family, then deeper modes. Provider families are not directly comparable.')
        system('Suggested/default: ' + preferred['label'])
        attempted_models = set()
        while True:
            try:
                await browser.select_model(preferred['label'])
                break
            except ModelUnavailableError:
                attempted_models.add(preferred['label'])
                models = await browser.discover_models()
                ranked = model_rank(models)
                enabled = [m for m in ranked if m.get('enabled', True)]
                next_model = next((m for m in enabled if m['label'] not in attempted_models), None)
                if next_model is None:
                    raise
                system('The model picker changed while startup was selecting a model. Refreshed enabled choices:')
                for i, model in enumerate(models, 1):
                    system(f"{i}. {model['label']}" + (' (unavailable)' if not model.get('enabled', True) else ''))
                preferred = next_model
                system('Retrying with the highest-ranked newly available model: ' + preferred['label'])
        if args.model:
            chosen = next((m for m in enabled if m['label'] == args.model), None)
            if chosen is None:
                raise ValueError('Requested model is not an enabled exact UI label')
        else:
            ambiguous = preferred.get('provider') != 'OpenAI' and not config.model
            chosen = None
            for attempt in range(5):
                prompt = 'Choose an enabled displayed number (provider ranking is ambiguous): ' if ambiguous else 'Choose a displayed number, or Enter for the default: '
                answer = (await ask(prompt)).strip()
                if not answer and not ambiguous:
                    chosen = preferred
                    break
                if answer.isdigit() and 1 <= int(answer) <= len(models) and models[int(answer)-1] in enabled:
                    chosen = models[int(answer)-1]
                    break
                system('Enter an enabled model number from the displayed list.')
            if chosen is None:
                raise ValueError('Model selection exhausted five attempts')
        if chosen['label'] != preferred['label']:
            await browser.select_model(chosen['label'])
        if not resume_existing:
            await orchestrator.prepare_initialization()
        settings['config']['model'] = chosen['label']
        persist_runtime_settings(config, settings)
        state.event('model_selected', label=chosen['label'], visible=True)
        if _UI_EVENT_SINK is not None:
            _UI_EVENT_SINK('model', {'name': chosen['label'], 'verified': True})
            _UI_EVENT_SINK('session', {'title': 'Copilot session ' + state.session_id[:8]})
        if not resume_existing:
            await orchestrator.initialize()
        else:
            system('Resuming the existing Copilot conversation; startup will not send another initialization message.')
        if resume_capture:
            system('Recovering the last committed response from the visible chat without resending its request.')
            await orchestrator.recover_capture_failed_turn()
        reconciled_unsent = state.data.get('last_reconciled_unsent') if resume_existing else None
        if isinstance(reconciled_unsent, dict):
            request_id = reconciled_unsent.get('request_id')
            if reconciled_unsent.get('ordinal') != state.message_count + 1:
                raise BrowserUIError('The reconciled unsent request is no longer the next conversation turn; no draft was sent.')
            draft = await browser.read_reconciled_draft(request_id, reconciled_unsent.get('text_hash'))
            system('Resuming the exact draft previously confirmed as not sent; its hash and chat state match.')
            state.begin_submission(request_id, draft)
            state.data['status'] = 'submitting'
            state.save()
            def committed_reconciled_draft():
                state.confirm_submission(request_id)
            try:
                raw = await browser.exchange(draft, request_id, on_submitted=committed_reconciled_draft)
            except SubmissionNotSentError:
                state.reconcile_submission(False)
                state.data['status'] = 'blocked'
                state.save()
                raise
            except SubmissionAmbiguousError:
                state.data['status'] = 'submission_uncertain'
                state.event('submission_uncertain', request_id=request_id)
                state.save()
                raise
            except CaptureTimeoutError:
                state.data['status'] = 'capture_failed'
                state.event('capture_failed', request_id=request_id)
                state.save()
                raise
            await orchestrator.turn(
                'Continue from the captured reply to the exact request already confirmed as not sent. Do not resend it.',
                recovered_response=(raw, request_id))
            resume_request_id = request_id
        await browser.verify_interaction_ready(chosen['label'], request_id=resume_request_id)
        system('Type your request and press Enter. For files, type :attach to open Choose files, then type your request.')
        system('Commands: :new [first message], :attach, :files, :remove <number>, :clear, :status, :exit. While the agent is running, type steering normally or use :steer <text>; :attach opens the local picker and :attach "path with spaces" adds a file (up to 20).')
        pending_files = orchestrator.attachment_queue()
        if terminal_input is not None:
            terminal_input.attach_picker = lambda: select_files(pending_files.account_root)
        async def run_user_turn(text, paths=()):
            active_run_id = _UI_ACTIVE_RUN_ID() if callable(_UI_ACTIVE_RUN_ID) else uuid.uuid4().hex
            if terminal_input is not None:
                terminal_input.set_active(active_run_id, orchestrator.cancel_event)
            try:
                return await orchestrator.turn(text, attachments=paths, active_run_id=active_run_id)
            finally:
                if terminal_input is not None:
                    terminal_input.set_active()
        def show_files():
            records = pending_files.records()
            system('Files for your next request: ' + str(len(records)) + '/' + str(MAX_USER_FILES) + '. Final automatic context files are included in the same 20-file send limit and checked before upload.')
            for index, record in enumerate(records, 1):
                conversion = ' (sent as ' + record['upload_name'] + ', identical bytes)' if record['requires_text_conversion'] else ''
                system(str(index) + '. ' + record['name'] + ' — ' + str(record['size']) + ' bytes' + conversion)
            if records:
                system('Now type your request. You will review this exact file batch once before upload. :remove <number> or :clear changes the queue.')
        while True:
            try:
                text = (await ask('You: ')).strip()
                if not text:
                    continue
                if text.lower() in {':exit', 'exit', 'quit'}:
                    break
                if text == ':new' or text.startswith(':new '):
                    first_message = text[4:].strip()
                    orchestrator = await start_new_session(config, orchestrator, chosen['label'])
                    browser, state = orchestrator.browser, orchestrator.state
                    directory = state.directory
                    pending_files = orchestrator.attachment_queue()
                    system('New independent session started; its records are kept in the configured user storage.')
                    if first_message:
                        initial_attachments = _UI_TAKE_ATTACHMENTS() if _UI_TAKE_ATTACHMENTS else ()
                        await run_user_turn(first_message, initial_attachments)
                    continue
                if text == ':status':
                    system(json.dumps({'session_id': state.session_id, 'message_count': state.message_count,
                                      'status': state.data['status'], 'findings': len(orchestrator.findings.data['findings']),
                                      'bug_fix': bool(state.data.get('bug_fix')),
                                      'uncertain_calls': [k for k, v in state.data['calls'].items() if v['status'] == 'uncertain']}, indent=2))
                    continue
                if text == ':attach' or text.lower() == 'attach files' or text.startswith(':attach '):
                    paths = ([Path(text[8:].strip().strip('"'))] if text.startswith(':attach ') else
                             await asyncio.to_thread(select_files, pending_files.account_root))
                    if paths:
                        pending_files.add(paths)
                        show_files()
                    else:
                        system('No files selected; the queue is unchanged.')
                    continue
                if text == ':files':
                    show_files()
                    continue
                if text.startswith(':remove '):
                    removed = pending_files.remove(int(text[8:].strip()))
                    system('Removed from the pending queue: ' + removed['name'] + '. The original file is preserved.')
                    show_files()
                    continue
                if text == ':clear':
                    pending_files.clear()
                    system('Pending attachment queue cleared. Original files are preserved.')
                    continue
                if text.startswith(':resolve '):
                    system('Manual resolution is disabled. Ask Copilot to inspect the current page and request browser.reconcile for an uncertain navigation-only call.')
                    continue
                pending_files.verify()
                before_send = state.message_count
                submitted_attachments = _UI_TAKE_ATTACHMENTS() if _UI_TAKE_ATTACHMENTS else ()
                await run_user_turn(text, [*pending_files.paths(), *submitted_attachments])
                if state.message_count > before_send:
                    pending_files.clear()
            except CaptureTimeoutError as exc:
                _record_turn_error(state, exc)
                error('Copilot reply capture timed out. No local action ran for this reply.')
                system('The sent message and capture details were retained in the configured user storage.')
                _record_bug_fix(state, config, exc, 'Copilot response capture', 'turn', bug_reports)
            except (ValueError, RuntimeError, OSError) as exc:
                _record_turn_error(state, exc)
                error('Action stopped: ' + str(exc))
                system('Session evidence was retained in the configured user storage.')
                if _actionable(exc):
                    _record_bug_fix(state, config, exc, 'Interactive agent operation', 'turn', bug_reports)
                if state.data['status'] == 'closed':
                    system('The previous session was archived. Restart the application to try a fresh session.')
                    break
                if state.data['pending_submission']:
                    system('Delivery is uncertain. Exit and resume with explicit reconciliation before another send.')
            except EOFError:
                break
            except Exception as exc:
                _record_turn_error(state, exc)
                _record_bug_fix(state, config, exc, 'Interactive agent operation', 'turn', bug_reports)
                error('The error was recorded; the session is still available. You can retry or continue with another request.')
    except Exception as exc:
        _record_bug_fix(state, config, exc, 'Agent startup or session', 'startup_or_session', bug_reports)
        raise
    finally:
        try:
            if orchestrator:
                await orchestrator.close()
            else:
                await browser.close()
        except Exception as exc:
            _record_bug_fix(state, config, exc, 'Agent shutdown', 'shutdown', bug_reports)
        _show_bug_handoff(bug_reports)
        if terminal_input is not None:
            terminal_input.close()
            _TERMINAL_INPUT = None
            _UI_STEERING_POLL = None
            _UI_TAKE_ATTACHMENTS = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--attach-existing', action='store_true')
    parser.add_argument('--port', type=int)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--model', help='Exact currently displayed UI label')
    parser.add_argument('--yes-setup', action='store_true', help='Accept supplied settings and the fast full-access session grant; isolated proof remains separate')
    parser.add_argument('--setup-only', action='store_true', help='Verify configured per-user storage and Edge without opening Copilot')
    parser.add_argument('--package-mode', choices=['reviewed', 'immediate'],
                        help='Legacy compatibility option; normal startup uses one fast full-access session choice')
    parser.add_argument('--discover-first', action='store_true',
                        help='Show the guided local Crawl4AI website discovery even with --yes-setup')
    parser.add_argument('--isolated-test-workspace', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--local-knowledge-test-directory', type=Path,
                        help='Explicitly use an empty C: LocalAppData directory for a live navigation-knowledge test; normal production storage remains S:-only.')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        system('\nStopped; retained session and browser profile.')
    except Exception as exc:
        system('Startup stopped: ' + str(exc))
        raise SystemExit(1) from exc
