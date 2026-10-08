"""Synthetic, deterministic fixtures for FUTURE tests; not observed site evidence."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import threading

from copilot_agent.discovery_contracts import MAPPING
from copilot_agent.site_knowledge import prepare_knowledge, execute_knowledge

ORIGIN = 'https://fixture.example'


def budgets():
    return dict(run_seconds=60, task_seconds=20, branch_seconds=40, pages=20, tasks=50,
                requests=80, bytes=2097152, concurrency=1, per_origin_concurrency=1,
                attempts=3, depth=2, browser_contexts=0, per_origin_rps=5,
                backoff_seconds=10, browser_restarts=0, replans=0, output_repairs=0)


def task(i, worker, parents=(), refs=(), urls=(), accept='usable', expand=False):
    operation, output = MAPPING[worker]
    return dict(id=i, worker=worker, operation=operation, branch=i,
                depends_on=[{'task_id': p, 'accept': accept} for p in parents],
                inputs={'urls': list(urls), 'evidence_from': list(refs), 'route_ids': []},
                output_type=output, priority=90, critical=worker == 'bootstrap',
                timeout_seconds=10, max_attempts=3, recovery_policy='read_only_v1',
                auth_requirement='public', approval_requirement='existing_read_approval' if worker in {'bootstrap', 'http', 'browser', 'network'} else 'none',
                expand_urls=expand)


def manifest():
    return dict(version='1.0', kind='discovery_manifest', request_id='dcurrent',
                objective='Synthetic public navigation discovery', seed_urls=[ORIGIN + '/'],
                scope={'origins': [ORIGIN], 'allow_paths': ['/'], 'exclude_paths': [],
                       'query_keys': [], 'max_query_variants': 3, 'allow_private_network': False, 'redirect_limit': 3},
                authentication={'mode': 'public', 'context_ref': None},
                permitted_workers=['bootstrap', 'http', 'structure', 'validate', 'aggregate'],
                budgets=budgets(),
                tasks=[task('bootstrap', 'bootstrap'), task('pages', 'http', ['bootstrap'], ['bootstrap'], [ORIGIN + '/'], expand=True),
                       task('structure', 'structure', ['pages'], ['pages']),
                       task('validate', 'validate', ['structure'], ['structure', 'pages']),
                       task('aggregate', 'aggregate', ['validate'], ['validate'], accept='terminal')],
                evidence_requirements={'required_types': ['scope', 'page', 'structure', 'boundary'], 'freshness_seconds': 300,
                                       'minimum_confidence': .8, 'retain_screenshots': False},
                stop={'plateau_window_pages': 10, 'plateau_windows': 3, 'minimum_gain': .01,
                      'duplicate_ratio': .9, 'required_high_priority_coverage': .95},
                replanning_triggers=[], redaction_profile='strict_v1',
                final_requirements={'max_model_bytes': 10000, 'include_gaps': True, 'include_evidence_refs': True})


def intent(scope, purpose='documents'):
    return dict(version='1.0', kind='navigation_intent', request_id='dcurrent', objective='Synthetic static target verification',
                target_purpose=purpose, scope=scope, allow_targeted_discovery=False,
                allow_consequential_actions=False, budgets=budgets())


@contextmanager
def workspace():
    with tempfile.TemporaryDirectory(prefix='copilot-discovery-') as temporary:
        root = Path(temporary)
        config = dict(root=root / 'source', storage_dir=root / 'onedrive', manifest_path=True,
                      persistent_graph=True, bounded_parallelism=False, local_recovery=False,
                      knowledge_write=True, knowledge_reuse=True, targeted_repair=False, max_output_chars=12000)
        owned = SimpleNamespace()
        page = SimpleNamespace(url=ORIGIN + '/', context=owned, is_closed=lambda: False)
        browser = SimpleNamespace(tool_page=page, tool_context=owned, page=None, chat_page=None)
        context = {'config': config, 'session_dir': root / 'session', 'knowledge_directory': root / 'device',
                   'source_request_id': 'current', 'approved': True, 'approval_hash': 'a' * 64,
                   'cancel_event': threading.Event(), 'site_knowledge_bindings': {}, 'discovery_runs': {}, 'browser': browser}
        args = {'origin': ORIGIN, 'tenant': 'fixture-tenant', 'user_scope': 'private-user', 'environment': 'test'}
        reviewed = prepare_knowledge(args, context, name='site_knowledge.bind')
        execute_knowledge('site_knowledge.bind', args, dict(context, site_knowledge_reviewed=reviewed))
        yield root, context
