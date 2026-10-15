"""Local REA readiness identities and bounded probes; never install or navigate."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import time


HEALTH_LOCK = threading.RLock()
HEALTH_CACHE = {}
# An uncertain process belongs to this process lifetime, not a cache TTL. A
# runtime file change must not erase the need to reconcile its earlier child.
UNCERTAIN_NODE_PROBES = {}


def _stat_stamp(info):
    if stat.S_ISDIR(info.st_mode):
        # Parent contents and Windows delayed directory timestamp updates do
        # not identify a runtime. Tree members are enumerated separately;
        # retain link/reparse ownership identity without unrelated churn.
        return (info.st_mode, info.st_ino, getattr(info, 'st_file_attributes', 0),
                getattr(info, 'st_reparse_tag', 0))
    return (info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_ino, getattr(info, 'st_file_attributes', 0),
            getattr(info, 'st_reparse_tag', 0))


def file_stamp(path, *, include_parents=False):
    path = Path(path)
    try:
        value = (str(path), _stat_stamp(path.stat()), _stat_stamp(path.lstat()))
    except OSError as error:
        value = (str(path), type(error).__name__, getattr(error, 'errno', None))
    if include_parents:
        value += (tuple(file_stamp(parent) for parent in path.parents),)
    return value


def source_tree_stamp(root, limit=4000):
    """Include transitive CLI sources, including additions/removals and edits."""
    result = [file_stamp(root, include_parents=True)]
    pending = [Path(root)]
    try:
        while pending:
            folder = pending.pop()
            with os.scandir(folder) as entries:
                for entry in entries:
                    metadata = entry.stat(follow_symlinks=False)
                    result.append((entry.path, _stat_stamp(metadata)))
                    if len(result) >= limit:
                        result.append(('identity_limit', time.monotonic_ns()))
                        return tuple(sorted(result, key=repr))
                    # Never follow a symlink/junction while forming a cache key.
                    if (entry.is_dir(follow_symlinks=False)
                            and not getattr(metadata, 'st_reparse_tag', 0) & 0x20000000):
                        pending.append(Path(entry.path))
    except OSError as error:
        result.append((str(root), type(error).__name__, getattr(error, 'errno', None)))
    return tuple(sorted(result, key=repr))


def python_source_identity(paths):
    result = [file_stamp(Path(__file__), include_parents=True)]
    for path in paths:
        path = Path(path)
        stamp = file_stamp(path, include_parents=True)
        try:
            # Bundled source files are small; content identity also detects
            # replacements whose timestamps were preserved by deployment.
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = None
        result.append((stamp, digest))
    return tuple(result)


def cached_health(key, check, *, failure_seconds=15):
    """Share one health result across catalog, routing and execution callers."""
    with HEALTH_LOCK:
        entry = HEALTH_CACHE.get(key)
        if entry and (entry[1].get('available') or entry[1].get('cleanup_uncertain')
                      or time.monotonic() - entry[0] < failure_seconds):
            return copy.deepcopy(entry[1])
        result = check()
        HEALTH_CACHE[key] = (time.monotonic(), copy.deepcopy(result))
        while len(HEALTH_CACHE) > 32:
            del HEALTH_CACHE[next(iter(HEALTH_CACHE))]
        return copy.deepcopy(result)


def scratch_roots(project=None, extra_roots=()):
    project = Path(project) if project else Path(__file__).resolve().parents[1]
    roots = [project / '.runtime' / 'rea-readiness', *extra_roots]
    if os.environ.get('LOCALAPPDATA'):
        roots.append(Path(os.environ['LOCALAPPDATA']) / 'Copilot Local Agent' / 'rea-readiness')
    try:
        roots.append(Path(tempfile.gettempdir()) / 'Copilot Local Agent' / 'rea-readiness')
    except OSError:
        pass
    return list(dict.fromkeys(Path(root) for root in roots))


@contextmanager
def scratch_directory(project=None, extra_roots=()):
    from .policy import reject_path_redirection
    failures = []
    temporary = None
    for root in scratch_roots(project, extra_roots):
        try:
            reject_path_redirection(root)
            root.mkdir(parents=True, exist_ok=True)
            temporary = tempfile.TemporaryDirectory(prefix='probe_', dir=root)
            test = Path(temporary.name) / 'writable-check'
            test.write_bytes(b'REA')
            test.unlink()
            break
        except (OSError, ValueError) as error:
            failures.append(str(root) + ': ' + type(error).__name__)
            if temporary is not None:
                temporary.cleanup()
                temporary = None
    if temporary is None:
        raise OSError('No writable REA readiness scratch candidate: ' + '; '.join(failures))
    try:
        yield Path(temporary.name)
    finally:
        temporary.cleanup()


def native_probe(command, *, timeout, cwd=None, output_limit=262144):
    """Bound output on disk and retain explicit owned-child cleanup status."""
    from .local_python_runner import _terminate_pid
    process = None
    extras = [Path(command[0]).parent / '.rea-readiness'] if command else []
    with scratch_directory(extra_roots=extras) as scratch, tempfile.TemporaryFile(dir=scratch) as output:
        try:
            options = ({'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
                       if os.name == 'nt' else {'start_new_session': True})
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, **options)
            deadline = time.monotonic() + max(0, timeout)
            failure = None
            while process.poll() is None:
                if output.seek(0, 2) > output_limit:
                    failure = 'output_limit'
                    break
                if time.monotonic() >= deadline:
                    failure = 'timeout'
                    break
                time.sleep(.02)
            if failure:
                stopped = _terminate_pid(process.pid)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    stopped = False
                return {'error': failure, 'cleanup_uncertain': not stopped,
                        'pid': process.pid, 'returncode': process.poll()}
            output.seek(0)
            text = output.read(output_limit + 1).decode('utf-8', 'replace')
            return {'returncode': process.returncode, 'stdout': text,
                    'error': 'output_limit' if len(text.encode('utf-8')) > output_limit else None,
                    'cleanup_uncertain': False}
        except OSError as error:
            uncertain = False
            if process is not None and process.poll() is None:
                stopped = _terminate_pid(process.pid)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    stopped = False
                uncertain = not stopped
            return {'error': 'spawn_failed' if process is None else 'probe_io_failed',
                    'cleanup_uncertain': uncertain,
                    'errno': getattr(error, 'errno', None)}
        finally:
            if process is not None and process.poll() is None:
                _terminate_pid(process.pid)
