"""Real Edge on synthetic HTTPS routes; no live website or Copilot account."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from playwright.async_api import async_playwright
from copilot_agent.browser import BrowserAdapter
from copilot_agent.policy import PathPolicy
from copilot_agent.tools import ToolRegistry
from copilot_agent.site_knowledge import prepare_knowledge

ORIGIN = 'https://fixture.test'
PAGES = {
    '/': '<title>Portal</title><nav><a data-testid="customer-search" href="/search">Customer search</a><a href="/documents">Documents</a></nav><main><h1>Welcome</h1></main>',
    '/search': '''<title>Search</title><h1>Customer search</h1><form onsubmit="event.preventDefault();document.querySelector('#results').hidden=false">
        <label>Customer ID<input id="query" required></label><button>Search</button></form>
        <table id="results" data-testid="results" hidden><tr><th>Customer</th><th>Status</th></tr>
        <tr><td><a href="/profile" data-testid="chosen-profile">Synthetic One</a></td><td>Active</td></tr>
        <tr><td><a href="/other">Synthetic Two</a></td><td>Active</td></tr></table><button disabled>Next page</button>''',
    '/profile': '<title>Profile</title><h1>Customer profile</h1><p data-testid="customer-id">SYNTHETIC-1</p><p data-testid="status">Active</p><a href="/documents">Documents</a>',
    '/documents': '<title>Documents</title><h1>Documents</h1><a href="/first.txt">First report</a><a href="/first.txt">Duplicate</a><a href="/second.txt">Second report</a><a href="/bad.pdf">Corrupt PDF</a>',
    '/complex': '''<title>Complex</title><h1>Sections</h1><nav><button aria-expanded="false" onclick="this.setAttribute('aria-expanded','true')">Menu</button></nav>
        <div role="dialog" aria-label="Details">Read details</div><iframe id="frame" src="/frame"></iframe>
        <div id="shadow"></div><script>document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML='<button data-testid="shadow-button">Shadow action</button>';
        setTimeout(()=>document.querySelector('main').innerHTML='<h2 data-testid="ready">Ready</h2>',200)</script><main aria-busy="false"></main>''',
    '/frame': '<h1>Frame section</h1><button data-testid="frame-button">Frame action</button>',
    '/captcha': '<h1>Verify you are human</h1>',
    '/denied': '<h1>Access denied</h1>',
    '/login': '<h1>Sign in to continue</h1><input type="password">',
}


class WebsiteIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='copilot_unseen_site_'))
        self.playwright = await async_playwright().start()
        self.native = await self.playwright.chromium.launch(channel='msedge', headless=True)
        self.browser = BrowserAdapter(SimpleNamespace(allowed_domains=['fixture.test']))
        self.browser.browser = self.native
        self.browser.tool_context = await self.native.new_context(accept_downloads=True, service_workers='block')
        await self.browser._configure_tool_context()
        async def serve(route):
            path = route.request.url.removeprefix(ORIGIN).split('?')[0]
            if path in {'/first.txt', '/second.txt', '/bad.pdf'}:
                data = {'/first.txt': b'first evidence', '/second.txt': b'second evidence', '/bad.pdf': b'<html>not a PDF</html>'}[path]
                await route.fulfill(status=200, body=data, headers={'content-type': 'application/pdf' if path.endswith('.pdf') else 'text/plain',
                    'content-disposition': 'attachment; filename="' + path[1:] + '"', 'content-length': str(len(data))})
            else:
                await route.fulfill(status=200, content_type='text/html', body=PAGES.get(path, '<h1>Missing page</h1>'))
        await self.browser.tool_context.route(ORIGIN + '/**', serve)
        self.browser.tool_page = await self.browser.tool_context.new_page()
        await self.browser.tool_page.goto(ORIGIN + '/')
        self.config = {'allowed_domains': ['fixture.test'], 'allowed_roots': [str(self.root)],
                       'storage_dir': str(self.root), 'max_tool_tabs': 6, 'max_output_chars': 12000}
        self.context = {'browser': self.browser, 'session_dir': self.root, 'config': self.config,
            'approved': True, 'approved_domains': ['fixture.test'], 'policy': PathPolicy([self.root]),
            'web_document_tickets': {}, 'pending_file_attachments': [], 'approved_attachment_hashes': {},
            'site_knowledge_bindings': {}, 'knowledge_directory': self.root / 'knowledge',
            'document_catalogues': {}, 'transferred_attachment_hashes': {}}
        self.context['download_manifest_hashes'] = {}
        self.registry = ToolRegistry()

    async def asyncTearDown(self):
        await self.native.close()
        await self.playwright.stop()

    async def call(self, name, args):
        outcome = await self.registry.execute(name, args, self.context)
        self.assertTrue(outcome['ok'], outcome)
        return outcome['result']

    async def test_landing_search_disambiguation_profile_and_documents(self):
        recon = await self.call('browser.recon', {'goal': 'Customer search documents'})
        self.assertTrue(recon['site_map']['routes'])
        plan = {'task_id': 'lookup', 'steps': [
            {'id': 'search', 'op': 'click', 'locator': {'testid': 'old-id', 'role': 'link', 'name': 'Customer search'}, 'effect': 'navigation',
             'expect': [{'kind': 'url', 'value': ORIGIN + '/search'}]},
            {'id': 'identifier', 'op': 'fill', 'locator': {'label': 'Customer ID'}, 'value': 'SYNTHETIC-1'},
            {'id': 'submit', 'op': 'click', 'locator': {'role': 'button', 'name': 'Search'}, 'effect': 'search',
             'expect': [{'kind': 'visible', 'locator': {'testid': 'results'}}]},
        ], 'success': [{'kind': 'count', 'locator': {'css': '#results a'}, 'count': 2}]}
        result = await self.call('browser.plan', plan)
        self.assertEqual(result['completed_steps'], 3)
        self.assertEqual(result['results'][0]['locator_strategy'], 'role')
        # Ambiguous identity cannot silently choose one result.
        bad = await self.registry.execute('browser.customer_summary', {'task_id': 'lookup', 'customer_key': 'one',
            'identity': [{'locator': {'css': '#results a'}, 'value': 'Synthetic One'}],
            'fields': [{'name': 'status', 'locator': {'testid': 'status'}}]}, self.context)
        self.assertFalse(bad['ok'])
        # Explicit synthetic selection represents the user's disambiguated choice.
        await self.call('browser.plan', {'task_id': 'lookup', 'steps': [{'id': 'selected', 'op': 'click',
            'locator': {'testid': 'chosen-profile'}, 'effect': 'navigation',
            'expect': [{'kind': 'url', 'value': ORIGIN + '/profile'}]}],
            'success': [{'kind': 'text', 'locator': {'testid': 'customer-id'}, 'value': 'SYNTHETIC-1'}]})
        summary = await self.call('browser.customer_summary', {'task_id': 'lookup', 'customer_key': 'one',
            'identity': [{'locator': {'testid': 'customer-id'}, 'value': 'SYNTHETIC-1'}],
            'fields': [{'name': 'status', 'locator': {'testid': 'status'}}]})
        self.assertEqual(summary['facts'][0]['value'], 'Active')
        self.assertEqual(summary['facts'][0]['evidence'], 'observed')

    async def test_real_download_batch_integrity_manifest_and_transfer_queue(self):
        await self.browser.tool_page.goto(ORIGIN + '/documents')
        docs = (await self.call('browser.documents', {}))['documents']
        self.assertEqual(len(docs), 3)
        self.assertEqual(docs[0]['duplicate_count'], 1)
        result = await self.call('browser.download_batch', {'documents': [{'document_id': d['document_id']} for d in docs[:2]],
            'destination': str(self.root / 'downloads'), 'concurrency': 2, 'rate_limit_ms': 100, 'timeout_seconds': 15})
        self.assertEqual(result['summary']['success'], 2)
        self.assertTrue(all(f['sha256'] == hashlib.sha256(Path(f['path']).read_bytes()).hexdigest() for f in result['files']))
        selected = [{'path': f['path'], 'sha256': f['sha256']} for f in result['files']]
        selected.append({'path': result['manifest_path'], 'sha256': result['manifest_sha256']})
        queued = await self.call('files.transfer_to_copilot', {'files': selected})
        self.assertEqual(queued['status'], 'queued')
        self.assertFalse(queued['delivery_verified'])
        self.assertEqual(len(self.context['pending_file_attachments']), 3)
        failed = await self.registry.execute('browser.download_batch', {'documents': [{'document_id': docs[2]['document_id']}],
            'destination': str(self.root / 'corrupt'), 'timeout_seconds': 10}, self.context)
        self.assertFalse(failed['ok'], failed)
        self.assertEqual(failed['result']['status'], 'failed')

    async def test_nested_frame_shadow_modal_and_delayed_state(self):
        await self.browser.tool_page.goto(ORIGIN + '/complex')
        recon = await self.call('browser.recon', {'max_elements': 30})
        self.assertEqual(recon['shadow_roots'], 1)
        self.assertEqual(len(recon['frames']), 1)
        self.assertTrue(recon['boundaries'])
        await self.call('browser.plan', {'task_id': 'complex', 'steps': [
            {'id': 'shadow', 'op': 'wait', 'locator': {'testid': 'shadow-button'}},
            {'id': 'frame', 'op': 'wait', 'locator': {'frame_selector': '#frame', 'testid': 'frame-button'}},
            {'id': 'slow', 'op': 'wait', 'locator': {'testid': 'ready'}, 'timeout_ms': 3000}],
            'success': [{'kind': 'visible', 'locator': {'testid': 'ready'}}]})

    async def test_boundaries_stop_before_effects_and_primary_tab_preserved(self):
        for path, category in [('/captcha', 'human_verification'), ('/denied', 'access_denied'), ('/login', 'authentication_required')]:
            await self.browser.tool_page.goto(ORIGIN + path)
            result = await self.registry.execute('browser.plan', {'task_id': 'boundaries',
                'steps': [{'id': 'read', 'op': 'capture', 'locator': {'role': 'heading', 'name': PAGES[path].split('<h1>')[1].split('</h1>')[0]}}],
                'success': [{'kind': 'url', 'value': ORIGIN + path}]}, self.context)
            self.assertFalse(result['ok'])
            self.assertEqual(result['result']['error']['code'], category)
            self.assertEqual(result['result']['completed_steps'], 0)
        await self.browser.tool_page.goto(ORIGIN + '/')
        tab = await self.call('browser.tabs', {'operation': 'open', 'url': ORIGIN + '/documents', 'task_id': 'boundaries', 'purpose': 'Documents'})
        await self.call('browser.tabs', {'operation': 'close', 'tab_id': tab['tab_id'], 'task_id': 'boundaries'})
        refused = await self.registry.execute('browser.tabs', {'operation': 'close', 'tab_id': 'tab-1'}, self.context)
        self.assertFalse(refused['ok'])
        self.assertFalse(self.browser.tool_page.is_closed())

    async def test_persistent_knowledge_consent_reuse_isolation_and_invalidation(self):
        async def approve(name, args):
            prepared = prepare_knowledge(args, self.context, name=name)
            self.context.update(approval_hash='a' * 64, site_knowledge_reviewed=prepared)
            if name == 'site_knowledge.save': self.context['site_knowledge_consent'] = prepared
            return await self.call(name, args)
        scope = {'origin': ORIGIN, 'tenant': 'tenant-a', 'user_scope': 'local-user', 'environment': 'test'}
        await approve('site_knowledge.bind', scope)
        save = {'origin': ORIGIN, 'categories': ['routes'], 'knowledge': {'routes': [{'path': '/customers/search', 'purpose': 'search'}]}}
        declined = await self.registry.execute('site_knowledge.save', save, {**self.context, 'approved': False})
        self.assertFalse(declined['ok'])
        self.assertFalse((self.root / 'knowledge').exists())
        await approve('site_knowledge.save', save)
        reused = await self.call('site_knowledge.retrieve', {'origin': ORIGIN})
        self.assertIn('knowledge', reused)
        await approve('site_knowledge.bind', {**scope, 'tenant': 'tenant-b'})
        other = await self.call('site_knowledge.retrieve', {'origin': ORIGIN})
        self.assertEqual(other.get('knowledge', {}), {})
        await approve('site_knowledge.bind', scope)
        await approve('site_knowledge.invalidate', {'origin': ORIGIN})
        invalid = await self.call('site_knowledge.retrieve', {'origin': ORIGIN})
        self.assertEqual(invalid.get('knowledge', {}), {})

    async def test_baseline_vs_verified_plan_same_unseen_route(self):
        async def baseline():
            calls = 0
            for name, args in [('browser.info', {}), ('browser.read', {}), ('browser.structure', {}),
                               ('browser.frames', {}), ('browser.click', {'selector': '[data-testid="customer-search"]'}),
                               ('browser.info', {}), ('browser.structure', {})]:
                await self.call(name, args); calls += 1
            self.assertEqual(self.browser.tool_page.url, ORIGIN + '/search')
            return calls
        start = time.monotonic(); old_calls = await baseline(); old_seconds = time.monotonic() - start
        await self.browser.tool_page.goto(ORIGIN + '/')
        start = time.monotonic()
        recon = await self.call('browser.recon', {'goal': 'Customer search'})
        await self.call('browser.plan', {'task_id': 'benchmark', 'steps': [{'id': 'route', 'op': 'click',
            'locator': recon['site_map']['routes'][0]['locator'], 'effect': 'navigation',
            'expect': [{'kind': 'url', 'value': ORIGIN + '/search'}]}],
            'success': [{'kind': 'visible', 'locator': {'label': 'Customer ID'}}]})
        new_seconds = time.monotonic() - start
        evidence = {'fixture': 'synthetic static landing to unknown customer search', 'browser': self.native.version,
            'baseline': {'tool_calls': old_calls, 'success': True, 'elapsed_seconds': round(old_seconds, 4)},
            'upgraded': {'tool_calls': 2, 'success': True, 'elapsed_seconds': round(new_seconds, 4)},
            'reduction_percent': round(100 * (old_calls - 2) / old_calls, 2),
            'measurement_scope': 'Registered tool calls; no live Copilot LLM message or production throughput measurement'}
        report = Path(__file__).resolve().parents[1] / 'runtime' / 'verification' / 'unseen-site-benchmark.json'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        self.assertLess(2, old_calls)


if __name__ == '__main__':
    unittest.main()
