"""Probe retry locations under S: without trusting free-space metadata."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import uuid


_PROBE_BYTES = 64 * 1024


def _candidate_directories(environ=None, *, storage_root=None, home=None, platform=None) -> list[Path]:
    # Temporary upload/browser work is agent-owned data too. Keep retries on S:
    # and try separate directories so one locked/broken folder does not block startup.
    if storage_root is None:
        raise ValueError('An S: Discoveries storage root is required for temporary agent files')
    base = Path(storage_root)
    candidates = [base / 'runtime' / 'temp', base / 'runtime' / 'temp-retry-1',
                  base / 'runtime' / 'temp-retry-2', base / 'runtime' / 'cache' / 'temp']

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


def select_temp_directory(environ=None, *, storage_root=None, home=None, platform=None, probe=_probe_directory) -> Path:
    """Return the first directory that passes a real write and readback probe.

    It deliberately avoids disk-usage/free-space estimates. Candidates remain
    under S: but use separate directories; every failed path is followed by
    another independent location and the last exception is chained on failure.
    """
    candidates = _candidate_directories(environ, storage_root=storage_root, home=home, platform=platform)
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


def configure_temp_directory(storage_root, environ=None, *, home=None, platform=None, probe=_probe_directory) -> Path:
    """Select and publish the verified location to Python and child processes."""
    directory = select_temp_directory(environ, storage_root=storage_root, home=home, platform=platform, probe=probe)
    target = str(directory)
    environment = os.environ if environ is None else environ
    environment['TEMP'] = target
    environment['TMP'] = target
    environment['TMPDIR'] = target
    # tempfile caches its first choice, so explicitly replace the cached value.
    tempfile.tempdir = target
    return directory
