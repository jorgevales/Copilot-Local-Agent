"""Narrow, provenance-recorded Edge helpers, with no CDD engine import.

Refactored from resources/implementation_sanitized.py in the existing Documents
review workflow. See docs/REUSE_MAPPING.md. No workflow, cleanup, credential,
process termination, or filesystem deletion code is carried across.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from urllib.parse import urlparse

_LOOPBACK_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class EndpointError(RuntimeError):
    pass


def cdp_endpoint(port: int) -> str:
    if not 1024 <= int(port) <= 65535:
        raise EndpointError("Choose an unprivileged local debugging port (1024-65535).")
    return f"http://127.0.0.1:{int(port)}"


def get_cdp_version(endpoint: str) -> dict | None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise EndpointError("CDP must use a loopback HTTP endpoint.")
    try:
        with _LOOPBACK_HTTP.open(endpoint + "/json/version", timeout=0.75) as response:
            payload = json.loads(response.read(65536).decode("utf-8"))
        return payload if isinstance(payload, dict) and payload.get("webSocketDebuggerUrl") else None
    except (OSError, ValueError):
        return None


def validate_endpoint(endpoint: str, payload: dict) -> str:
    expected = urlparse(endpoint)
    ws = urlparse(str(payload.get("webSocketDebuggerUrl", "")))
    if ws.scheme != "ws" or ws.hostname not in {"127.0.0.1", "localhost"} or ws.port != expected.port:
        raise EndpointError("CDP returned an address outside the requested local port.")
    if "edg/" not in str(payload.get("Browser", "")).lower():
        raise EndpointError("The debugging port does not advertise Microsoft Edge.")
    return ws.geturl()


def find_edge_executable(explicit_path=None) -> Path:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("The configured Microsoft Edge executable does not exist.")
        return path
    if os.name == "nt":
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                path = Path(root) / "Microsoft/Edge/Application/msedge.exe"
                if path.is_file():
                    return path
    for command in ("msedge", "microsoft-edge", "microsoft-edge-stable"):
        found = shutil.which(command)
        if found:
            return Path(found).resolve()
    raise FileNotFoundError("Microsoft Edge was not found. Configure edge_executable.")


def _hidden_command(command: list[str], timeout=8) -> str:
    options = {"capture_output": True, "text": True, "timeout": timeout, "check": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(command, **options).stdout


def validate_profile_ownership(port: int, profile: Path) -> None:
    """Fail closed when the exact listener/profile relationship cannot be proven."""
    if os.name != "nt":
        raise EndpointError("Existing-session profile ownership currently supports Windows only.")
    # Constant PowerShell script, numeric port only; profile never enters shell code.
    script = (
        f"$owner = Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction Stop "
        "| Select-Object -ExpandProperty OwningProcess -Unique; "
        "if (@($owner).Count -ne 1) { throw 'Listener ownership is ambiguous' }; "
        "Get-CimInstance Win32_Process -Filter ('ProcessId=' + $owner) "
        "| Select-Object Name,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        info = json.loads(_hidden_command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise EndpointError("Cannot prove the debugging port's dedicated profile ownership.") from exc
    line = info.get("CommandLine") or ""
    if info.get("Name", "").casefold() != "msedge.exe":
        raise EndpointError("The debugging listener is not Microsoft Edge.")
    port_match = re.search(r"--remote-debugging-port(?:=|\s+)(\d+)", line)
    actual_profile = _profile_argument(line)
    if not port_match or int(port_match[1]) != int(port) or actual_profile is None:
        raise EndpointError("Cannot prove the debugging listener's dedicated profile.")
    actual = actual_profile.expanduser().resolve()
    if os.path.normcase(str(actual)) != os.path.normcase(str(profile.expanduser().resolve())):
        raise EndpointError("The debugging port belongs to a different Edge profile.")


def _profile_argument(command_line: str) -> Path | None:
    # Windows quotes the entire --user-data-dir=... argument when it has spaces.
    match = re.search(r'"--user-data-dir=([^"]+)"|--user-data-dir(?:=|\s+)(?:"([^"]+)"|(\S+))', command_line)
    return Path(next(value for value in match.groups() if value)) if match else None


def remote_debugging_blocked() -> bool:
    """Read the effective Windows Edge policy when it explicitly disables CDP."""
    if os.name != "nt":
        return False
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Policies\Microsoft\Edge") as key:
                value, _ = winreg.QueryValueEx(key, "RemoteDebuggingAllowed")
                if value == 0:
                    return True
        except OSError:
            continue
    return False


def port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.4):
            return True
    except OSError:
        return False


def loopback_listener_pid(port: int) -> int | None:
    """Read the Windows TCP listener owner without PowerShell/CIM privileges."""
    if os.name != "nt":
        return None
    import ctypes

    class TcpRow(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint32) for name in
                    ('state', 'local_address', 'local_port', 'remote_address', 'remote_port', 'pid')]

    query = ctypes.windll.iphlpapi.GetExtendedTcpTable
    size = ctypes.c_uint32()
    if query(None, ctypes.byref(size), False, 2, 3, 0) != 122 or not 4 <= size.value <= 4 * 1024 * 1024:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if query(buffer, ctypes.byref(size), False, 2, 3, 0) != 0:
        return None
    count = ctypes.c_uint32.from_buffer_copy(buffer).value
    if 4 + count * ctypes.sizeof(TcpRow) > size.value:
        return None
    matches = set()
    for index in range(count):
        row = TcpRow.from_buffer_copy(buffer, 4 + index * ctypes.sizeof(TcpRow))
        if (row.state == 2 and socket.ntohs(row.local_port & 0xffff) == port and
                socket.inet_ntoa(row.local_address.to_bytes(4, 'little')) == '127.0.0.1'):
            matches.add(row.pid)
    return next(iter(matches)) if len(matches) == 1 else None


def validate_launched_endpoint(port: int, profile: Path, process: subprocess.Popen | None) -> None:
    """Prove a fresh listener belongs to this run, or use exact profile inspection."""
    if process is not None and process.poll() is None and loopback_listener_pid(port) == process.pid:
        return
    validate_profile_ownership(port, profile)


def profile_in_use(profile: Path) -> bool:
    """Check whether another Edge command already owns this exact dedicated profile."""
    if os.name != "nt" or not profile.is_dir():
        return False
    command = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" "
               "| Where-Object { $_.CommandLine -match '--user-data-dir' } "
               "| Select-Object CommandLine | ConvertTo-Json -Compress")
    try:
        output = _hidden_command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command])
        records = json.loads(output) if output.strip() else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return False  # Ownership is checked again after CDP becomes available.
    for record in records if isinstance(records, list) else [records]:
        line = record.get("CommandLine", "") if isinstance(record, dict) else ""
        actual = _profile_argument(line)
        if actual:
            try:
                if os.path.normcase(str(actual.resolve())) == os.path.normcase(str(profile.resolve())):
                    return True
            except OSError:
                pass
    return False


def launch_edge(edge_path: Path, port: int, profile: Path) -> subprocess.Popen:
    """Start visible Edge with a dedicated profile; never touch ordinary windows."""
    profile = profile.expanduser().resolve()
    if remote_debugging_blocked():
        raise EndpointError("Microsoft Edge policy disables remote debugging. Ask your organization to permit it; the agent will not bypass this policy.")
    if profile_in_use(profile):
        raise EndpointError("The dedicated agent Edge profile is already open. Close that agent browser before retrying.")
    if port_listening(port):
        raise EndpointError("The selected local debugging port is already in use. Restart the agent to select a free port.")
    profile.mkdir(parents=True, exist_ok=True)
    command = [str(edge_path), f"--remote-debugging-port={int(port)}",
               "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}",
               "--no-first-run", "--no-default-browser-check", "--new-window", "about:blank"]
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
               "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    try:
        return subprocess.Popen(command, **options)
    except OSError as exc:
        raise EndpointError("Microsoft Edge could not be started. Check the Edge installation and local execution policy.") from exc


def stop_launched_edge(process: subprocess.Popen | None) -> None:
    """Stop only the process handle returned by this run's Popen call."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    except OSError:
        pass


async def connect_bounded(playwright, endpoint: str, timeout: float, process=None):
    """Bounded CDP startup with sanitized failure categories."""
    deadline = time.monotonic() + max(1, timeout)
    handshakes = 0
    endpoint_seen = False
    launched_exited = False
    handshake_rejected = False
    while time.monotonic() < deadline:
        if remote_debugging_blocked():
            raise EndpointError("Microsoft Edge policy disables remote debugging. Ask your organization to permit it; the agent will not bypass this policy.")
        payload = await asyncio.to_thread(get_cdp_version, endpoint)
        if payload:
            if not endpoint_seen:
                print('[System] Edge debugging endpoint is ready; connecting Playwright.')
            endpoint_seen = True
            websocket = validate_endpoint(endpoint, payload)
            # The reference workflow found browser target enumeration can exceed 8s.
            remaining = deadline - time.monotonic()
            if remaining > 0:
                route = websocket if handshakes % 2 == 0 else endpoint
                budget = min((5, 10, 20, 30)[min(handshakes, 3)], remaining)
                handshakes += 1
                try:
                    browser = await asyncio.wait_for(
                        playwright.chromium.connect_over_cdp(route, timeout=max(1000, int(budget * 1000))),
                        timeout=budget + 0.25)
                    if browser.is_connected() and browser.contexts:
                        return browser
                except Exception as exc:
                    # Classify a rejection, but never display the raw Playwright
                    # exception: it may contain URLs, profile paths or IDs.
                    detail = str(exc).casefold()
                    handshake_rejected |= '403' in detail or 'forbidden' in detail or 'origin not allowed' in detail
                if handshakes == 1:
                    print('[System] Edge responded, but the first browser handshake did not complete; retrying within the startup limit.')
        elif process is not None and process.poll() is not None:
            launched_exited = True  # Edge may hand off to a child; keep the full startup window.
        await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
    if endpoint_seen:
        if handshake_rejected:
            raise EndpointError("Edge's debugging endpoint rejected Playwright's connection. Check organizational browser security policy; the agent will not bypass it.")
        raise EndpointError("Edge's debugging endpoint responded, but Playwright could not complete the browser handshake within the startup limit. The browser may be slow or a local security control may block the connection.")
    if remote_debugging_blocked():
        raise EndpointError("Microsoft Edge policy disables remote debugging. Ask your organization to permit it; the agent will not bypass this policy.")
    if port_listening(urlparse(endpoint).port):
        raise EndpointError("The selected local port is occupied, but it is not serving an Edge debugging endpoint. Restart the agent to choose another port.")
    if launched_exited:
        raise EndpointError("Edge exited before opening its debugging endpoint. Check the dedicated profile and organizational Edge launch policy.")
    raise EndpointError("Edge started but did not open a debugging endpoint before the startup limit. Check Edge remote-debugging policy and the dedicated profile.")


EDITOR_SELECTORS = (
    "#m365-chat-editor-target-element",
    "[data-testid*='chat-editor' i] [contenteditable='true']",
    "[data-test-id*='chat-editor' i] [contenteditable='true']",
    "[role='textbox'][contenteditable='true'][aria-label*='Copilot' i]",
    "[role='textbox'][aria-label*='Message' i]",
    "textarea[aria-label*='Copilot' i]",
    "textarea[placeholder*='message' i]",
    "main [contenteditable='true'][role='textbox']",
)
PICKER_SELECTOR = "#gptModeSwitcher,button[aria-label*='Model Selector' i],button[aria-label*='mode selector' i]"
SEND_SELECTOR = ('button[aria-label="Send"],button[aria-label^="Send "]:not([aria-label*="stop" i]),'
                 'button[type="submit"][aria-label*="send" i]:not([aria-label*="stop" i])')
ATTACH_SELECTOR = ("#plus-menu-container button[data-testid='PlusMenuButton'],"
                   "button[data-testid='chat-input-attach-button'],"
                   "button[data-test-id='chat-input-attach-button'],"
                   "button[aria-label='Add and manage sources']")
