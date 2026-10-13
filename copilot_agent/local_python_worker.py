"""Fixed worker for an explicitly approved local-Python plan.

This process is defense in depth, not an operating-system sandbox.  The host
validates and hashes the complete plan before launch; this worker repeats the
important runtime checks and records every managed child process immediately.
"""
from __future__ import annotations

import ast
import builtins
import _io as private_io
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import traceback
from urllib.parse import urlsplit


EXPOSED_APPLICATION_IMPORTS = frozenset({"copilot_agent.desktop"})
DENIED_NATIVE_FILE_MODULES = frozenset({
    "mmap", "msvcrt", "win32file", "_io", "sqlite3", "_sqlite3", "dbm", "_dbm", "_gdbm",
    "shelve", "lmdb", "apsw", "duckdb", "berkeleydb", "bsddb", "h5py", "tables",
    "pyarrow", "ctypes",
})


def _within(path: Path, scopes: list[Path]) -> bool:
    return any(path == scope or scope.is_dir() and scope in path.parents for scope in scopes)


def _write_event(stream, event: str, **details) -> None:
    stream.write(json.dumps({"event": event, **details}, ensure_ascii=False) + "\n")
    stream.flush()


def _normalized_executable(value: str) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def main() -> int:
    if len(sys.argv) < 4:
        print("Local Python worker received an incomplete invocation.", file=sys.stderr)
        return 2
    plan_path, script_path, ledger_path = map(Path, sys.argv[1:4])
    user_arguments = sys.argv[4:]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    script_bytes = script_path.read_bytes()
    if hashlib.sha256(script_bytes).hexdigest() != plan["script_sha256"]:
        print("Approved script bytes changed before worker execution.", file=sys.stderr)
        return 2
    if user_arguments != plan["arguments"]:
        print("Runtime arguments differ from the approved plan.", file=sys.stderr)
        return 2
    source = script_bytes.decode("utf-8", errors="strict")
    code = compile(source, str(script_path), "exec")
    package_parent = Path(__file__).resolve().parents[1]
    approved_root = Path(plan["application_root"]).resolve()
    if approved_root != package_parent:
        print("Approved application import root differs from the bound worker runtime.", file=sys.stderr)
        return 2
    if str(approved_root) not in sys.path:
        sys.path.insert(0, str(approved_root))
    working = Path(plan["working_directory"]).resolve()
    os.chdir(working)
    read_scopes = [Path(item).resolve() for item in plan["read_paths"]]
    create_scopes = [Path(item).resolve() for item in plan["create_paths"]]
    create_roots = [Path(item).resolve() for item in plan.get("create_roots", [])]
    package_scratch_active = bool(create_roots)
    modify_scopes = [Path(item).resolve() for item in plan["modify_paths"]]
    runtime_roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), Path(__file__).resolve().parent]
    permissions = set(plan["permissions"])
    declared_imports = set(plan["imports"])
    destinations = set()
    for item in plan["network_destinations"]:
        parsed = urlsplit(item)
        destinations.add((parsed.hostname.casefold(), parsed.port or 443))
    child_specs = plan["subprocesses"]
    created_in_worker: set[str] = set()
    scratch_file_sizes: dict[str, int] = {}
    scratch_directories: set[str] = set()
    used_specs: set[int] = set()
    real_popen = subprocess.Popen
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8", newline="\n") as ledger:
        _write_event(ledger, "worker_started", pid=os.getpid())
        _write_event(ledger, "capabilities_validated", imports=sorted(declared_imports),
                     application_imports=sorted(declared_imports & EXPOSED_APPLICATION_IMPORTS))

        def audit(event, args):
            if package_scratch_active and event == "import" and args and isinstance(args[0], str):
                if args[0].split(".", 1)[0] in DENIED_NATIVE_FILE_MODULES:
                    raise PermissionError("Native file stores and raw file access are unavailable in package stages")
            if package_scratch_active and event == "mmap.__new__":
                raise PermissionError("Memory mapped file access is unavailable in package stages")
            if event == "open" and args and isinstance(args[0], int):
                mode = args[1] if len(args) > 1 else "r"
                flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
                if ((isinstance(mode, str) and any(mark in mode for mark in "wax+"))
                        or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                    raise PermissionError("Writing through an unbound file descriptor is unavailable")
            if event == "open" and args and isinstance(args[0], (str, bytes)):
                candidate = Path(os.fsdecode(args[0]))
                candidate = (working / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                mode = args[1] if len(args) > 1 else "r"
                flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
                writing = (isinstance(mode, str) and any(mark in mode for mark in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
                if writing:
                    if _within(candidate, modify_scopes):
                        return
                    if _within(candidate, create_scopes) and not candidate.exists():
                        return
                    candidate_key = os.path.normcase(str(candidate))
                    if _within(candidate, create_roots):
                        if candidate_key in created_in_worker:
                            info = candidate.lstat()
                            if candidate.is_file() and not candidate.is_symlink() and info.st_nlink == 1:
                                return
                        elif not candidate.exists():
                            if len(created_in_worker) >= 100:
                                raise PermissionError("Stage scratch file-count limit exceeded")
                            created_in_worker.add(candidate_key)
                            scratch_file_sizes[candidate_key] = 0
                            return
                    raise PermissionError("File write is outside the approved create/modify scope: " + str(candidate))
                if (_within(candidate, read_scopes) or _within(candidate, create_scopes + modify_scopes)
                        or _within(candidate, runtime_roots)
                        or os.path.normcase(str(candidate)) in created_in_worker):
                    return
                raise PermissionError("File read is outside the approved scope: " + str(candidate))
            if event in {"os.remove", "os.rmdir", "os.rename", "os.replace", "shutil.rmtree"}:
                raise PermissionError("Deletion and rename operations are unavailable in approved local Python")
            if event == "os.mkdir":
                candidate = Path(os.fsdecode(args[0]))
                candidate = (working / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                # Package stages may create nested directories only beneath
                # their private, precreated attempt scratch root.
                if candidate.is_dir() and any(candidate in scope.parents for scope in create_scopes):
                    return
                if any(candidate == scope or scope in candidate.parents for scope in create_roots):
                    key = os.path.normcase(str(candidate))
                    if not candidate.exists():
                        if len(scratch_directories) >= 100:
                            raise PermissionError("Stage scratch directory-count limit exceeded")
                        scratch_directories.add(key)
                    return
                raise PermissionError("Directory creation is outside the approved create scope: " + str(candidate))
            if event in {"os.symlink", "os.link", "os.chmod", "os.chown", "os.utime", "os.truncate"}:
                raise PermissionError("Link and file metadata mutations are unavailable in approved local Python")
            if event in {"os.listdir", "os.scandir"}:
                candidate = Path(args[0] if args and args[0] is not None else working)
                candidate = (working / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                # Import discovery needs to inspect the single bound parent that
                # contains copilot_agent. This does not authorize reading files or
                # enumerating any other project directory.
                if not (candidate == approved_root or _within(candidate, read_scopes)
                        or _within(candidate, runtime_roots)
                        or any(candidate == scope or scope in candidate.parents for scope in create_roots)):
                    raise PermissionError("Directory inspection is outside the approved read scope: " + str(candidate))
            if event in {"os.system", "os.spawn", "os.posix_spawn", "os.exec", "pty.spawn"}:
                raise PermissionError("Unmanaged process or shell execution is unavailable")
            if event in {"socket.bind", "socket.listen"}:
                raise PermissionError("Listening sockets are unavailable")
            if event == "socket.getaddrinfo":
                host = str(args[0]).casefold()
                port = int(args[1])
                if "network" not in permissions or (host, port) not in destinations:
                    raise PermissionError("Network destination is outside the approved scope")
            if event == "socket.connect":
                address = args[1]
                if not isinstance(address, tuple) or len(address) < 2:
                    raise PermissionError("Only approved TCP destinations are supported")
                host, port = str(address[0]).casefold(), int(address[1])
                approved_hosts = {host for host, approved_port in destinations if approved_port == port}
                if "network" not in permissions or host not in approved_hosts:
                    # A resolved IP is accepted only when it belongs to an approved hostname.
                    resolved = {item[4][0].casefold() for name, approved_port in destinations if approved_port == port
                                for item in socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)}
                    if host not in resolved:
                        raise PermissionError("Network connection is outside the approved scope")
            if event == "ctypes.dlopen" and not permissions.intersection({"desktop_capture", "window_management"}):
                raise PermissionError("Native desktop libraries require an approved desktop permission")

        sys.addaudithook(audit)

        # Bound scratch writes as they happen, rather than only after the worker
        # exits. Pathlib.write_text/write_bytes route through io.open.
        original_io_open = io.open
        original_builtin_open = builtins.open
        original_file_io = io.FileIO
        original_private_file_io = private_io.FileIO
        original_private_open = private_io.open
        scratch_write_bytes = 0

        class BoundedScratchStream:
            __slots__ = ("_stream", "_path", "_key")

            def __getattribute__(self, name):
                if name in {"_stream", "_path", "_key", "__dict__"}:
                    raise PermissionError("Private scratch stream state is unavailable")
                return object.__getattribute__(self, name)

            def __init__(self, stream, path):
                object.__setattr__(self, "_stream", stream)
                object.__setattr__(self, "_path", path)
                object.__setattr__(self, "_key", os.path.normcase(str(path)))

            def __getattr__(self, name):
                if name in {"buffer", "raw", "fileno", "truncate", "detach"}:
                    raise PermissionError("Scratch stream exposes no raw descriptor, buffer, detach, or truncate operation")
                stream = object.__getattribute__(self, "_stream")
                return getattr(stream, name)

            def truncate(self, size=None):
                raise PermissionError("Scratch files cannot be truncated through the file API")

            def fileno(self):
                raise PermissionError("Scratch file descriptors are unavailable")

            def __enter__(self):
                object.__getattribute__(self, "_stream").__enter__()
                return self

            def __exit__(self, *args):
                return object.__getattribute__(self, "_stream").__exit__(*args)

            def write(self, value):
                nonlocal scratch_write_bytes
                stream = object.__getattribute__(self, "_stream")
                path = object.__getattribute__(self, "_path")
                key = object.__getattribute__(self, "_key")
                if isinstance(value, str):
                    estimate = len(value.encode(stream.encoding or "utf-8")) * 2
                else:
                    try:
                        estimate = memoryview(value).nbytes
                    except TypeError:
                        estimate = len(value)
                current = scratch_file_sizes.get(key, path.stat().st_size if path.exists() else 0)
                try:
                    position = stream.tell()
                except (OSError, ValueError):
                    position = current
                projected = max(current, position + estimate)
                total = sum(scratch_file_sizes.values()) - current + projected
                if total > 50 * 1024 * 1024 or scratch_write_bytes + estimate > 50 * 1024 * 1024:
                    raise PermissionError("Stage scratch byte limit exceeded")
                result = stream.write(value)
                actual = os.fstat(stream.fileno()).st_size
                scratch_file_sizes[key] = actual
                scratch_write_bytes += estimate
                return result

            def writelines(self, lines):
                for line in lines:
                    self.write(line)

        def bounded_open(original, file, mode="r", *args, **kwargs):
            stream = original(file, mode, *args, **kwargs)
            if isinstance(file, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(file))
                candidate = (working / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                writing = any(mark in mode for mark in "wax+") if isinstance(mode, str) else False
                if writing and _within(candidate, create_roots):
                    return BoundedScratchStream(stream, candidate)
            return stream

        io.open = lambda file, mode="r", *args, **kwargs: bounded_open(original_io_open, file, mode, *args, **kwargs)
        builtins.open = lambda file, mode="r", *args, **kwargs: bounded_open(original_builtin_open, file, mode, *args, **kwargs)
        def denied_file_io(*args, **kwargs):
            raise PermissionError("Direct FileIO construction is unavailable in approved package stages")

        if package_scratch_active:
            io.FileIO = denied_file_io
            private_io.FileIO = denied_file_io
            private_io.open = lambda file, mode="r", *args, **kwargs: bounded_open(
                original_private_open, file, mode, *args, **kwargs)
        raw_write_functions = {name: getattr(os, name, None) for name in ("write", "writev", "pwrite", "pwritev", "ftruncate")}
        for name, original in raw_write_functions.items():
            if original is not None:
                setattr(os, name, lambda *args, **kwargs: (_ for _ in ()).throw(
                    PermissionError("Raw descriptor writes are unavailable in package-stage scratch")))

        def approved_popen(command, *args, **kwargs):
            if "subprocesses" not in permissions:
                raise PermissionError("Managed subprocess permission was not approved")
            if kwargs.get("shell"):
                raise PermissionError("Shell execution is unavailable")
            if not isinstance(command, (list, tuple)) or not command or any(not isinstance(item, str) for item in command):
                raise PermissionError("Managed subprocesses require an exact argument vector")
            executable = _normalized_executable(command[0])
            arguments = list(command[1:])
            match = next((index for index, spec in enumerate(child_specs)
                          if index not in used_specs and _normalized_executable(spec["executable"]) == executable
                          and spec["arguments"] == arguments), None)
            if match is None:
                raise PermissionError("Subprocess executable or arguments differ from the approved plan")
            used_specs.add(match)
            kwargs["shell"] = False
            kwargs["cwd"] = str(working)
            kwargs["env"] = dict(os.environ)
            process = real_popen(list(command), *args, **kwargs)
            spec = child_specs[match]
            _write_event(ledger, "child_started", pid=process.pid, spec_index=match,
                         persistent=spec["persistent"], purpose=spec["purpose"])
            return process

        subprocess.Popen = approved_popen
        original_import = builtins.__import__

        def approved_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and name.split(".", 1)[0] in {"keyring", "winreg"}:
                raise PermissionError("Credential and registry modules are unavailable")
            if package_scratch_active and level == 0 and name.split(".", 1)[0] in DENIED_NATIVE_FILE_MODULES:
                raise PermissionError("Native file stores and raw file access are unavailable in package stages")
            if level == 0 and name.split(".", 1)[0] == "copilot_agent" and name not in EXPOSED_APPLICATION_IMPORTS:
                raise PermissionError("Application module is not part of the approved Code Runner API: " + name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = approved_import
        sys.argv = [str(script_path), *user_arguments]
        namespace = {"__name__": "__main__", "__file__": str(script_path), "__package__": None,
                     "__builtins__": builtins.__dict__}
        try:
            exec(code, namespace, namespace)
        except BaseException:
            traceback.print_exc()
            _write_event(ledger, "worker_failed")
            return 1
        finally:
            subprocess.Popen = real_popen
            io.FileIO = original_file_io
            private_io.FileIO = original_private_file_io
            private_io.open = original_private_open
            builtins.__import__ = original_import
            io.open = original_io_open
            builtins.open = original_builtin_open
            for name, original in raw_write_functions.items():
                if original is not None:
                    setattr(os, name, original)
        _write_event(ledger, "worker_completed", used_subprocess_specs=sorted(used_specs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
