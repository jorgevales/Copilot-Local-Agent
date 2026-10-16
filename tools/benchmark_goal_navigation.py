"""Reproducible offline browser benchmark; no Copilot/model or production traffic.

Compare individual known actions with goal continuations executing short known
segments. Model waits, if requested, are explicitly simulated, never measured.
All synthetic evidence is retained beneath the selected output directory.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_agent.performance import PerformanceTrace
from copilot_agent.policy import PathPolicy
from copilot_agent.tools import ToolRegistry


async def run_case(browser, root, variant, run_number, delay_ms=0, steps=6, scenario='known_segments'):
    directory = root / f'{variant}-{run_number:03d}'
    directory.mkdir(parents=True, exist_ok=False)
    context = await browser.new_context(viewport={'width': 1280, 'height': 800})
    network_counts = {'requests': 0, 'blocked': 0}
    async def fixture(route):
        network_counts['requests'] += 1
        parsed = urlsplit(route.request.url)
        if parsed.hostname != 'navigation-benchmark.test':
            network_counts['blocked'] += 1
            await route.abort('blockedbyclient')
            return
        stage = int(parsed.path.strip('/') or 0) if not parsed.path.startswith('/noise') else -1
        heading = 'Target report' if stage == steps else f'Navigation stage {stage}'
        links = ''.join(f'<a href="/{n}">Target report stage {n}</a> ' for n in range(1, steps+1))
        noise = ''.join(f'<a href="/0">Unrelated section {n}</a> ' for n in range(6))
        if scenario == 'branching_discovery':
            # Only the next route is revealed. Neither navigator receives a
            # fabricated future path or the final URL from the scripted adviser.
            links = f'<a href="/{stage+1}">Target report section {stage+1}</a>' if 0 <= stage < steps else ''
            noise = '<a href="/noise">Inventory archive</a> <a href="/0">Home</a>'
        await route.fulfill(content_type='text/html', body=f'<!doctype html><title>{heading}</title><h1>{heading}</h1><nav>{links}{noise}</nav>')
    await context.route('**/*', fixture)
    page = await context.new_page()
    await page.goto('https://navigation-benchmark.test/')
    adapter = SimpleNamespace(tool_page=page, tool_context=context, page=None, _tool_pages=[page])
    tracing = PerformanceTrace(directory)
    env = {'browser': adapter, 'config': {'allowed_domains': ['navigation-benchmark.test'],
           'compact_navigation': True}, 'session_dir': directory, 'approved': True,
           'path_policy': PathPolicy([directory]), 'performance_trace': tracing}
    registry = ToolRegistry()
    target = [{'kind': 'url', 'value': f'https://navigation-benchmark.test/{steps}'},
              {'kind': 'text', 'locator': {'role': 'heading'}, 'value': 'Target report'}]
    outcomes, model_decisions, actions, ok = [], 0, 0, False
    started, cpu = time.monotonic(), time.process_time()
    try:
        async def decision(name, args):
            nonlocal model_decisions
            model_decisions += 1
            # Simulated delay is a configurable experimental input, not inferred
            # from provider usage or a claim about live Copilot performance.
            await asyncio.sleep(delay_ms / 1000)
            env.update(source_request_id=f'run-{model_decisions}', source_call_id=f'call-{model_decisions}')
            result = await registry.execute(name, args, env)
            outcomes.append({'ok': result['ok'], 'status': result.get('result', {}).get('status')})
            return result
        def segment(first, last):
            return [{'id': f'page-{n}', 'op': 'navigate', 'url': f'https://navigation-benchmark.test/{n}',
                     'expect': [{'kind': 'url', 'value': f'https://navigation-benchmark.test/{n}'}]}
                    for n in range(first, last+1)]
        if scenario == 'branching_discovery':
            args = {'task_id': 'benchmark', 'goal': 'Target report', 'success': target[1:]}
            result = None
            if variant == 'goal_continuations':
                result = await decision('browser.navigate_goal', args)
            for n in range(steps * 2):
                if page.url == f'https://navigation-benchmark.test/{steps}':
                    break
                if variant == 'individual_actions':
                    observed = await decision('browser.recon', {'goal': args['goal'], 'task_id': 'benchmark'})
                    if not observed['ok']:
                        break
                    choices = observed['result']['site_map']['routes']
                else:
                    if not result['ok'] or result['result'].get('status') != 'needs_visual_decision':
                        break
                    choices = result['result']['candidates']
                choice = next((c for c in choices if c.get('url') and
                               not c.get('requires_locator') and not c.get('query_omitted')
                               and 'Target report' in c.get('label', '')), None)
                if choice is None:
                    break
                step = {'id': f'observed-{n}', 'op': 'navigate', 'url': choice['url'],
                        'expect': [{'kind': 'url', 'value': choice['url']}]}
                if variant == 'individual_actions':
                    result = await decision('browser.plan', {'task_id': 'benchmark', 'steps': [step],
                        'success': step['expect'], 'max_actions': 1, 'timeout_seconds': 15})
                else:
                    args.update(observation_id=result['result']['observation_id'], steps=[step])
                    result = await decision('browser.navigate_goal', args)
                if not result['ok']:
                    break
                actions += 1
        elif variant == 'individual_actions':
            for n in range(1, steps+1):
                result = await decision('browser.plan', {'task_id': 'benchmark', 'steps': segment(n, n),
                    'success': segment(n, n)[0]['expect'], 'max_actions': 1, 'timeout_seconds': 15})
                if not result['ok']:
                    break
                actions += 1
        else:
            args = {'task_id': 'benchmark', 'goal': 'Target report', 'success': target}
            result = await decision('browser.navigate_goal', args)
            for first in range(1, steps+1, 3):
                if not result['ok'] or result['result'].get('status') != 'needs_visual_decision':
                    break
                args.update(observation_id=result['result']['observation_id'], steps=segment(first, min(first+2, steps)))
                result = await decision('browser.navigate_goal', args)
            actions = result.get('result', {}).get('actions', 0)
        # Independent fixture outcome, never the model/tool completion claim.
        ok = page.url == f'https://navigation-benchmark.test/{steps}' and await page.locator('h1').inner_text() == 'Target report'
        records = list(tracing.records)
        counts = Counter(r['phase'] for r in records)
        action_times = [r['duration_ms'] for r in records if r['phase'] == 'action']
        first_action = next((max(0, (tracing.started-started)*1000+r['monotonic_ms']-r['duration_ms'])
                             for r in records if r['phase'] == 'action'), None)
        return {'variant': variant, 'scenario': scenario, 'run': run_number, 'verified_target': ok,
                'synthetic_completion_ms': round((time.monotonic()-started)*1000, 3),
                'python_cpu_ms': round((time.process_time()-cpu)*1000, 3),
                'scripted_decision_requests': model_decisions, 'reasoning_model_calls': None,
                'simulated_decision_delay_ms': delay_ms, 'live_copilot_wait_ms': None,
                'verified_actions': actions, 'screenshots': counts['screenshot'],
                'structured_dom_captures': counts['structure'],
                'time_to_first_navigation_action_ms': first_action,
                'average_action_ms': statistics.mean(action_times) if action_times else None,
                'successful_actions_per_minute': actions/max(.001,time.monotonic()-started)*60,
                'recovery_rate': None, 'network_requests': network_counts['requests'],
                'blocked_network_requests': network_counts['blocked'],
                'visual_packages': counts['visual_packaging'],
                'visual_bytes': sum(r.get('bytes', 0) for r in records if r['phase'] == 'visual_packaging'),
                'human_interventions': 0, 'policy_violations': None,
                'outcomes': outcomes, 'telemetry_dropped': tracing.dropped,
                'memory_bytes': None, 'gpu': None, 'network_bytes': None}
    finally:
        tracing.flush()
        await context.close()


async def benchmark(output, runs=3, delay_ms=0, scenario='known_segments'):
    from playwright.async_api import async_playwright
    output.mkdir(parents=True, exist_ok=False)
    results = []
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception:
            browser = await playwright.chromium.launch(headless=True, channel='msedge')
        try:
            for n in range(1, runs+1):
                order = ('individual_actions', 'goal_continuations') if n % 2 else ('goal_continuations', 'individual_actions')
                for variant in order:
                    results.append(await run_case(browser, output, variant, n, delay_ms, scenario=scenario))
        finally:
            await browser.close()
    summary = {name: {'runs': len(rows), 'successes': sum(r['verified_target'] for r in rows),
                     'median_synthetic_completion_ms': statistics.median(r['synthetic_completion_ms'] for r in rows),
                     'median_scripted_decision_requests': statistics.median(r['scripted_decision_requests'] for r in rows)}
               for name in ('individual_actions', 'goal_continuations')
               for rows in [[r for r in results if r['variant'] == name]]}
    source_root = Path(__file__).resolve().parents[1]
    source_hashes = {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in
                    ('copilot_agent/goal_navigation.py', 'copilot_agent/automatic_visuals.py',
                     'copilot_agent/tools.py', 'copilot_agent/web_navigation.py',
                     'tools/benchmark_goal_navigation.py')}
    report = {'kind': 'offline_synthetic_browser_benchmark', 'scenario': scenario, 'live_model_tested': False,
              'python_version': sys.version, 'playwright_version': version('playwright'),
              'browser_version': browser.version, 'source_sha256': source_hashes,
              'note': 'Scripted decisions and optional artificial delays; no live VDI/Copilot speedup established. '
                      'CPU is the Python process only. Unavailable usage/resource metrics are null.',
              'summary': summary, 'runs': results}
    (output / 'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing evidence is never overwritten')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--decision-delay-ms', type=float, default=0)
    parser.add_argument('--scenario', choices=('known_segments', 'branching_discovery'), default='known_segments')
    options = parser.parse_args()
    if not 1 <= options.runs <= 100 or not 0 <= options.decision_delay_ms <= 60000:
        parser.error('runs must be 1..100 and simulated delay 0..60000ms')
    result = asyncio.run(benchmark(options.output, options.runs, options.decision_delay_ms, options.scenario))
    print(json.dumps(result['summary'], indent=2))
    sys.exit(0 if all(row['verified_target'] for row in result['runs']) else 1)
