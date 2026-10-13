"""Environment-local discovery storage and operator-selected storage helpers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import socket
import ntpath

from .persistence import write_json

SETTINGS_FILE = 'settings.json'
TESTING_SETTINGS_FILE = 'testing-settings.json'


def machine_key(hostname=None) -> str:
    name = socket.gethostname() if hostname is None else str(hostname)
    return 'vdi-' + hashlib.sha256(name.casefold().encode('utf-8')).hexdigest()[:16]


def discoveries_storage(project_root: Path, environ=None) -> Path:
    """Prefer the live shared store, otherwise use this host's local app data."""
    from .policy import PolicyError, mapped_s_drive_root
    root = Path(project_root).expanduser().resolve()
    try:
        share = mapped_s_drive_root().resolve()
    except (PolicyError, OSError):
        # A reachable UNC checkout needs no particular mapped drive letter.
        if root.drive.startswith('\\\\'):
            return root.parent / 'Discoveries knowledge'
        environment = os.environ if environ is None else environ
        local = environment.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        return validate_user_storage_directory(Path(local) / 'CopilotLocalAgent' / 'Discoveries knowledge')
    if root != share and share in root.parents:
        return root.parent / 'Discoveries knowledge'
    # A VDI may pull its source onto C: while durable data lives on S:.
    return share / 'CopilotLocalAgent' / 'Discoveries knowledge'


def discoveries_storage_paths(project_root: Path) -> dict[str, str]:
    """Describe the selected folder without assuming a drive mapping exists."""
    from .policy import PolicyError, mapped_s_drive_root
    target = discoveries_storage(project_root).resolve()
    try:
        share = mapped_s_drive_root().resolve()
    except (PolicyError, OSError):
        return {'s_path': str(target), 'unc_path': str(target)}
    if target != share and share not in target.parents:
        return {'s_path': str(target), 'unc_path': str(target)}
    relative = ntpath.relpath(str(target), str(share))
    if relative == '..' or relative.startswith('..\\'):
        raise ValueError('The Discoveries knowledge folder resolved outside the live S: share')
    return {'s_path': str(Path('S:/') / Path(relative)), 'unc_path': str(target)}


def default_local_storage(environ=None) -> Path:
    """Select storage for the current machine and checkout."""
    from .config import PROJECT_ROOT
    return discoveries_storage(PROJECT_ROOT, environ=environ)


def validate_user_storage_directory(path: Path) -> Path:
    """Normalize an operator-supplied storage path, including an explicit OneDrive path."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise ValueError('Storage must be an absolute local path supplied by the user or configuration')
    target = target.resolve()
    if target == Path(target.anchor):
        raise ValueError('Storage must be a dedicated directory, not a filesystem root')
    return target


def profile_directory(storage_dir: Path, hostname=None) -> Path:
    return Path(storage_dir) / 'runtime' / 'edge-profiles' / machine_key(hostname)


def read_user_settings(storage_dir: Path, *, testing=False) -> dict:
    if type(testing) is not bool:
        raise ValueError('Testing preferences selector must be boolean')
    path = Path(storage_dir) / (TESTING_SETTINGS_FILE if testing else SETTINGS_FILE)
    if not path.is_file():
        # Testing may inherit live defaults in memory, never write them back.
        return read_user_settings(storage_dir) if testing else {}
    if path.stat().st_size > 65536:
        raise ValueError('Per-user settings exceed the bounded settings size')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or value.get('schema_version') != '1.0':
        raise ValueError('Unsupported per-user settings format')
    return value


def save_user_settings(storage_dir: Path, settings: dict, *, testing=False) -> Path:
    if type(testing) is not bool:
        raise ValueError('Testing preferences selector must be boolean')
    directory = Path(storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    value = dict(settings, schema_version='1.0', storage_dir=str(directory))
    value.pop('selected_account', None)  # Drop the former account auto-selection flag.
    path = directory / (TESTING_SETTINGS_FILE if testing else SETTINGS_FILE)
    write_json(path, value)
    return path


def shared_python_candidates(values, require_shared=True) -> list[str]:
    """Pure candidate normalization for the launcher's S-drive policy."""
    selected, seen = [], set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = PureWindowsPath(value.strip().strip('"'))
        if candidate.name.casefold() != 'python.exe' or not candidate.is_absolute():
            continue
        if require_shared and candidate.drive.upper() != 'S:':
            continue
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            selected.append(str(candidate))
    return selected
