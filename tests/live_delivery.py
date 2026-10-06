"""Explicit real UI delivery acceptance; harmless retained artifacts, never code execution."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_agent.browser import BrowserAdapter
from copilot_agent.config import Config
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.persistence import write_json
from copilot_agent.state import SessionState
from copilot_agent.tools import ToolRegistry


async def run(args):
    if not args.live: raise SystemExit('Explicit --live required; synthetic UI creation/downloads/extraction only.')
    config = Config.load(args.config)
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    directory = config.runtime_dir / 'acceptance' / ('delivery-' + token)
    directory.mkdir(parents=True)
    report = {'status': 'incomplete', 'mode': 'real visible synthetic file-delivery acceptance', 'steps': [],
              'authorization': 'Existing user engineering request: constrained new synthetic artifacts only; no generated script execution.',
              'OneDrive_created_access': False, 'generated_code_execution': False}
    browser = BrowserAdapter(config)
    engine = None
    allowed_names = {'synthetic-delivery.txt', 'synthetic-delivery.zip', 'synthetic-package.zip', 'synthetic-office.zip'}
    def decide(preview):
        plan = preview['complete_pending_plan']
        call = next(call for call in plan['tool_requests'] if call['call_id'] == preview['current_call_id'])
        prepared = preview.get('prepared_code') or {}
        if call['name'] == 'copilot.download' and call['arguments']['expected_name'] in allowed_names:
            target = Path(prepared['destination']).resolve()
            try: target.relative_to(config.storage_dir.resolve())
            except ValueError: return 'deny'
            return 'once'
        if call['name'] == 'archives.extract':
            manifest = prepared.get('archive_manifest', {})
            names = {entry['path'] for entry in manifest.get('entries', []) if not entry['directory']}
            if names and names.issubset({'README.md', 'main.py', 'synthetic.xlsx'}): return 'once'
        return 'deny'
    try:
        await browser.start()
        models = await browser.discover_models()
        if not any(item['label'] == args.model and item.get('enabled', True) for item in models):
            raise RuntimeError('The exact requested test model is unavailable.')
        await browser.select_model(args.model)
        state = SessionState(directory / 'session')
        engine = Orchestrator(config, browser, ToolRegistry(), state, approval_decider=decide)
        await engine.initialize()
        cases = [
            ('single non-Office direct file', 'Create one harmless text file named synthetic-delivery.txt containing exactly delivery-test followed by a newline. Provide an actual downloadable UI file link. Request copilot.download with expected_name synthetic-delivery.txt in the SAME response that includes the actual clickable artifact link after the END marker. If direct delivery is unavailable, ZIP fallback is allowed but report unavailable honestly.'),
            ('complete coding package', 'Create a complete tiny synthetic coding package in synthetic-package.zip containing exactly README.md (text: synthetic package) and main.py (text: print("synthetic package")). Do not execute any code. Request copilot.download with expected_name synthetic-package.zip in the SAME response as its actual clickable link after the END marker; after downloading, use archives.inspect then archives.extract with the actual inspected SHA-256, expected_files README.md and main.py, and a NEW destination inside the permitted OneDrive workspace. Return actual verification evidence.'),
            ('Office file in outer ZIP', 'Create a harmless Excel workbook named synthetic.xlsx with A1 equal to delivery-test, and deliver it INSIDE synthetic-office.zip. The outer ZIP must contain the workbook file rather than raw Office XML. Request copilot.download with expected_name synthetic-office.zip in the SAME response as the actual clickable link after the END marker. After actual download, use archives.inspect then archives.extract using its inspected SHA-256, expected_files synthetic.xlsx and a NEW destination inside the permitted OneDrive workspace. Do not launch Office or execute code.')]
        if args.only:
            cases = [cases[{'direct': 0, 'package': 1, 'office': 2}[args.only]]]
        report['selected_cases'] = [name for name, _ in cases]
        for name, request in cases:
            before = set(state.data['calls'])
            result = await engine.turn(request)
            calls = {key: value for key, value in state.data['calls'].items() if key not in before}
            observed_links = await browser.page.evaluate(r'''() => [...document.querySelectorAll('[data-testid="markdown-reply"] a[href]')].map(n=>{
              const u=new URL(n.href,location.href);return {label:(n.innerText||'').slice(0,200),scheme:u.protocol,host:u.hostname,path:u.pathname.slice(0,300),role:n.getAttribute('role'),download:n.getAttribute('download'),target:n.target};})''')
            status = 'passed' if result.get('completion_status') == 'complete' and any(call['request']['name'] == 'copilot.download' and call['result'].get('ok') for call in calls.values()) else 'blocked'
            report['steps'].append({'name': name, 'status': status, 'response': result, 'calls': calls, 'message_count': state.message_count, 'observed_link_metadata': observed_links})
            write_json(directory / 'report.json', report)
            await browser.page.screenshot(path=str(directory / (str(len(report['steps'])) + '-delivery.png')), full_page=False,
                mask=[browser.page.locator('nav,aside,header,[role="navigation"],[data-testid*="sidebar" i],button[aria-label*="account" i]')])
            if any(call['status'] == 'uncertain' for call in calls.values()): break
        report['status'] = 'passed' if len(report['steps']) == len(cases) and all(step['status'] == 'passed' for step in report['steps']) else 'partially_verified'
    except Exception as exc:
        report['steps'].append({'name': 'delivery acceptance', 'status': 'blocked', 'error': str(exc)})
    finally:
        if engine: await engine.close()
        else: await browser.close()
        write_json(directory / 'report.json', report)
        print('LIVE_DELIVERY_REPORT: ' + str(directory / 'report.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--model', default='GPT-6 Sol')
    parser.add_argument('--only', choices=['direct', 'package', 'office'], help='Run a changed delivery case without repeating already established cases.')
    asyncio.run(run(parser.parse_args()))
