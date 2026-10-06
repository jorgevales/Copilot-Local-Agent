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
from .browser import BrowserAdapter, model_rank
from .config import Config
from .orchestrator import Orchestrator
from .state import SessionState
from .tools import ToolRegistry
from .feedback import Feedback
from .file_picker import select_files
from .attachments import MAX_USER_FILES
from .storage import default_storage, discover_onedrive_accounts, machine_key, read_user_settings, save_user_settings, validate_storage_directory
from . import reused_browser as edge
from .setup_resources import choose_account, choose_edge

_TERMINAL = Feedback()

def system(message):
    _TERMINAL.emit('System', message)


def error(message):
    _TERMINAL.emit('Error', message)


async def ask(prompt: str) -> str:
    return await asyncio.to_thread(input, _TERMINAL.prompt('User', prompt))


async def choose_browser_endpoint(config, args, settings):
    """Reuse only the exact owned profile; otherwise choose a free loopback port.

    Changes the in-memory config/settings only. The caller persists settings before
    launch. The browser adapter still repeats endpoint/profile validation and
    guards the profile with its controller mutex, including startup races.
    """
    if config.attach_existing:
        return config
    debug_ports = settings.get('debug_ports', {})
    if not isinstance(debug_ports, dict):
        raise ValueError('Per-machine debug_ports settings must be an object')
    key = machine_key()
    remembered = debug_ports.get(key)
    candidates = []
    if not getattr(args, 'port', None) and type(remembered) is int and 1024 <= remembered <= 65535:
        candidates.append(remembered)
    if config.debug_port not in candidates:
        candidates.append(config.debug_port)
    selected = None
    for port in candidates:
        endpoint = edge.cdp_endpoint(port)
        payload = await asyncio.to_thread(edge.get_cdp_version, endpoint)
        if payload:
            try:
                edge.validate_endpoint(endpoint, payload)
                await asyncio.to_thread(edge.validate_profile_ownership, port, config.profile_dir)
            except (edge.EndpointError, OSError, ValueError):
                # Unknown or mismatched listeners are never attached.
                pass
            else:
                selected = port
                config.attach_existing = True
                system('Reusing the verified dedicated Edge profile on local port ' + str(port) + '.')
                break
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
    directory = config.runtime_dir / 'sessions' / uuid.uuid4().hex
    state = SessionState(directory)
    browser = BrowserAdapter(fresh_config)
    browser._launched_process = owned_process
    engine = None
    try:
        await browser.start()
        # Recheck current account availability and the actual checked option.
        await browser.discover_models()
        await browser.select_model(model_label)
        state.event('model_selected', label=model_label, visible=True)
        engine = Orchestrator(fresh_config, browser, registry or ToolRegistry(), state)
        await engine.initialize()
        return engine
    except Exception as exc:
        state.event('new_session_setup_failed', error=str(exc))
        state.data['status'] = 'blocked'
        state.save()
        await browser.close()
        raise RuntimeError('New session setup stopped; previous records and new diagnostics are retained in your selected OneDrive storage.') from exc


async def run(args):
    config = Config.load(args.config)
    if config.storage_dir is None:
        accounts = getattr(config, '_storage_candidates', None) or discover_onedrive_accounts()
        selected = await choose_account(accounts, ask, system)
        config.select_storage(default_storage(selected))
    settings = read_user_settings(config.storage_dir)
    if args.config is None and isinstance(settings.get('config'), dict):
        personal = settings['config']
        allowed_keys = {'allowed_domains', 'allowed_roots', 'model', 'response_timeout', 'max_corrections', 'max_tool_rounds', 'sync_timeout', 'max_delivery_retries', 'download_timeout', 'copilot_download_hosts'}
        for key in allowed_keys & personal.keys():
            setattr(config, key, personal[key])
    if args.attach_existing:
        config.attach_existing = True
    if args.port:
        config.debug_port = args.port
    if args.profile:
        config.profile_dir = args.profile
        config._profile_explicit = True
    if args.model:
        config.model = args.model
    config.validate()
    accounts = getattr(config, '_storage_candidates', None) or discover_onedrive_accounts()
    validate_storage_directory(config.storage_dir, accounts)
    if not config.profile_dir.is_relative_to(config.storage_dir) and not (config.attach_existing and config.root.drive.upper() != 'S:'):
        raise ValueError('The persistent Edge profile must be inside your selected OneDrive storage.')
    transient = config.runtime_dir / 'temp'
    transient.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = str(transient)
    os.environ['TMP'] = str(transient)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    await choose_edge(config, settings, ask, system, force=getattr(args, 'setup_only', False))
    settings['python_executable'] = sys.executable
    settings['config'] = {key: value for key, value in config.as_dict().items() if key in {
        'allowed_domains', 'allowed_roots', 'model', 'response_timeout', 'max_corrections', 'max_tool_rounds',
        'sync_timeout', 'max_delivery_retries', 'download_timeout', 'copilot_download_hosts'}}
    settings['config']['allowed_roots'] = [str(Path(path).relative_to(config.storage_dir))
                                          if Path(path).is_relative_to(config.storage_dir) else path
                                          for path in config.allowed_roots]
    save_user_settings(config.storage_dir, settings)
    if getattr(args, 'setup_only', False):
        system('Setup verified. Personal storage: ' + str(config.storage_dir))
        system('Python resource setup verified. Setup.cmd creates the project virtual environment and installs pinned dependencies before this storage step.')
        return
    await choose_browser_endpoint(config, args, settings)
    save_user_settings(config.storage_dir, settings)
    for root in config.allowed_roots:
        Path(root).mkdir(parents=True, exist_ok=True)
    directory = args.resume or config.runtime_dir / 'sessions' / uuid.uuid4().hex
    if args.resume and not Path(args.resume).resolve().is_relative_to(config.runtime_dir.resolve()):
        raise ValueError('Resume sessions must be inside your selected per-user runtime directory.')
    state = SessionState(directory, resume=bool(args.resume))
    browser = BrowserAdapter(config)
    orchestrator = None
    system('Copilot Local Agent — reasoning through Microsoft 365 Copilot web UI')
    system('Session records are kept in your selected OneDrive storage.')
    system('Browser: Visible. Non-visible Copilot operation has not passed acceptance and is unavailable.')
    system('Permitted file roots: ' + ', '.join(Path(root).name for root in config.allowed_roots))
    system('Third-party browser domains: ' + ', '.join(config.allowed_domains))
    system('No files will be deleted. Generated-code execution always requires approval.')
    system('Useful Findings are saved on any valid turn; their file is attached every ten messages.')
    system('File delivery: actual Copilot UI downloads and verified ZIP extraction; no Created-folder monitoring.')
    if not args.yes_setup:
        if (await ask('Start this visible run [Y/n]? ')).strip().lower() == 'n':
            return
    try:
        if state.data['pending_submission']:
            system('Previous delivery is uncertain. Inspect the previous chat before reconciling.')
            answer = (await ask('Was that exact pending request submitted [sent/not-sent/exit]? ')).strip()
            if answer not in {'sent', 'not-sent'}:
                return
            state.reconcile_submission(answer == 'sent')
        await browser.start()
        models = await browser.discover_models()
        ranked = model_rank(models)
        enabled = [m for m in ranked if m.get('enabled', True)]
        if not enabled:
            raise RuntimeError('No enabled Copilot models were discovered')
        system('Models actually discovered in this account:')
        for i, model in enumerate(models, 1):
            system(f"{i}. {model['label']}" + (' (unavailable)' if not model.get('enabled', True) else ''))
        preferred = next((m for m in enabled if m['label'] == config.model), enabled[0])
        system('Version ranking prefers newer versions within a family, then deeper modes. Provider families are not directly comparable.')
        system('Suggested/default: ' + preferred['label'])
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
        await browser.select_model(chosen['label'])
        settings['config']['model'] = chosen['label']
        save_user_settings(config.storage_dir, settings)
        state.event('model_selected', label=chosen['label'], visible=True)
        orchestrator = Orchestrator(config, browser, ToolRegistry(), state)
        await orchestrator.initialize()
        system('Type your request and press Enter. For files, type :attach to open Choose files, then type your request.')
        system('Commands: :new [first message], :attach, :files, :remove <number>, :clear, :status, :exit. Advanced: :attach <path>, :resolve <call_id> completed|not_executed')
        pending_files = orchestrator.attachment_queue()
        def show_files():
            records = pending_files.records()
            system('Files for your next request: ' + str(len(records)) + '/' + str(MAX_USER_FILES) + '. Ten of Copilot\'s 20 slots are reserved for startup guidance, findings and context.')
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
                    system('New independent session started; its records are kept in your selected OneDrive storage.')
                    if first_message:
                        await orchestrator.turn(first_message)
                    continue
                if text == ':status':
                    system(json.dumps({'session_id': state.session_id, 'message_count': state.message_count,
                                      'status': state.data['status'], 'findings': len(orchestrator.findings.data['findings']),
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
                    _, call_id, outcome = text.split()
                    system(json.dumps(state.data['calls'][call_id], ensure_ascii=False, indent=2))
                    if (await ask('Confirm the observed outcome by typing CONFIRM: ')) == 'CONFIRM':
                        state.reconcile_call(call_id, outcome)
                    continue
                pending_files.verify()
                before_send = state.message_count
                await orchestrator.turn(text, attachments=pending_files.paths())
                if state.message_count > before_send:
                    pending_files.clear()
            except (ValueError, RuntimeError, OSError) as exc:
                state.event('turn_error', error=str(exc))
                error('Action stopped: ' + str(exc))
                system('Session evidence was retained in your selected OneDrive storage.')
                if state.data['status'] == 'closed':
                    system('The previous session was archived. Restart the application to try a fresh session.')
                    break
                if state.data['pending_submission']:
                    system('Delivery is uncertain. Exit and resume with explicit reconciliation before another send.')
            except EOFError:
                break
    finally:
        if orchestrator:
            await orchestrator.close()
        else:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--attach-existing', action='store_true')
    parser.add_argument('--port', type=int)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--model', help='Exact currently displayed UI label')
    parser.add_argument('--yes-setup', action='store_true', help='Accept supplied browser settings; does not approve tools or scripts')
    parser.add_argument('--setup-only', action='store_true', help='Select/verify personal OneDrive storage without opening Copilot')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        system('\nStopped; retained session and browser profile.')
    except Exception as exc:
        system('Startup stopped: ' + str(exc))
        raise SystemExit(1) from exc
