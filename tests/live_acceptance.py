"""Explicit real visible acceptance; never auto-approve generated scripts.

Run only with --live and an authorized dedicated profile configuration. A retained
pending-approval preview and matching decision file bridge the user approval UI.
This is not part of unittest discovery and cannot silently send on import.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_agent.browser import BrowserAdapter, model_rank
from copilot_agent.config import Config
from copilot_agent.logging_utils import redact
from copilot_agent.orchestrator import Orchestrator
from copilot_agent.persistence import write_json
from copilot_agent.state import SessionState
from copilot_agent.sync import CreatedSync
from copilot_agent.tools import ToolRegistry


class InjectedCaptureBrowser:
    """One declared local capture fault; underlying request/response remains real."""
    def __init__(self, adapter, evidence):
        self.adapter, self.evidence, self.inject_next = adapter, evidence, False

    def __getattr__(self, key):
        return getattr(self.adapter, key)

    async def exchange(self, *args, **kwargs):
        raw = await self.adapter.exchange(*args, **kwargs)
        if self.inject_next:
            self.inject_next = False
            with (self.evidence / 'original-before-injected-capture-fault.txt').open('x', encoding='utf-8') as stream:
                stream.write(redact(raw))
            print('DECLARED_FAULT: intentionally corrupted one captured response; real original retained.', flush=True)
            return 'Intentional local capture corruption for protocol recovery acceptance.'
        return raw


async def run(args):
    if not args.live:
        raise SystemExit('Explicit --live is required; this workflow sends synthetic content to Copilot.')
    cfg = Config.load(args.config)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = cfg.root / 'runtime' / 'acceptance' / ('conversation-' + stamp + '-' + uuid.uuid4().hex[:6])
    directory.mkdir(parents=True)
    for root in cfg.allowed_roots:
        Path(root).mkdir(parents=True, exist_ok=True)
    state = SessionState(directory / 'session')
    adapter = BrowserAdapter(cfg)
    browser = InjectedCaptureBrowser(adapter, directory)
    report = {'started_at': stamp, 'mode': 'real visible Copilot UI, synthetic content only', 'steps': [], 'limitations': [], 'directory': str(directory)}
    write_json(directory / 'report.json', report)

    async def record(name, action, verification=None):
        print('LIVE_STEP: ' + name, flush=True)
        started = time.monotonic()
        try:
            value = await action()
            if verification:
                verification(value)
            evidence = json.loads(json.dumps(redact(value), default=lambda obj: {'runtime_type': type(obj).__name__}))
            report['steps'].append({'name': name, 'status': 'passed', 'duration_seconds': round(time.monotonic() - started, 3), 'evidence': evidence})
            write_json(directory / 'report.json', report)
            if adapter.page and not adapter.page.is_closed():
                path = directory / (str(len(report['steps'])).zfill(2) + '-' + name.replace(' ', '-') + '.png')
                await adapter.page.screenshot(path=str(path), timeout=10000, mask=[
                    adapter.page.locator('nav,[role="navigation"],[data-testid*="sidebar" i]'),
                    adapter.page.locator('button[aria-label*="account" i]')])
            return value
        except Exception as exc:
            report['steps'].append({'name': name, 'status': 'blocked', 'error': str(exc)})
            write_json(directory / 'report.json', report)
            print('LIVE_BLOCKED: ' + str(exc), flush=True)
            raise

    approval_mode = {'value': 'deny'}
    async def decide(preview):
        if approval_mode['value'] == 'deny':
            return 'deny'
        if not preview.get('prepared_code'):
            return 'deny'
        proposal = preview['prepared_code']
        # Full immutable generated proposal is presented; human must explicitly grant.
        nonce = uuid.uuid4().hex
        pending = directory / 'pending-approval.json'
        decision_file = directory / ('decision-' + nonce + '.json')
        write_json(pending, {'nonce': nonce, 'preview': preview, 'decision_file': str(decision_file)})
        print('PENDING_USER_APPROVAL: ' + str(pending), flush=True)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            if decision_file.exists():
                decision = json.loads(decision_file.read_text(encoding='utf-8'))
                if decision.get('nonce') != nonce or decision.get('proposal_hash') != proposal['proposal_hash']:
                    raise ValueError('Human approval file does not match pending proposal')
                return 'once' if decision.get('decision') == 'once' else 'deny'
            await asyncio.sleep(.5)
        report['limitations'].append('Explicit user approval did not arrive before the bounded approval wait ended.')
        return 'deny'

    engine = None
    try:
        await record('visible startup', adapter.start, lambda result: None)
        models = await record('dynamic model discovery', adapter.discover_models)
        chosen = next((m for m in model_rank(models) if m.get('enabled', True)), None)
        if not chosen:
            raise RuntimeError('No enabled model was discovered')
        await record('exact model selection', lambda: adapter.select_model(chosen['label']))
        engine = Orchestrator(cfg, browser, ToolRegistry(), state, approval_decider=decide)
        await record('guidance upload initialization and envelope capture', engine.initialize,
                     lambda result: require(result['response_type'] == 'final', 'Initialization was not final'))
        await record('no tool response', lambda: engine.turn('Synthetic acceptance: say Hello from the local agent. Use no local tools.'),
                     lambda result: require(result['response_type'] == 'final', 'No-tool response did not complete'))
        before_calls = len(state.data['calls'])
        await record('read only local tool and returned evidence', lambda: engine.turn('Synthetic acceptance: use the registered system.versions tool exactly once to obtain the actual local Python version, then report it. Do not infer it from memory.'),
                     lambda result: require(any(c['request']['name'] == 'system.versions' for c in list(state.data['calls'].values())[before_calls:]), 'Copilot did not request the actual tool'))
        plan = {'script': "print('approval-test')", 'purpose': 'Synthetic acceptance of immutable execution approval',
                'language': 'python_subset', 'working_directory': cfg.allowed_roots[0],
                'read_paths': [], 'create_paths': [], 'expected_outputs': [], 'commands': [], 'subprocesses': [],
                'network_destinations': [], 'permissions': [], 'risk_summary': 'Bounded computation and terminal output only; no file reads, writes, subprocesses or network.',
                'recovery_notes': 'No external changes to roll back. Retain the execution report.'}
        instruction = 'Synthetic Code Runner acceptance: request exactly one code_runner tool call using these exact arguments. The user decides approval; do not execute it yourself or change the script. After the tool outcome, provide an honest final answer. Arguments:\n' + json.dumps(plan)
        before_calls = len(state.data['calls'])
        await record('code proposal denied without execution', lambda: engine.turn(instruction),
                     lambda result: require(any(c.get('result', {}).get('error', {}).get('code') == 'approval_denied' for c in list(state.data['calls'].values())[before_calls:]), 'No denied code proposal was observed'))
        previous_retries = len(state.data['retry_records'])
        browser.inject_next = True
        await record('invalid capture correction through real UI', lambda: engine.turn('Synthetic recovery acceptance: answer with a short final confirmation that this is harmless synthetic testing, with no tools.'),
                     lambda result: require(len(state.data['retry_records']) > previous_retries, 'Protocol correction was not triggered'))
        await record('findings proposed and saved immediately', lambda: engine.turn('Synthetic findings acceptance: return a genuinely reusable Useful Finding that this acceptance workflow uses harmless synthetic inputs. Its provenance is the synthetic test requests observed in this session. Use no tools and complete the turn.'),
                     lambda result: require(bool(engine.findings.data['findings']), 'No valid finding was accepted'))
        limit = state.message_count + 12
        while not state.data['findings_sync'] and state.message_count < limit:
            await record('continuous no tool turn ' + str(state.message_count + 1), lambda: engine.turn('Synthetic continuity acceptance: reply Ready in a final no-tool envelope.'))
        require(bool(state.data['findings_sync']), 'No tenth-message findings upload was committed')
        report['steps'].append({'name': 'tenth-message current findings attachment', 'status': 'passed', 'evidence': state.data['findings_sync']})
        write_json(directory / 'report.json', report)

        # The initialization's real Markdown/schema/catalogue uploads already prove
        # local attachment transfer. Do not silently auto-approve extra user files.
        watcher = CreatedSync(cfg.created_dir, poll_interval=cfg.sync_poll_interval) if cfg.created_sync_enabled and cfg.created_dir else None
        baseline = watcher.baseline() if watcher else None
        expected = 'synthetic-agent-' + uuid.uuid4().hex[:8] + '.txt'
        creation = await record('integrated created file capability observation', lambda: engine.turn(
            'Synthetic file capability acceptance: if your current integrated capabilities can create a downloadable text file, create ' + expected + ' containing only Synthetic local agent acceptance. Use no local file tools. If unavailable, return an honest blocked error envelope. Return the filename and observed creation evidence in your structured response.'))
        result = (await watcher.poll(baseline, pattern=expected, timeout=min(cfg.sync_timeout, 30)) if watcher else
                  {'status':'deferred_user','files':[],'reason':'User requested no OneDrive access during engineering verification.'})
        if result['status'] == 'synchronized':
            delivered = Path(result['files'][0]['path'])
            content_ok = delivered.stat().st_size <= 1024 and delivered.read_text(encoding='utf-8-sig').strip() == 'Synthetic local agent acceptance.'
            result['expected_content_verified'] = content_ok
            if not content_ok:
                result['status'] = 'content_mismatch'
        report['steps'].append({'name': 'actual Copilot created file local synchronization', 'status': 'passed' if result['status'] == 'synchronized' else 'deferred' if not watcher else 'blocked', 'evidence': result})
        if result['status'] != 'synchronized':
            report['limitations'].append('Actual Copilot-created local delivery was not verified: ' + result['status'] + '. No cloud preview was substituted for local evidence.')
        write_json(directory / 'report.json', report)
        await record('local synchronization observation returned to Copilot', lambda: engine.turn(
            'Authoritative local delivery observation for the synthetic file: ' + json.dumps(result) +
            '. Acknowledge only these facts in a final no-tool envelope. Do not treat a cloud preview as local delivery.'))

        approval_mode['value'] = 'human'
        before_calls = len(state.data['calls'])
        await record('explicit human code approval exact execution', lambda: engine.turn(instruction),
                     lambda result: require(any(c.get('result', {}).get('ok') and c['request']['name'] == 'code_runner' for c in list(state.data['calls'].values())[before_calls:]), 'No explicitly approved code execution completed'))
        await record('another user message after tools', lambda: engine.turn('Synthetic final continuity check: reply Session remains usable in a final no-tool envelope.'))
    except Exception as exc:
        report['limitations'].append(str(exc))
    finally:
        if adapter.page and not adapter.page.is_closed():
            report['synthetic_conversation_url'] = adapter.page.url.split('?', 1)[0].split('#', 1)[0]
        try:
            if engine:
                await engine.close()
            else:
                await adapter.close()
            report['steps'].append({'name': 'owned pages and session clean exit', 'status': 'passed'})
        except Exception as exc:
            report['steps'].append({'name': 'owned pages and session clean exit', 'status': 'blocked', 'error': str(exc)})
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['copilot_message_count'] = state.message_count
        report['result'] = 'passed' if not report['limitations'] and all(s['status'] == 'passed' for s in report['steps']) else 'incomplete_with_documented_limitations'
        write_json(directory / 'report.json', report)
        print('LIVE_REPORT: ' + str(directory / 'report.json'), flush=True)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--config', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
