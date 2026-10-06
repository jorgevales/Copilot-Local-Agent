"""Fixed worker for an explicitly approved local-Python plan.

This process is defense in depth, not an operating-system sandbox.  The host
validates and hashes the complete plan before launch; this worker repeats the
important runtime checks and records every managed child process immediately.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import traceback
from urllib.parse import urlsplit


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
    package_parent = str(Path(__file__).resolve().parents[1])
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)
    working = Path(plan["working_directory"]).resolve()
    os.chdir(working)
    read_scopes = [Path(item).resolve() for item in plan["read_paths"]]
    create_scopes = [Path(item).resolve() for item in plan["create_paths"]]
    modify_scopes = [Path(item).resolve() for item in plan["modify_paths"]]
    runtime_roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), Path(__file__).resolve().parent]
    permissions = set(plan["permissions"])
    destinations = set()
    for item in plan["network_destinations"]:
        parsed = urlsplit(item)
        destinations.add((parsed.hostname.casefold(), parsed.port or 443))
    child_specs = plan["subprocesses"]
    used_specs: set[int] = set()
    real_popen = subprocess.Popen
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8", newline="\n") as ledger:
        _write_event(ledger, "worker_started", pid=os.getpid())

        def audit(event, args):
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
                    raise PermissionError("File write is outside the approved create/modify scope: " + str(candidate))
                if _within(candidate, read_scopes) or _within(candidate, create_scopes + modify_scopes) or _within(candidate, runtime_roots):
                    return
                raise PermissionError("File read is outside the approved scope: " + str(candidate))
            if event in {"os.remove", "os.rmdir", "os.rename", "os.replace", "shutil.rmtree"}:
                raise PermissionError("Deletion and rename operations are unavailable in approved local Python")
            if event in {"os.listdir", "os.scandir"}:
                candidate = Path(args[0] if args and args[0] is not None else working)
                candidate = (working / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                if not (_within(candidate, read_scopes) or _within(candidate, runtime_roots)):
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
            builtins.__import__ = original_import
        _write_event(ledger, "worker_completed", used_subprocess_specs=sorted(used_specs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
