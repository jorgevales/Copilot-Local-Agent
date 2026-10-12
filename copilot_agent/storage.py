"""Per-user local app-data storage and operator-selected storage paths."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import socket

from .persistence import write_json

SETTINGS_FILE = 'settings.json'
TESTING_SETTINGS_FILE = 'testing-settings.json'


def machine_key(hostname=None) -> str:
    name = socket.gethostname() if hostname is None else str(hostname)
    return 'vdi-' + hashlib.sha256(name.casefold().encode('utf-8')).hexdigest()[:16]


def default_local_storage(environ=None) -> Path:
    """Return the ordinary per-user app-data root without probing OneDrive."""
    environment = os.environ if environ is None else environ
    base = environment.get('LOCALAPPDATA')
    if isinstance(base, str) and base.strip():
        return Path(base).expanduser().resolve() / 'CopilotLocalAgent'
    if os.name == 'nt':
        return Path.home() / 'AppData' / 'Local' / 'CopilotLocalAgent'
    base = environment.get('XDG_DATA_HOME')
    return (Path(base).expanduser() if isinstance(base, str) and base.strip()
            else Path.home() / '.local' / 'share') / 'copilot-local-agent'


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
