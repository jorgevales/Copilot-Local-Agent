"""Fixed, owned read-only analysis worker; never executes the supplied artifact."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time


def main():
    if len(sys.argv) != 7 or sys.argv[1] not in {'capture', 'artifact'}:
        return 2
    operation, kind, supplied, seconds, max_input, max_output = sys.argv[1:]
    if kind not in ({'har', 'saz'} if operation == 'capture' else {'managed', 'go', 'rust', 'javascript'}):
        return 2
    deadline = time.monotonic() + min(180, max(.01, float(seconds)))
    byte_limit, output_limit = min(104857600, int(max_input)), min(8388608, int(max_output))
    target = Path(supplied)
    total, count = 0, 0

    def budget():
        if time.monotonic() >= deadline:
            raise TimeoutError('Analysis deadline reached')

    # The parent already admitted and hash-verified the immutable snapshot.
    # Recheck bounds in the worker before any parser materializes its input.
    pending = [target]
    while pending:
        budget()
        item = pending.pop()
        count += 1
        if count > 2001 or item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            return 2
        if item.is_dir():
            pending.extend(item.iterdir())
        else:
            total += item.stat().st_size
            if total > byte_limit:
                return 2
    from .rea_backends import PythonNativeREABackend
    backend = PythonNativeREABackend()
    prepared = {'snapshot': supplied, '_arguments': {'format' if operation == 'capture' else 'kind': kind}}
    try:
        result = asyncio.run((backend.analyze_capture if operation == 'capture' else backend.analyze_artifact)(
            prepared, {'_rea_budget': budget}))
    except TimeoutError:
        result = {'status': 'timeout', 'side_effects_uncertain': False,
                  'limitations': ['The bounded static analysis deadline was reached.']}
    except (ValueError, OSError, UnicodeError, RecursionError, KeyError, TypeError) as error:
        result = {'status': 'failed', 'side_effects_uncertain': False,
                  'error': {'code': 'invalid_input', 'message': type(error).__name__},
                  'limitations': ['No complete analysis is claimed for malformed or unsupported bytes.']}
    payload = json.dumps(result, ensure_ascii=True, allow_nan=False).encode('utf-8')
    if len(payload) > output_limit:
        payload = b'{"status":"output_limit","side_effects_uncertain":false,"limitations":["Analysis exceeded the output budget."]}'
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
