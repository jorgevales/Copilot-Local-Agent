"""Bounded child-only Windows ownership queries; never run agent actions."""
import json
import os
from pathlib import Path
import sys


def suppress_fault_dialogs():
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.SetErrorMode.argtypes = (ctypes.c_uint,)
        kernel.SetErrorMode.restype = ctypes.c_uint
        kernel.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def main():
    suppress_fault_dialogs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from copilot_agent.reused_browser import _windows_process_details_native, _loopback_listener_pid_native
    try:
        kind, value = sys.argv[1], int(sys.argv[2])
        if kind not in {'process', 'listener'}:
            raise ValueError('Unknown query')
        result = (_windows_process_details_native(value) if kind == 'process' else
                  _loopback_listener_pid_native(value))
        print(json.dumps({'ok': True, 'result': result}))
        return 0
    except Exception:
        print(json.dumps({'ok': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
