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
import subprocess
import time
import urllib.request
from urllib.parse import urlparse


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
        with urllib.request.urlopen(endpoint + "/json/version", timeout=0.75) as response:
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
    profile_match = re.search(r'--user-data-dir(?:=|\s+)(?:"([^"]+)"|(\S+))', line)
    if not port_match or int(port_match[1]) != int(port) or not profile_match:
        raise EndpointError("Cannot prove the debugging listener's dedicated profile.")
    actual = Path(profile_match[1] or profile_match[2]).expanduser().resolve()
    if os.path.normcase(str(actual)) != os.path.normcase(str(profile.expanduser().resolve())):
        raise EndpointError("The debugging port belongs to a different Edge profile.")


def launch_edge(edge_path: Path, port: int, profile: Path) -> subprocess.Popen:
    """Start visible detached Edge; leave browser and profile intact on all outcomes."""
    profile = profile.expanduser().resolve()
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
    return subprocess.Popen(command, **options)


async def connect_bounded(playwright, endpoint: str, timeout: float):
    """Sequential fresh WebSocket/HTTP handshakes under one hard deadline."""
    deadline = time.monotonic() + max(1, timeout)
    attempts = 0
    while time.monotonic() < deadline:
        payload = await asyncio.to_thread(get_cdp_version, endpoint)
        if payload:
            websocket = validate_endpoint(endpoint, payload)
            routes = [websocket, endpoint] if attempts % 2 == 0 else [endpoint, websocket]
            for route in routes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    browser = await asyncio.wait_for(
                        playwright.chromium.connect_over_cdp(route, timeout=int(min(8, remaining) * 1000)),
                        timeout=remaining)
                    if browser.is_connected() and browser.contexts:
                        return browser
                except Exception:
                    pass
        attempts += 1
        await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise EndpointError("Edge's CDP handshake did not complete within the startup timeout.")


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
