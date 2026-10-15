"""Small functional fixtures for bundled REA; no network or browser creation."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import queue
import struct
import tempfile
import threading
import zipfile


def _managed_fixture():
    image = bytearray(2048)
    image[:2] = b'MZ'
    struct.pack_into('<I', image, 0x3c, 0x80)
    image[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', image, 0x84, 0x8664, 1)
    struct.pack_into('<H', image, 0x94, 240)
    struct.pack_into('<H', image, 0x98, 0x20b)
    struct.pack_into('<II', image, 0x98 + 112 + 14 * 8, 0x2000, 72)
    struct.pack_into('<IIII', image, 0x188 + 8, 0x1000, 0x2000, 0x600, 0x200)
    struct.pack_into('<II', image, 0x208, 0x2080, 0x400)
    root = 0x280
    image[root:root + 4] = b'BSJB'
    struct.pack_into('<I', image, root + 12, 4)
    image[root + 16:root + 20] = b'v4\0\0'
    struct.pack_into('<HH', image, root + 20, 0, 2)
    struct.pack_into('<II', image, root + 24, 0x80, 0x80)
    image[root + 32:root + 36] = b'#~\0\0'
    struct.pack_into('<II', image, root + 36, 0x180, 0x80)
    image[root + 44:root + 56] = b'#Strings\0\0\0\0'
    table = root + 0x80
    struct.pack_into('<Q', image, table + 8, 1 << 2)
    struct.pack_into('<I', image, table + 24, 1)
    struct.pack_into('<IHHHHH', image, table + 28, 1, 1, 7, 0, 1, 1)
    names = b'\0Probe\0SelfCheck\0'
    image[root + 0x180:root + 0x180 + len(names)] = names
    return bytes(image)


class _FixtureOwnedPage:
    """Exercise passive collection and listener cleanup, without any real page."""
    url = 'https://rea-selfcheck.invalid/'
    frames = []

    def __init__(self):
        self.listeners = {}

    def on(self, event, callback):
        self.listeners[event] = callback

    def remove_listener(self, event, callback):
        if self.listeners.pop(event) is not callback:
            raise ValueError('Listener contract mismatch')

    async def evaluate(self, script):
        if not isinstance(script, str) or 'document.createTreeWalker' not in script:
            raise ValueError('Passive structural snapshot unavailable')
        return {'url': self.url, 'ready_state': 'complete',
                'dom': {'tags': {'main': 1}, 'roles': {}, 'input_types': {},
                        'visited_elements': 1, 'truncated': False},
                'navigation': [self.url + 'api/status'], 'forms': [], 'scripts': [],
                'resources': [], 'framework_hints': []}


def functional_checks(project=None):
    from .rea_python_capture import analyze_capture
    from .rea_python_artifacts import analyze_artifact
    from .rea_python_page import inspect_page
    from .rea_readiness import scratch_directory
    with scratch_directory(project) as root:
        capture = root / 'probe.har'
        capture.write_text(json.dumps({'log': {'entries': [{
            'request': {'method': 'GET', 'url': 'https://rea-selfcheck.invalid/api/status'},
            'response': {'status': 200, 'content': {'mimeType': 'application/json'}},
            'time': 1}]}}), encoding='utf-8')
        har = analyze_capture(capture, 'har')
        if har['findings']['analyzed_request_count'] != 1 or har['findings']['methods'] != {'GET': 1}:
            raise ValueError('HAR parser functional check failed')
        saz_path = root / 'probe.saz'
        with zipfile.ZipFile(saz_path, 'w') as archive:
            archive.writestr('raw/1_c.txt', b'GET /api/status HTTP/1.1\r\nHost: rea-selfcheck.invalid\r\n\r\n')
            archive.writestr('raw/1_s.txt', b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}')
        saz = analyze_capture(saz_path, 'saz')
        if saz['findings']['analyzed_request_count'] != 1:
            raise ValueError('SAZ parser functional check failed')
        source = root / 'probe.js'
        source.write_text('export function ready() { return fetch("/api/status"); }', encoding='utf-8')
        js = analyze_artifact(source, 'javascript')
        if not any(value['name'] == 'ready' for value in js['findings']['exports']):
            raise ValueError('JavaScript parser functional check failed')
        binary = root / 'probe.bin'
        binary.write_bytes(_managed_fixture())
        managed = analyze_artifact(binary, 'managed')
        if not any(value['name'] == 'Probe' for value in managed['findings']['types']):
            raise ValueError('Managed metadata parser functional check failed')
        binary.write_bytes(b'\x7fELF\x02\0go1.24.2\0net/http.Client\0')
        go = analyze_artifact(binary, 'go')
        if '1.24.2' not in go['findings'].get('go_versions', []):
            raise ValueError('Go metadata parser functional check failed')
        binary.write_bytes(b'\x7fELF\x02\0rustc 1.80.0\0std::panic::run\0')
        rust = analyze_artifact(binary, 'rust')
        if '1.80.0' not in rust['findings'].get('rustc_versions', []):
            raise ValueError('Rust metadata parser functional check failed')
        page = _FixtureOwnedPage()
        page_result = asyncio.run(inspect_page(page, observation_ms=0))
        if page.listeners or page_result['findings']['dom']['tag_counts'] != {'main': 1}:
            raise ValueError('Passive page collector functional check failed')
    return {
        'rea.inspect_page': {'status': 'verified', 'check': 'Passive collector processes a synthetic owned-page adapter and removes its listener; real browser access is validated at invocation.'},
        'rea.analyze_capture': {'status': 'verified', 'check': 'HAR and SAZ synthetic request/response parser checks passed.'},
        'rea.analyze_artifact': {'status': 'verified', 'check': 'JavaScript exports, valid managed metadata, Go and Rust compiler-marker checks passed.'}}


def run_functional_checks(project=None):
    """Health is called inside existing event loops; keep its fixture loop separate."""
    result = queue.Queue(maxsize=1)

    def run():
        try:
            result.put((True, functional_checks(project)))
        except Exception as error:
            result.put((False, error))

    worker = threading.Thread(target=run, name='rea-python-readiness', daemon=True)
    worker.start()
    worker.join(timeout=10)
    if worker.is_alive():
        raise TimeoutError('Bundled REA functional self-check did not finish within ten seconds')
    success, value = result.get_nowait()
    if not success:
        raise value
    return value
