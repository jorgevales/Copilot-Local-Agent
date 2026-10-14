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
import sys
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


def get_cdp_version(endpoint: str, timeout: float = 0.75) -> dict | None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise EndpointError("CDP must use a loopback HTTP endpoint.")
    try:
        with _LOOPBACK_HTTP.open(endpoint + "/json/version", timeout=max(0.05, min(float(timeout), 0.75))) as response:
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


def _edge_listener_process(port: int) -> dict:
    """Return the proven Edge listener command without exposing it to callers."""
    if os.name != "nt":
        raise EndpointError("Existing-session profile ownership currently supports Windows only.")
    try:
        owner = loopback_listener_pid(int(port))
        if owner is None:
            raise EndpointError("The debugging listener owner is unavailable or ambiguous.")
        info = _windows_process_details(owner)
    except (OSError, ValueError, RuntimeError) as exc:
        raise EndpointError("Cannot prove the debugging port's dedicated profile ownership.") from exc
    line = info.get("CommandLine") or ""
    if info.get("Name", "").casefold() != "msedge.exe":
        raise EndpointError("The debugging listener is not Microsoft Edge.")
    port_match = re.search(r"--remote-debugging-port(?:=|\s+)(\d+)", line)
    if not port_match or int(port_match[1]) != int(port):
        raise EndpointError("Cannot prove the Edge debugging listener's local port.")
    return {'command_line': line, 'profile': _profile_argument(line)}


def _native_probe(kind, identifier):
    """A faulty native DLL must not terminate the agent's Python process."""
    command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('edge_native_probe.py')),
               kind, str(int(identifier))]
    output = _hidden_command(command, timeout=5)
    if len(output) > 262144:
        raise OSError('Native ownership probe returned an oversized response')
    result = json.loads(output)
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise OSError('Native ownership probe did not complete')
    return result['result']


def _windows_process_details(pid: int) -> dict:
    """Isolated native query, then independent CIM/WMI provider fallbacks."""
    if os.name != 'nt':
        raise OSError('Windows process inspection is unavailable')
    pid = int(pid)
    if not 1 <= pid <= 0xffffffff:
        raise ValueError('Invalid process identifier')
    try:
        result = _native_probe('process', pid)
        if not isinstance(result, dict) or not isinstance(result.get('Name'), str) or not isinstance(result.get('CommandLine'), str):
            raise ValueError('Malformed process probe')
        return result
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    for provider in ('Get-CimInstance', 'Get-WmiObject'):
        command = (f"$ErrorActionPreference='Stop'; {provider} Win32_Process -Filter \"ProcessId={pid}\" "
                   '| Select-Object Name,CommandLine | ConvertTo-Json -Compress')
        try:
            result = json.loads(_hidden_command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], timeout=4))
            if isinstance(result, dict) and isinstance(result.get('Name'), str) and isinstance(result.get('CommandLine'), str):
                return result
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    raise OSError('All process-ownership inspection routes failed; no browser identity was assumed')


def _decode_process_command(buffer, returned):
    """Decode only bytes inside the caller-owned native result allocation."""
    import ctypes
    class UnicodeString(ctypes.Structure):
        _fields_ = [('Length', ctypes.c_ushort), ('MaximumLength', ctypes.c_ushort),
                    ('Buffer', ctypes.c_void_p)]  # LPWSTR would dereference before validation.
    header_size = ctypes.sizeof(UnicodeString)
    returned = int(returned)
    if not header_size <= returned <= ctypes.sizeof(buffer):
        raise OSError('Process command-line response length was invalid')
    command = UnicodeString.from_buffer_copy(buffer)
    address = ctypes.addressof(buffer)
    offset = (command.Buffer or 0) - address
    if (not command.Length or command.Length % 2 or command.MaximumLength < command.Length
            or command.MaximumLength % 2 or offset < header_size or offset % 2
            or offset + command.Length > returned or offset + command.MaximumLength > ctypes.sizeof(buffer)):
        raise OSError('Process command-line pointer or length was outside the returned allocation')
    try:
        text = buffer.raw[offset:offset + command.Length].decode('utf-16-le', errors='strict')
    except UnicodeError as error:
        raise OSError('Process command line was not valid UTF-16') from error
    if '\x00' in text:
        raise OSError('Process command line contained an embedded terminator')
    return text


def _windows_process_details_native(pid: int) -> dict:
    """Read a process image and command line without privileged CIM/WMI access."""
    if os.name != "nt":
        raise OSError("Windows process inspection is unavailable")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    image_query = kernel32.QueryFullProcessImageNameW
    image_query.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                            ctypes.POINTER(wintypes.DWORD))
    image_query.restype = wintypes.BOOL
    handle = open_process(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        image = ctypes.create_unicode_buffer(32768)
        image_length = wintypes.DWORD(len(image))
        if not image_query(handle, 0, image, ctypes.byref(image_length)):
            raise ctypes.WinError(ctypes.get_last_error())

        command_buffer = ctypes.create_string_buffer(65536)
        returned = wintypes.ULONG()
        query = ntdll.NtQueryInformationProcess
        query.argtypes = (wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                          wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))
        query.restype = wintypes.LONG
        status = query(handle, 60, command_buffer, len(command_buffer), ctypes.byref(returned))
        if status < 0:
            raise OSError(f"Process command-line query failed with NTSTATUS 0x{status & 0xffffffff:08x}")
        return {"Name": Path(image.value).name,
                "CommandLine": _decode_process_command(command_buffer, returned.value)}
    finally:
        close_handle(handle)


def validate_edge_listener(port: int, profile: Path | None = None) -> Path | None:
    """Prove a local Edge CDP listener, optionally requiring one exact profile."""
    info = _edge_listener_process(port)
    actual_profile = info['profile']
    if profile is None:
        return actual_profile
    if actual_profile is None:
        raise EndpointError("The Edge debugging listener does not expose its profile identity.")
    actual = actual_profile.expanduser().resolve()
    try:
        first, second = os.stat(actual), os.stat(profile.expanduser().resolve())
        if first.st_ino and second.st_ino and os.path.samestat(first, second):
            return actual
    except OSError:
        pass
    if os.path.normcase(str(actual)) != os.path.normcase(str(profile.expanduser().resolve())):
        raise EndpointError("The debugging port belongs to a different Edge profile.")
    return actual


def validate_profile_ownership(port: int, profile: Path) -> None:
    """Fail closed when the exact listener/profile relationship cannot be proven."""
    validate_edge_listener(port, profile)


def discover_edge_debugging_endpoints() -> list[dict]:
    """Discover running Edge instances that explicitly expose loopback CDP."""
    if os.name != 'nt':
        return []
    command = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" "
               "| Where-Object { $_.CommandLine -match '--remote-debugging-port' } "
               "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    try:
        output = _hidden_command(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command])
        records = json.loads(output) if output.strip() else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    found = {}
    for record in records if isinstance(records, list) else [records]:
        line = record.get('CommandLine', '') if isinstance(record, dict) else ''
        match = re.search(r"--remote-debugging-port(?:=|\s+)(\d+)", line)
        if not match:
            continue
        port = int(match[1])
        if not 1024 <= port <= 65535:
            continue
        found.setdefault(port, {'port': port, 'profile': _profile_argument(line)})
    return [found[port] for port in sorted(found)]


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
    """Isolated TCP query, PowerShell TCP provider, then numeric netstat."""
    if os.name != 'nt':
        return None
    port = int(port)
    try:
        result = _native_probe('listener', port)
        if result is not None and (type(result) is not int or result <= 0):
            raise ValueError('Malformed listener probe')
        return result
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    command = (f"$ErrorActionPreference='Stop'; Get-NetTCPConnection -State Listen -LocalPort {port} "
               "| Where-Object { $_.LocalAddress -in @('127.0.0.1','::1','::ffff:127.0.0.1') } "
               '| Select-Object -ExpandProperty OwningProcess | ConvertTo-Json -Compress')
    try:
        output = _hidden_command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], timeout=4)
        values = json.loads(output) if output.strip() else []
        matches = set(values if isinstance(values, list) else [values])
        if any(type(pid) is not int or pid <= 0 for pid in matches):
            raise ValueError('Malformed TCP provider response')
        return next(iter(matches)) if len(matches) == 1 else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        pass
    try:
        output = _hidden_command(['netstat.exe', '-ano'], timeout=4)
        matches = set()
        for line in output.splitlines():
            fields = line.split()
            if (len(fields) == 5 and fields[0].upper() == 'TCP'
                    and fields[1] in {f'127.0.0.1:{port}', f'[::1]:{port}', f'[::ffff:127.0.0.1]:{port}'}
                    and fields[3].upper() == 'LISTENING' and fields[4].isdigit()):
                matches.add(int(fields[4]))
        return next(iter(matches)) if len(matches) == 1 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _loopback_listener_pid_native(port: int) -> int | None:
    """Read IPv4/IPv6 loopback listener owners without PowerShell/CIM privileges."""
    if os.name != "nt":
        return None
    import ctypes

    class Tcp4Row(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint32) for name in
                    ('state', 'local_address', 'local_port', 'remote_address', 'remote_port', 'pid')]

    query = ctypes.windll.iphlpapi.GetExtendedTcpTable
    query.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int32,
                      ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
    query.restype = ctypes.c_uint32
    matches = set()

    def read_table(family: int, row_type, is_ipv6: bool) -> bool:
        size = ctypes.c_uint32()
        if query(None, ctypes.byref(size), False, family, 3, 0) != 122 or not 4 <= size.value <= 4 * 1024 * 1024:
            return False
        buffer = ctypes.create_string_buffer(size.value)
        if query(buffer, ctypes.byref(size), False, family, 3, 0) != 0:
            return False
        if not 4 <= size.value <= ctypes.sizeof(buffer):
            return False
        count = ctypes.c_uint32.from_buffer_copy(buffer).value
        if 4 + count * ctypes.sizeof(row_type) > size.value:
            return False
        for index in range(count):
            row = row_type.from_buffer_copy(buffer, 4 + index * ctypes.sizeof(row_type))
            if row.state != 2 or socket.ntohs(row.local_port & 0xffff) != port:
                continue
            raw_address = (bytes(row.local_address) if is_ipv6 else
                           row.local_address.to_bytes(4, 'little'))
            address = socket.inet_ntop(socket.AF_INET6 if is_ipv6 else socket.AF_INET, raw_address)
            is_loopback = (address == '::1' or address.casefold() == '::ffff:127.0.0.1') if is_ipv6 else address == '127.0.0.1'
            if is_loopback:
                matches.add(row.pid)
        return True

    class Tcp6Row(ctypes.Structure):
        _fields_ = [('local_address', ctypes.c_ubyte * 16),
                    ('local_scope_id', ctypes.c_uint32), ('local_port', ctypes.c_uint32),
                    ('remote_address', ctypes.c_ubyte * 16), ('remote_scope_id', ctypes.c_uint32),
                    ('remote_port', ctypes.c_uint32), ('state', ctypes.c_uint32), ('pid', ctypes.c_uint32)]

    ipv4_ok = read_table(2, Tcp4Row, False)
    ipv6_ok = read_table(23, Tcp6Row, True)
    if not ipv4_ok and not ipv6_ok:
        raise OSError('Native TCP ownership tables were unavailable')
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
    """Start a detached Playwright owner for a visible, dedicated Edge profile."""
    profile = profile.expanduser().resolve()
    edge_path = Path(edge_path).expanduser().resolve()
    if remote_debugging_blocked():
        raise EndpointError("Microsoft Edge policy disables remote debugging. Ask your organization to permit it; the agent will not bypass this policy.")
    if profile_in_use(profile):
        raise EndpointError("The dedicated agent Edge profile is already open. Close that agent browser before retrying.")
    if port_listening(port):
        raise EndpointError("The selected local debugging port is already in use. Restart the agent to select a free port.")
    from .persistence import io_path
    io_path(profile).mkdir(parents=True, exist_ok=True)
    owner = Path(__file__).with_name('edge_owner.py').resolve()
    command = [sys.executable, str(owner), '--port', str(int(port)),
               '--profile', str(profile), '--edge-executable', str(edge_path)]
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


def direct_profile_candidates(profile):
    """Alternative launch spellings must identify the exact same profile."""
    profile = Path(profile).expanduser().resolve()
    result = [('direct Edge', profile, False)]
    if os.name == 'nt':
        from .persistence import io_path
        extended = io_path(profile)
        try:
            if str(extended) != str(profile) and os.path.samefile(extended, profile):
                result.append(('direct Edge using the verified extended Windows path', extended, False))
        except OSError:
            pass
        try:
            from .policy import mapped_s_drive_root
            share = mapped_s_drive_root().resolve()
            alias = Path('S:/') / profile.relative_to(share)
            if str(alias) != str(profile) and os.path.samefile(alias, profile):
                result.append(('direct Edge using the verified S: path', alias, False))
        except (OSError, ValueError, RuntimeError):
            pass
    result.append(('direct Edge with software graphics', profile, True))
    return result


def launch_edge_direct(edge_path, port, profile, *, software_graphics=False):
    """Launch installed Edge without a second Python/Playwright owner runtime."""
    from .persistence import io_path
    import uuid
    profile = Path(profile).expanduser().absolute()  # Preserve a verified S: alias.
    if remote_debugging_blocked():
        raise EndpointError('Microsoft Edge policy disables remote debugging; no alternate launch bypasses it.')
    if profile_in_use(profile):
        raise EndpointError('The dedicated agent Edge profile is already open; it was preserved.')
    if port_listening(port):
        raise EndpointError('The selected local debugging port is already in use; it was not replaced.')
    directory = io_path(profile)
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ('.edge-startup-' + uuid.uuid4().hex)
    try:
        with probe.open('xb') as stream:
            stream.write(b'Edge profile write/read check')
            stream.flush()
            os.fsync(stream.fileno())
        if probe.read_bytes() != b'Edge profile write/read check':
            raise OSError('Profile write readback failed')
    finally:
        probe.unlink(missing_ok=True)
    command = [str(Path(edge_path).expanduser().resolve()),
               f'--remote-debugging-port={int(port)}', '--remote-debugging-address=127.0.0.1',
               '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check', 'about:blank']
    if software_graphics:
        command.insert(-1, '--disable-gpu')
    options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
               'stderr': subprocess.DEVNULL, 'close_fds': True}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options['start_new_session'] = True
    try:
        return subprocess.Popen(command, **options)
    except OSError as error:
        raise EndpointError('Direct Microsoft Edge launch failed; profile files were retained.') from error


async def connect_bounded(playwright, endpoint: str, timeout: float, process=None, initial_payload=None,
                          endpoint_validator=None, endpoint_wait_timeout=None):
    """Bounded CDP startup with sanitized failure categories."""
    deadline = time.monotonic() + max(1, timeout)
    handshakes = 0
    endpoint_seen = False
    launched_exited = False
    exit_observed_at = None
    handshake_rejected = False
    first_payload = initial_payload
    started = time.monotonic()
    while time.monotonic() < deadline:
        if remote_debugging_blocked():
            raise EndpointError("Microsoft Edge policy disables remote debugging. Ask your organization to permit it; the agent will not bypass this policy.")
        if first_payload is not None:
            payload, first_payload = first_payload, None
        else:
            remaining = max(0.05, deadline - time.monotonic())
            payload = await asyncio.to_thread(get_cdp_version, endpoint, min(0.2, remaining))
        if payload:
            if not endpoint_seen:
                print('[System] Edge debugging endpoint is ready; connecting Playwright.')
            endpoint_seen = True
            websocket = validate_endpoint(endpoint, payload)
            if endpoint_validator is not None:
                await asyncio.to_thread(endpoint_validator)
                endpoint_validator = None
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
            exit_observed_at = exit_observed_at or time.monotonic()
            # Allow a brief child-process handoff, then let the caller rescan all
            # running Edge CDP endpoints instead of waiting the entire timeout.
            if time.monotonic() - exit_observed_at >= min(3.0, max(.05, timeout / 2)):
                break
        # A new local Edge listener normally appears quickly. Poll tightly at
        # first, then back off while preserving the same bounded startup window.
        elapsed = time.monotonic() - started
        if (not endpoint_seen and endpoint_wait_timeout is not None
                and elapsed >= endpoint_wait_timeout):
            break  # A live endpoint still receives the full handshake timeout.
        interval = 0.05 if elapsed < 2 else (0.1 if elapsed < 5 else 0.25)
        await asyncio.sleep(min(interval, max(0, deadline - time.monotonic())))
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
