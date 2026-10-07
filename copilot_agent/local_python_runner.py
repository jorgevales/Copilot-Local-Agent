"""Bounded host-process execution for an exact, explicitly approved local-Python plan."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .desktop import inspect_windows, launch_viewers
from .policy import PolicyError


MAX_EVIDENCE_BYTES = 50 * 1024 * 1024
EXPOSED_APPLICATION_IMPORTS = frozenset({"copilot_agent.desktop"})


def _hash_file(path: Path, maximum: int = MAX_EVIDENCE_BYTES) -> tuple[str, int]:
    digest, total = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(65536):
            total += len(block)
            if total > maximum:
                raise PolicyError("Evidence file exceeds the 50 MiB verification limit: " + str(path))
            digest.update(block)
    return digest.hexdigest(), total


def runtime_binding(plan: dict) -> dict:
    """Bind the reviewed interpreter and fixed runtime implementation."""
    package = Path(__file__).resolve().parent
    application_root = package.parent
    interpreter = Path(plan["interpreter"]).resolve()
    interpreter_hash, interpreter_size = _hash_file(interpreter, 200 * 1024 * 1024)
    files = [package / "local_python_worker.py", package / "__init__.py"]
    if "copilot_agent.desktop" in plan.get("imports", []) or plan.get("viewer_windows"):
        files.append(package / "desktop.py")
    if plan.get("viewer_windows"):
        files.append(package / "image_viewer.py")
    preflight = _preflight_imports(interpreter, application_root, plan.get("imports", []))
    return {"interpreter": str(interpreter), "interpreter_sha256": interpreter_hash,
            "interpreter_size": interpreter_size,
            "application_root": str(application_root), "import_preflight": preflight,
            "runtime_files": [{"path": str(path), "sha256": _hash_file(path)[0]} for path in files]}


def _preflight_imports(interpreter: Path, application_root: Path, imports: list[str]) -> dict:
    """Check declared modules in the exact isolated runtime before approval."""
    probe = (
        "import importlib.util,json,sys\n"
        "sys.path.insert(0,sys.argv[1])\n"
        "names=json.loads(sys.argv[2])\n"
        "missing=[name for name in names if importlib.util.find_spec(name) is None]\n"
        "if missing: raise ModuleNotFoundError(', '.join(missing))\n"
        "if 'copilot_agent.desktop' in names:\n"
        " from copilot_agent.desktop import enumerate_displays,capture_display\n"
        "print(json.dumps({'available':names}))\n")
    environment = _safe_environment(application_root)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(interpreter), "-I", "-c", probe, str(application_root), json.dumps(imports)],
            cwd=str(application_root), env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False,
            creationflags=flags)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PolicyError("Declared import preflight could not start in the approved runtime: " + type(exc).__name__) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
        summary = detail[-1][:500] if detail else "module unavailable"
        raise PolicyError("Declared import preflight failed before approval: " + summary)
    return {"ok": True, "imports": list(imports), "isolated_runtime": True}


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ctypes = __import__("ctypes")
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        available = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(available and exit_code.value == 259)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_pid(pid: int) -> bool:
    """Terminate only a PID recorded as created by this runner."""
    if not _pid_running(pid):
        return True
    try:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                           check=False, creationflags=flags)
            if _pid_running(pid):
                ctypes = __import__("ctypes")
                handle = ctypes.windll.kernel32.OpenProcess(0x0001 | 0x00100000, False, pid)
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    ctypes.windll.kernel32.WaitForSingleObject(handle, 3000)
                    ctypes.windll.kernel32.CloseHandle(handle)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            except OSError:
                os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _pid_running(pid):
            time.sleep(0.05)
        if os.name != "nt" and _pid_running(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        return False
    return not _pid_running(pid)


class ManagedProcessRegistry:
    """Own persistent children so session shutdown can clean them up."""
    def __init__(self, session_dir):
        self.session_dir = Path(session_dir).resolve()
        self.records: dict[int, dict] = {}
        self.path = self.session_dir / "managed-processes.json"

    def register(self, record: dict) -> None:
        pid = int(record["pid"])
        retained = {key: value for key, value in record.items() if key != "process"}
        retained["pid"] = pid
        self.records[pid] = retained
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": "1.0", "processes": list(self.records.values())}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def cleanup(self, records: list[dict]) -> list[dict]:
        outcomes = []
        for record in records:
            pid = int(record["pid"])
            stopped = _terminate_pid(pid)
            outcomes.append({"pid": pid, "stopped": stopped, "purpose": record.get("purpose", record.get("title", "managed child"))})
            self.records.pop(pid, None)
        self._save()
        return outcomes

    def cleanup_all(self) -> list[dict]:
        return self.cleanup(list(self.records.values()))


def _ledger_records(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _children(path: Path, plan: dict) -> list[dict]:
    result = []
    for event in _ledger_records(path):
        if event.get("event") != "child_started" or type(event.get("pid")) is not int:
            continue
        index = event.get("spec_index")
        if type(index) is not int or not 0 <= index < len(plan["subprocesses"]):
            continue
        spec = plan["subprocesses"][index]
        result.append({"pid": event["pid"], "persistent": spec["persistent"], "purpose": spec["purpose"],
                       "executable": spec["executable"], "arguments": spec["arguments"], "spec_index": index})
    return result


async def _terminate_main(process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        await asyncio.to_thread(_terminate_pid, process.pid)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), 2)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        await asyncio.wait_for(process.wait(), 3)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def _read_bounded(stream, limit: int) -> bytes:
    collected = bytearray()
    while True:
        block = await stream.read(4096)
        if not block:
            return bytes(collected)
        collected.extend(block)
        if len(collected) > limit:
            raise PolicyError("Process output exceeded the approved limit")


def _safe_environment(working: Path) -> dict[str, str]:
    allowed = {"SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
                        "COPILOT_APPROVED_WORKING_DIRECTORY": str(working)})
    return environment


async def execute_local_python(plan: dict, prepared: dict, session_dir: Path,
                               process_registry: ManagedProcessRegistry | None = None) -> dict:
    """Execute one exact local-Python proposal and independently verify effects."""
    registry = process_registry or ManagedProcessRegistry(session_dir)
    run_id = uuid.uuid4().hex
    run_dir = Path(session_dir) / "code_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    plan_path, ledger_path, audit_path = run_dir / "worker-plan.json", run_dir / "children.jsonl", run_dir / "audit.json"
    worker_plan = {key: plan[key] for key in ("working_directory", "read_paths", "create_paths", "modify_paths",
                                               "network_destinations", "permissions", "subprocesses", "arguments", "imports")}
    worker_plan["script_sha256"] = prepared["script_sha256"]
    worker_plan["application_root"] = prepared["runtime_binding"]["application_root"]
    plan_path.write_text(json.dumps(worker_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    worker = Path(__file__).with_name("local_python_worker.py").resolve()
    command = [plan["interpreter"], "-I", str(worker), str(plan_path), prepared["script_path"], str(ledger_path), *plan["arguments"]]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = None
    started = time.monotonic()
    status, error, stdout, stderr = "failed", None, b"", b""
    viewers: list[dict] = []
    cleanup: list[dict] = []
    verification = {"ok": True, "display_count": None, "displays": [], "windows": []}
    try:
        for path in plan["create_paths"]:
            if Path(path).exists():
                raise PolicyError("Approved create target already exists; execution requires a fresh plan: " + path)
        process = await asyncio.create_subprocess_exec(*command, cwd=plan["working_directory"],
            env=_safe_environment(Path(plan["working_directory"])), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=flags, start_new_session=os.name != "nt")
        try:
            stdout, stderr, _ = await asyncio.wait_for(asyncio.gather(
                _read_bounded(process.stdout, plan["max_output_chars"]),
                _read_bounded(process.stderr, plan["max_output_chars"]), process.wait()),
                timeout=plan["timeout_seconds"])
            if len(stdout) + len(stderr) > plan["max_output_chars"]:
                raise PolicyError("Combined process output exceeded the approved limit")
            status = "completed" if process.returncode == 0 else "failed"
            if process.returncode != 0:
                error = "Approved local Python exited with code " + str(process.returncode)
        except asyncio.TimeoutError:
            status, error = "cancelled", "Approved runtime limit expired; owned processes were stopped"
            await _terminate_main(process)
        except PolicyError as exc:
            status, error = "failed", str(exc)
            await _terminate_main(process)
    except asyncio.CancelledError:
        if process is not None:
            await _terminate_main(process)
        children = _children(ledger_path, plan)
        cleanup.extend(await asyncio.to_thread(registry.cleanup, children))
        audit = {"schema_version": "1.0", "run_id": run_id, "status": "cancelled",
                 "proposal_hash": prepared["proposal_hash"], "script_sha256": prepared["script_sha256"],
                 "runtime_binding": prepared["runtime_binding"], "cleanup": cleanup,
                 "duration_seconds": round(time.monotonic() - started, 4)}
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    except Exception as exc:
        status, error = "failed", str(exc)
        if process is not None:
            await _terminate_main(process)

    children = _children(ledger_path, plan)
    if status == "completed" and plan["viewer_windows"]:
        try:
            viewers = await asyncio.to_thread(launch_viewers, plan["viewer_windows"], plan["interpreter"])
            verification = await asyncio.to_thread(inspect_windows, plan["viewer_windows"])
            if not verification["ok"]:
                status, error = "failed", "Post-run verification did not find every approved visible viewer on its target display"
        except Exception as exc:
            status, error = "failed", "Viewer launch or verification was blocked: " + str(exc)

    managed_viewers = [{"pid": item["pid"], "persistent": True, "purpose": "Persistent approved image viewer",
                        "title": item["title"], "display_index": item["display_index"],
                        "image_path": item["image_path"]} for item in viewers]
    all_children = [*children, *managed_viewers]
    if status == "completed":
        for child in all_children:
            if child.get("persistent"):
                registry.register(child)
            elif _pid_running(child["pid"]):
                cleanup.extend(await asyncio.to_thread(registry.cleanup, [child]))
    else:
        cleanup.extend(await asyncio.to_thread(registry.cleanup, all_children))

    outputs, missing = [], []
    for value in plan["expected_outputs"]:
        path = Path(value)
        try:
            digest, size = _hash_file(path)
            outputs.append({"path": str(path), "size": size, "sha256": digest, "readable": True,
                            "expected": True})
        except (OSError, PolicyError) as exc:
            outputs.append({"path": str(path), "readable": False, "expected": True, "error": str(exc)})
            missing.append(str(path))
    if missing and status == "completed":
        status, error = "failed", "One or more approved expected outputs were not independently readable"
        cleanup.extend(await asyncio.to_thread(registry.cleanup, [child for child in all_children if child.get("persistent")]))

    # A failed create-only desktop attempt is safe to recover automatically when
    # retained evidence proves that it created no declared files or processes.
    create_targets_absent = all(not Path(value).exists() for value in plan["create_paths"])
    cleanup_complete = all(item.get("stopped") or item.get("already_stopped") for item in cleanup)
    effects_certain = (status == "failed" and not plan["modify_paths"] and not plan["network_destinations"]
                       and not plan["subprocesses"] and create_targets_absent and not all_children
                       and cleanup_complete)

    decoded_stdout = stdout.decode("utf-8", errors="replace")
    decoded_stderr = stderr.decode("utf-8", errors="replace")
    result = {"status": status, "proposal_hash": prepared["proposal_hash"],
              "script_sha256": prepared["script_sha256"], "interpreter": plan["interpreter"],
              "arguments": plan["arguments"], "stdout": decoded_stdout, "stderr": decoded_stderr,
              "output": decoded_stdout, "exit_code": process.returncode if process and process.returncode is not None else None,
              "duration_seconds": round(time.monotonic() - started, 4), "outputs": outputs,
              "created_paths": [item["path"] for item in outputs if item.get("readable")],
              "missing_outputs": missing, "managed_processes": [{key: value for key, value in item.items() if key != "process"}
                                                              for item in all_children],
              "verification": verification, "cleanup": cleanup, "audit_path": str(audit_path),
              "runtime_binding": prepared["runtime_binding"],
              "side_effects_uncertain": False if effects_certain else status != "completed"}
    if error:
        result["error"] = error
    audit = {"schema_version": "1.0", "run_id": run_id, "plan": plan,
             "prepared": prepared, "result": result, "worker_events": _ledger_records(ledger_path)}
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
