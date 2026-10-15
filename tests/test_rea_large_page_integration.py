"""Explicit local upstream-REA/owned-Edge proof for a page over the chat budget."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest

from copilot_agent.policy import PathPolicy
from copilot_agent.rea import execute_rea


@unittest.skipUnless(os.environ.get('COPILOT_REA_INTEGRATION') == '1',
                     'Explicit installed REA and Edge integration gate; no downloads')
class REALargePageIntegrationTests(unittest.TestCase):
    def test_real_node_inspection_retains_large_evidence_without_fallback(self):
        from playwright.async_api import async_playwright
        from copilot_agent.browser import BrowserAdapter

        async def run():
            with tempfile.TemporaryDirectory(prefix='rea-large-page-') as directory:
                root = Path(directory)
                with socket.socket() as reserve:
                    reserve.bind(('127.0.0.1', 0))
                    port = reserve.getsockname()[1]
                async with async_playwright() as playwright:
                    native = await playwright.chromium.launch(channel='msedge', headless=True,
                        args=['--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={port}'])
                    try:
                        browser = BrowserAdapter(SimpleNamespace(allowed_domains=['fixture.test'], debug_port=port))
                        browser.browser = native
                        browser.tool_context = await native.new_context(service_workers='block')
                        browser.context = browser.tool_context
                        browser.tool_page = await browser.tool_context.new_page()
                        await browser._configure_tool_context(browser.tool_page)
                        label = 'Synthetic navigation fixture action with structural evidence only '
                        body = '<title>REA large synthetic page</title><main>' + ''.join(
                            f'<button title="{label}{number}" aria-label="{label}{number}" '
                            f'data-fixture="synthetic-{number:05d}">{label}{number}</button>'
                            for number in range(6500)) + '</main>'
                        async def serve(route):
                            await route.fulfill(status=200, content_type='text/html', body=body)
                        await browser.tool_context.route('https://fixture.test/**', serve)
                        await browser.tool_page.route('https://fixture.test/**', serve)
                        await browser.tool_page.goto('https://fixture.test/')
                        config = {'root': str(Path(__file__).resolve().parents[1]),
                                  'allowed_domains': ['fixture.test'], 'allowed_roots': [str(root)],
                                  'rea_backend': 'node_cli', 'rea_timeout_seconds': 45,
                                  'rea_max_output_bytes': 1048576,
                                  'rea_max_transport_bytes': 33554432}
                        context = {'browser': browser, 'config': config,
                                   'session_dir': str(root / 'session')}
                        result = await execute_rea('rea.inspect_page', {'observation_ms': 0},
                                                  context, PathPolicy([root]))
                        self.assertEqual('node_cli', result.get('backend'))
                        self.assertIn(result.get('status'), {'completed', 'partial'},
                                      {key: result.get(key) for key in ('status', 'error', 'process_diagnostics')})
                        self.assertTrue(result.get('observation_verified'))
                        self.assertFalse(result.get('fallback_used', False))
                        self.assertNotIn('prior_backend_attempt', result)
                        self.assertGreater(result['stdout_bytes'], 4_008_122)
                        self.assertTrue(result['response_truncated'])
                        self.assertLessEqual(len(json.dumps(result, ensure_ascii=True).encode()), 1048576)
                        full = Path(result['full_evidence_path']).read_bytes()
                        self.assertEqual(result['full_evidence_sha256'], hashlib.sha256(full).hexdigest())
                        stored = json.loads(full)
                        self.assertEqual('node_cli', stored['backend'])
                        diagnostics = stored['process_diagnostics']
                        self.assertEqual(0, diagnostics['returncode'])
                        self.assertFalse(diagnostics['stdout_truncated'])
                        self.assertEqual('<NODE_ROOT>/node.exe', diagnostics['command']['executable'])
                        self.assertIn('inspect-web-page', diagnostics['command']['arguments'])
                        self.assertTrue(native.is_connected())
                        self.assertFalse(browser.tool_page.is_closed())
                        print('REA large-page upstream proof: ' + json.dumps({
                            'backend': result['backend'], 'status': result['status'],
                            'stdout_bytes': result['stdout_bytes'], 'full_evidence_bytes': len(full),
                            'response_bytes': len(json.dumps(result, ensure_ascii=True).encode()),
                            'process_ms': diagnostics['duration_ms'], 'exit_status': diagnostics['returncode']}))
                    finally:
                        await native.close()
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
