"""Select a verified temporary directory without trusting free-space metadata.

The agent's persistent runtime may live on a synced, quota-limited, or redirected
volume. Temporary browser and upload data should use a separately probed location.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import uuid


_PROBE_BYTES = 64 * 1024


def _candidate_directories(environ=None, *, home=None, platform=None) -> list[Path]:
    environment = os.environ if environ is None else environ
    system = os.name if platform is None else platform
    home_path = Path.home() if home is None else Path(home)
    candidates: list[Path] = []
    if system == 'nt':
        local_app_data = environment.get('LOCALAPPDATA')
        if local_app_data:
            candidates.append(Path(local_app_data) / 'Temp' / 'CopilotLocalAgent')
        # Respect operator-provided temporary locations, but verify them with I/O.
        for key in ('TEMP', 'TMP'):
            if environment.get(key):
                candidates.append(Path(environment[key]) / 'CopilotLocalAgent')
        system_root = environment.get('SystemRoot') or environment.get('WINDIR')
        if system_root:
            candidates.append(Path(system_root) / 'Temp' / 'CopilotLocalAgent')
        candidates.append(home_path / 'AppData' / 'Local' / 'Temp' / 'CopilotLocalAgent')
    else:
        for key in ('TMPDIR', 'TEMP', 'TMP'):
            if environment.get(key):
                candidates.append(Path(environment[key]) / 'copilot-local-agent')
        cache = environment.get('XDG_CACHE_HOME')
        if cache:
            candidates.append(Path(cache) / 'copilot-local-agent' / 'temp')
        candidates.append(Path('/tmp') / 'copilot-local-agent')

    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            normalized = path.expanduser().resolve(strict=False)
        except OSError:
            normalized = path.expanduser().absolute()
        key = os.path.normcase(str(normalized))
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _probe_directory(directory: Path) -> None:
    """Verify mkdir, exclusive creation, durable write, readback, and cleanup."""
    directory.mkdir(parents=True, exist_ok=True)
    payload = os.urandom(_PROBE_BYTES)
    path = directory / ('.copilot-agent-write-probe-' + uuid.uuid4().hex)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        actual = path.read_bytes()
        if len(actual) != len(payload) or hashlib.sha256(actual).digest() != hashlib.sha256(payload).digest():
            raise OSError('temporary-directory write probe failed readback verification')
    finally:
        path.unlink(missing_ok=True)


def select_temp_directory(environ=None, *, home=None, platform=None, probe=_probe_directory) -> Path:
    """Return the first directory that passes a real write and readback probe.

    It deliberately does not consult disk-usage/free-space estimates and never
    reuses ``storage_dir/runtime/temp``. Every failed candidate is followed by
    another independent location; the last exception is chained on total failure.
    """
    candidates = _candidate_directories(environ, home=home, platform=platform)
    failures: list[tuple[Path, OSError]] = []
    for candidate in candidates:
        try:
            probe(candidate)
        except OSError as exc:
            failures.append((candidate, exc))
            continue
        return candidate
    tested = len(failures)
    attempted = ', '.join(str(path) for path, _ in failures) or 'no usable temporary locations were configured'
    final_error = failures[-1][1] if failures else None
    message = f'No temporary directory passed the write/readback probe ({tested} location(s) tested): {attempted}'
    if final_error is not None:
        raise OSError(message) from final_error
    raise OSError(message)


def configure_temp_directory(environ=None, *, home=None, platform=None, probe=_probe_directory) -> Path:
    """Select and publish the verified location to Python and child processes."""
    directory = select_temp_directory(environ, home=home, platform=platform, probe=probe)
    target = str(directory)
    environment = os.environ if environ is None else environ
    environment['TEMP'] = target
    environment['TMP'] = target
    environment['TMPDIR'] = target
    # tempfile caches its first choice, so explicitly replace the cached value.
    tempfile.tempdir = target
    return directory
