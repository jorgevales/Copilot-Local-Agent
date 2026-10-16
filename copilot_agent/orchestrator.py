from __future__ import annotations
import asyncio
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
import uuid
import threading
import time
from .approvals import ApprovalManager
from .browser import BrowserUIError, CaptureTimeoutError, SubmissionAmbiguousError, SubmissionNotSentError
from .code_runner import CodeRunner
from .local_python_runner import ManagedProcessRegistry
from .findings import Findings
from .feedback import Feedback, public_preview
from .logging_utils import redact, SENSITIVE
from .policy import PathPolicy, PolicyError, URLPolicy
from .reconciliation import capture_baseline, recover_missing_navigation, navigation_scope_allows, _binding
from .presentation import exchange_summary, call_summary
from .research_permissions import prepare_permissions
from .prompts import PromptBuilder
from .protocol import ProtocolError, parse_response, correction_message
from .state import canonical_hash, operation_domains, recoverable_capture_request_id, browser_inventory
from .sync import CreatedSync
from .attachments import AttachmentQueue, SUPPORTED_EXTENSIONS, TEXT_EXTENSIONS, upload_name
from .performance import PerformanceTrace


class Orchestrator:
    def __init__(self, config, browser, registry, state, approval_decider=None, display=print, event_sink=None, cancel_event=None, steering_poll=None, steering_complete=None):
        self.config, self.browser, self.registry, self.state = config, browser, registry, state
        self.performance = PerformanceTrace(state.directory, enabled=getattr(config, 'performance_enabled', True))
        browser.performance_trace = self.performance
        if hasattr(registry, 'config'):
            registry.config = config
        # Persisted target observations never restore a session authorization.
        state.data['approved_domains'] = []
        state.data['website_private'] = True
        browser.website_private = True
        self.findings = Findings(state.directory)
        capability = getattr(config, '_knowledge_capability', None)
        if capability:
            state.data['knowledge_capability'] = capability
            self.findings.set_storage_capability(capability['statement'])
        self.prompts = PromptBuilder(config, registry, state, self.findings)
        self.policy = PathPolicy(config.allowed_roots, excluded_roots=[config.profile_dir],
                                 mapped_s_root=getattr(config, '_auto_s_drive_root', None))
        self.display = display
        self.event_sink = event_sink
        self.cancel_event = cancel_event if cancel_event is not None else threading.Event()
        self.steering_poll = steering_poll
        self.steering_complete = steering_complete
        self._pending_steering_items = []
        self._active_turn_run_id = None
        self.feedback = Feedback(display, state)
        self.approvals = ApprovalManager(state, approval_decider, self.feedback)
        self.approvals.session_plan_approval = bool(getattr(config, '_session_plan_approval', False))
        self.approvals.fast_package_session = bool(getattr(config, '_continuous_package_session', False))
        self.approvals.supervised_session = bool(getattr(config, '_supervised_session', False))
        from .session_mode import configure_session
        self.approvals.on_revoke = lambda: configure_session(self.config, False)
        self.process_registry = ManagedProcessRegistry(state.directory)
        self.live_seen = {}
        self.navigation_domains = set()  # Fresh local browser approval only; never inherited on restart.
        self.navigation_binding = None
        self._next_turn_preparation = None
        self._prepared_attachment_uploads = {}
        if hasattr(browser, 'set_feedback'):
            browser.set_feedback(self._live_feedback)
        self.initialized = False
        self._prepared_initialization = None
        self.approved_attachment_hashes = {}
        self.approved_attachment_upload_names = {}
        self.base_context = {'config': config, 'session_dir': state.directory, 'browser': browser, 'session_state': state, 'approved': False,
                             'performance_trace': self.performance,
                             'path_policy': self.policy,
                             'pending_image_attachments': [], 'created_snapshots': {},
                             'pending_file_attachments': [],
                             'pending_visual_attachments': [], 'automatic_visual_context': {},
                             'approved_attachment_hashes': self.approved_attachment_hashes,
                             'site_knowledge_bindings': {},
                             'session_path_extensions': [],
                             'active_research_grants': {}, 'research_usage': {}, 'research_context': {'active': False},
                             'discovery_runs': {},
                             '_rea_runtime': {},
                             'login_attempts': {},
                             'web_document_tickets': {},
                             'document_catalogues': {}, 'download_manifest_hashes': {},
                             'transferred_attachment_hashes': {},
                             'website_private': True,
                             # Method ids are hashes of generic locator
                             # strategies; values are successful semantic
                             # locator methods only. Persisted per session.
                             'successful_locator_methods': state.data.setdefault('successful_locator_methods', {}),
                             'cancel_event': self.cancel_event, 'cancelled': self.cancel_event.is_set,
                             'process_registry': self.process_registry,
                             'approved_domains': self.state.data.setdefault('approved_domains', [])}
        self.base_context['automation_progress'] = lambda event: self.feedback.emit(
            'Automation package', json.dumps(event, ensure_ascii=False, sort_keys=True))
        def storage_attempt_notice(attempt, total, directory):
            s_path = self._display_s_path(directory)
            self.feedback.emit('System', f'Save attempt {attempt}/{total}; intended S: path {s_path}; '
                               f'resolved UNC filesystem path {directory}')
        self.base_context['storage_attempt_notice'] = storage_attempt_notice
        from .local_navigation import SessionNavigationGrant
        self.base_context['local_navigation_grant'] = SessionNavigationGrant(
            bool(getattr(config, '_local_navigation_confirmed', False)))
        def enable_discovery():
            from .session_mode import discovery_mode
            if not discovery_mode(config):
                configure_session(config, True)
            self.base_context['local_navigation_grant'].confirm()
            self._knowledge_authority(self.base_context)
        self.approvals.on_discovery_grant = enable_discovery
        def revoke_discovery():
            configure_session(config, False)
            self.base_context['local_navigation_grant'].revoke()
            self.navigation_domains.clear()
            self.navigation_binding = None
            self.state.data['approved_domains'].clear()
            for key in ('knowledge_session_authorized', 'knowledge_session_grant', 'approval_hash'):
                self.base_context.pop(key, None)
            if hasattr(browser, 'tool_domains'):
                browser.tool_domains = set(config.allowed_domains)
        self.approvals.on_revoke = revoke_discovery
        self._knowledge_authority(self.base_context)
        authorize = getattr(browser, 'authorize_tool_domain', None)
        if callable(authorize):
            for domain in self.state.data['approved_domains']:
                authorize(domain)
        self.download_service = None

    def _knowledge_authority(self, context):
        from .session_mode import discovery_mode
        if discovery_mode(self.config) and getattr(self.config, '_knowledge_session_confirmed', False):
            from .site_knowledge import knowledge_session_grant
            context['knowledge_session_authorized'] = True
            context['approval_hash'] = canonical_hash({'session': self.state.session_id,
                                                       'authority': 'sanitized_knowledge_session'})
            context['knowledge_session_grant'] = knowledge_session_grant(context)
        return context

    def _authorize_user_targets(self, text):
        """The session grant covers explicit public targets in the user's request."""
        from .session_mode import discovery_mode, website_origin
        import ipaddress
        from urllib.parse import urlsplit
        if not discovery_mode(self.config) or not isinstance(text, str):
            return
        for value in re.findall(r'https?://[^\s<>"\']+', text):
            value = value.rstrip('.,;!)]}')
            try:
                domain = URLPolicy.website_domain(value)
                if '.' not in domain or domain.endswith(('.local', '.internal', '.localhost', '.test')):
                    continue
                try:
                    ipaddress.ip_address(domain)
                except ValueError:
                    pass
                else:
                    continue
                if urlsplit(value).hostname != domain:
                    continue
                self.state.approve_domain(domain)
                self.navigation_domains.add(domain)
                self.config._session_approved_origins.add(website_origin(value))
                authorize = getattr(self.browser, 'authorize_tool_domain', None)
                if callable(authorize):
                    authorize(domain)
            except (PolicyError, ValueError):
                continue
        if self.navigation_domains:
            self.navigation_binding = _binding(self.browser)

    def _display_s_path(self, directory):
        import ntpath
        try:
            from .policy import mapped_s_drive_root
            relative = ntpath.relpath(str(Path(directory).resolve()), str(mapped_s_drive_root().resolve()))
            if relative == '..' or relative.startswith('..\\'):
                return self.prompts.storage_paths['s_path']
            return str(Path('S:/') / Path(relative))
        except (OSError, ValueError, PolicyError):
            return self.prompts.storage_paths['s_path']

    def _code_runner(self):
        return CodeRunner(self.policy, self.state.directory,
                          {'tool_timeout': self.config.tool_timeout,
                           'max_output_chars': self.config.max_output_chars})

    async def _parallel_readonly_group(self, calls, request_id):
        """Execute independent bounded reads, with one page observation per tab."""
        files = {'files.exists', 'files.metadata', 'files.hash', 'files.read'}
        passive = {'rea.inspect_page', 'rea.analyze_capture', 'rea.analyze_artifact',
                   'browser.recon', 'browser.route'}
        if (len(calls) < 2 or self.cancel_event.is_set()
                or not getattr(self.config, 'bounded_parallelism', True)
                or any(call.get('name') not in files | passive for call in calls)):
            return None
        contexts, tabs = [], set()
        try:
            for call in calls:
                if self.registry.definition(call['name'])['approval_policy'] != 'read_only':
                    return None
                if call['name'] in {'rea.inspect_page', 'browser.recon', 'browser.route'}:
                    tab = call['arguments'].get('tab_id', 'tab-1')
                    if tab in tabs:
                        return None
                    tabs.add(tab)
                context = self._knowledge_authority(dict(self.base_context))
                context.update(source_request_id=request_id, source_call_id=call['call_id'], parallel_readonly=True)
                self.registry.validate_call(call['name'], call['arguments'], context)
                contexts.append(context)
        except Exception:
            return None  # The serial path produces the authoritative diagnostic.
        for call in calls:
            self.state.begin_call(call, state_changing=False)
        semaphore = asyncio.Semaphore(4)
        async def run_one(call, context):
            async with semaphore:
                try:
                    if call['name'] in files:
                        result = await asyncio.to_thread(lambda: asyncio.run(
                            self.registry.execute(call['name'], call['arguments'], context)))
                        method = 'parallel_thread'
                    else:
                        result = await self.registry.execute(call['name'], call['arguments'], context)
                        method = 'parallel_async'
                    result.setdefault('result', {}).setdefault('execution_method', method)
                    return result
                except Exception:
                    return {'ok': False, 'tool': call['name'],
                            'result': {'status': 'failed', 'side_effects_uncertain': False},
                            'error': {'code': 'operation_failed', 'message': 'Independent read failed; inspect its evidence before changing the method.'}}
        outcomes = await asyncio.gather(*(run_one(call, context) for call, context in zip(calls, contexts)))
        results = {}
        for call, outcome in zip(calls, outcomes):
            self.state.finish_call(call['call_id'], outcome)
            results[call['call_id']] = outcome
        return results

    def _live_feedback(self, event):
        request_id = event['request_id']
        if event['type'] == 'generation':
            self.feedback.emit('System', event['message'], request_id=request_id)
            return
        if event['type'] == 'progress':
            self.feedback.emit('Copilot', redact(event.get('message', '')),
                               request_id=request_id, validated=False, visible_progress=True)
            return
        preview = public_preview(event.get('raw', ''), self.state.session_id, request_id)
        if any(preview.get(key) for key in ('user_response', 'action_plan')) and not self.live_seen.get(('timing', request_id)):
            self.performance.record('first_useful_output', request_id=request_id)
            self.live_seen[('timing', request_id)] = True
        self.feedback.record('Copilot', 'Streaming preview retained for diagnostics.',
                             request_id=request_id, validated=False,
                             generation_ended=event.get('generation_ended'), fields=preview)

    def _action_text(self, response):
        return '; '.join(str(step.get('step', '?')) + '. ' + str(step.get('action', '')) +
                         '\n  Check: ' + str(step.get('verification', ''))
                         for step in response.get('action_plan', []) if isinstance(step, dict))

    def _emit_validated_response(self, response, title):
        request_id = response.get('request_id')
        reply = response.get('user_response', '')
        process = [('Understanding', response.get('task_interpretation')),
                   ('Decision', response.get('decision_summary')),
                   ('Assumptions', response.get('assumptions')),
                   ('Plan', self._action_text(response)), ('Risk', response.get('risk_summary')),
                   ('Message', reply)]
        self.feedback.section('Copilot', 'PROCESS SUMMARY (DELIVERED) / ' + title, process,
                              request_id=request_id, validated=True)
        self.feedback.record('Copilot', title, request_id=request_id, validated=True,
                             task=response.get('task_interpretation'), action=self._action_text(response),
                             completion_status=response.get('completion_status'))
        if self.event_sink:
            self.event_sink('exchange', {'actor': 'Copilot', 'label': 'Copilot process summary (delivered)',
                                         'text': '\n\n'.join(label + ': ' + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
                                                              for label, value in process if value),
                                         'details': redact(response), 'request_id': request_id})
            if response.get('response_type') == 'tool_request':
                self.event_sink('plan', {'title': response.get('task_interpretation') or 'Action plan',
                                         'steps': response.get('action_plan', [])})

    def _emit_tool_result(self, name, result):
        payload = result.get('result', {}) if isinstance(result, dict) else {}
        review = payload.get('review', {}) if isinstance(payload, dict) else {}
        verification = payload.get('verification', {}) if isinstance(payload, dict) else {}
        windows = verification.get('windows', []) if isinstance(verification, dict) else []
        output_paths = [item.get('path') for item in payload.get('outputs', []) if isinstance(item, dict) and item.get('readable')]
        rows = [
            ('Status', payload.get('status', 'completed' if result.get('ok') else 'failed')),
            ('Outputs', output_paths),
            ('Verification', ({'ok': verification.get('ok'), 'visible_windows': len([item for item in windows if item.get('visible')]),
                               'target_displays': sorted({item.get('display_index') for item in windows})}
                              if windows else None)),
            ('Error', result.get('error', {}).get('message') if isinstance(result.get('error'), dict) else None),
        ]
        if name in {'automation.inspect', 'automation.run'} and isinstance(review, dict):
            rows.extend([
                ('ZIP review', review.get('summary')),
                ('What was checked', [{'item': item.get('item'), 'status': item.get('status'),
                                       'detail': item.get('detail')}
                                      for item in review.get('checks', []) if isinstance(item, dict)]),
                ('What failed', [{'item': item.get('item'), 'detail': item.get('detail'),
                                  'next_step': item.get('next_step')}
                                 for item in review.get('failures', []) if isinstance(item, dict)]),
                ('Future review setting', review.get('future_review_options')),
            ])
        if name == 'automation.run' and isinstance(payload, dict):
            failed_steps = []
            for stage in self._package_run_stage_details(payload):
                stage_name = str(stage.get('stage_id') or 'Package step').replace('_', ' ').capitalize()
                reason = stage.get('error') or stage.get('stderr') or stage.get('status') or 'The step did not complete.'
                certainty = stage.get('side_effects_uncertain')
                if certainty is False:
                    progress = 'The local runner stopped before this step started.'
                elif certainty is True:
                    progress = 'This step started, but its final result is uncertain.'
                else:
                    progress = 'The run record does not confirm whether this step started.'
                failed_steps.append({'step': stage_name, 'result': progress, 'reason': str(reason)[:800]})
            validation_errors = payload.get('validation', {}).get('errors', [])
            rows.extend([
                ('Run summary', payload.get('summary')),
                ('Package run', payload.get('status', 'unknown')),
                ('Steps that failed', failed_steps or ([
                    {'step': str(stage_id).replace('_', ' ').capitalize(),
                     'result': 'Did not complete; no detailed stage record was available.'}
                    for stage_id in payload.get('failed_stages', [])] if payload.get('failed_stages') else [])),
                ('Expected files still missing or unchecked', validation_errors),
            ])
        self.feedback.section('Tool/' + name, 'RESULT', rows)
        if self.event_sink:
            status = ('completed' if result.get('ok') else 'uncertain'
                      if payload.get('side_effects_uncertain') else 'failed')
            summary = (result.get('error', {}).get('message') if isinstance(result.get('error'), dict)
                       else payload.get('summary') or payload.get('status', 'Observed result'))
            self.event_sink('tool', {'name': name, 'status': status, 'summary': summary,
                                     'result': redact(result)})

    def _package_run_stage_details(self, run_result):
        """Read concise failure details from the captured run result or its retained checkpoint."""
        direct = run_result.get('stage_results')
        if isinstance(direct, list) and direct:
            return [item for item in direct if isinstance(item, dict)]
        state_path = run_result.get('state_path')
        if not isinstance(state_path, str) or not state_path:
            return []
        try:
            resolved = self.policy.resolve(state_path, must_exist=True)
            saved = json.loads(resolved.read_text(encoding='utf-8'))
            stages = saved.get('stages', {}) if isinstance(saved, dict) else {}
            failed_ids = set(run_result.get('failed_stages', []))
            details = []
            for stage_id, record in stages.items():
                if stage_id not in failed_ids and record.get('status') != 'failed':
                    continue
                outcome = record.get('result', {})
                if not isinstance(outcome, dict):
                    outcome = {}
                item = {'stage_id': stage_id, 'status': record.get('status')}
                for key in ('error', 'stderr', 'stdout', 'side_effects_uncertain'):
                    value = outcome.get(key, record.get(key))
                    if value is not None:
                        item[key] = str(value)[:1200] if key in {'error', 'stderr', 'stdout'} else value
                details.append(item)
            return details
        except (OSError, ValueError, TypeError, PolicyError):
            return []

    def _package_run_repair_instruction(self, results):
        """Return a direct Copilot repair request from captured local package-run failures."""
        failed_runs = []
        for result in results:
            if not isinstance(result, dict) or result.get('tool') != 'automation.run':
                continue
            run = result.get('result', {})
            if (not isinstance(run, dict) or run.get('status') in {'not_started', 'cancelled'}
                    or isinstance(run.get('review'), dict)):
                continue
            validation = run.get('validation', {})
            if (run.get('status') == 'completed' and not run.get('failed_stages')
                    and isinstance(validation, dict) and validation.get('ok') is True):
                continue
            failed_runs.append((run, self._package_run_stage_details(run)))
        if not failed_runs:
            return None
        lines = [
            'The local package run did not pass. Use the captured stage and output results below to repair the package automatically; do not ask the user to inspect it or write a repair request.'
        ]
        local_runner_boundary = False
        for run, stages in failed_runs:
            lines.append('Local run status: ' + str(run.get('status') or 'failed') + '.')
            approved_root = run.get('output_root')
            for stage in stages:
                stage_name = str(stage.get('stage_id') or 'Package step')
                detail = stage.get('error') or stage.get('stderr') or stage.get('status') or 'The step did not complete.'
                certainty = stage.get('side_effects_uncertain')
                if certainty is False:
                    start_status = 'The local runner confirms this step was rejected before it started.'
                    if 'WinError 267' in str(detail) or 'The directory name is invalid' in str(detail):
                        local_runner_boundary = True
                elif certainty is True:
                    start_status = 'This step started, but its final effect is uncertain; do not describe it as successful.'
                else:
                    start_status = 'The local result does not confirm whether this step started.'
                lines.append(f'- Failed step {stage_name}: {str(detail)[:1000]} {start_status}')
                attempted = stage.get('attempted_path')
                if not attempted:
                    match = re.search(
                        r'(?:File write is outside the approved create/modify scope|'
                        r'Directory inspection is outside the approved read scope|'
                        r'File read is outside the approved scope|Output path)\s*:\s*([^\r\n]+)',
                        str(detail))
                    attempted = match.group(1).strip().strip("'\"") if match else None
                if attempted and approved_root:
                    lines.append(
                        f'The package attempted to access or write `{attempted}`. '
                        f'The approved output folder is `{approved_root}`. '
                        'Update the package so all declared outputs are written beneath the approved '
                        'output folder supplied as the final stage argument (`sys.argv[-1]`). '
                        'Do not infer the output path from the working directory or scan sibling run folders.')
            validation = run.get('validation', {})
            if isinstance(validation, dict) and validation.get('errors'):
                lines.append('Output checks that did not pass: ' + '; '.join(
                    str(item)[:500] for item in validation['errors'][:20]))
            if not stages and not (isinstance(validation, dict) and validation.get('errors')):
                lines.append('Failed steps recorded: ' + ', '.join(map(str, run.get('failed_stages', []))))
        if local_runner_boundary:
            lines.append('This failure is at the local runner boundary, not in the ZIP: Windows rejected the runner working folder before package code started. Do not change package code to work around it, do not rebuild or rerun the ZIP, and do not claim a package failure. The local runner must be corrected before another run.')
        else:
            lines.append('Fix every reported cause in the package, then run the relevant build and package tests in Copilot\'s cloud sandbox. Deliver a fresh clickable ZIP with matching integrity hashes. The local orchestrator will automatically inspect that revision and show its findings; request the next local run only after the fresh review passes.')
        lines.append('Do not claim the local run succeeded until the orchestrator reports that the corrected package and its outputs passed.')
        return '\n'.join(lines)

    @staticmethod
    def _latest_failed_package_run(calls):
        """Restore an unfinished package failure when a Copilot reply is recovered after restart."""
        if not isinstance(calls, dict):
            return None
        for call_id, record in reversed(list(calls.items())):
            if not isinstance(record, dict) or record.get('request', {}).get('name') != 'automation.run':
                continue
            result = record.get('result', {})
            error_code = result.get('error', {}).get('code') if isinstance(result, dict) else None
            if error_code in {'approval_denied', 'package_review_required', 'package_review_failed'}:
                return None
            run = result.get('result', {}) if isinstance(result, dict) else {}
            if (isinstance(run, dict) and run.get('status') not in {None, 'not_started', 'cancelled'}
                    and (run.get('status') != 'completed' or run.get('failed_stages')
                         or run.get('validation', {}).get('ok') is not True)):
                return {'call_id': call_id, **result}
            return None
        return None

    def _recovered_package_run_failure(self):
        """Restore a compact package failure from its retained local run checkpoint."""
        path = self.state.data.get('package_run_failure_state_path')
        if not isinstance(path, str) or not path:
            return None
        try:
            resolved = self.policy.resolve(path, must_exist=True)
            saved = json.loads(resolved.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError, PolicyError):
            return None
        expected_hash = self.state.data.get('package_run_failure_archive_sha256')
        if ((expected_hash and saved.get('archive_sha256') != expected_hash)
                or saved.get('status') not in {'failed', 'partial'}):
            return None
        stage_records = saved.get('stages', {})
        if not isinstance(stage_records, dict):
            stage_records = {}
        failed_stages = [stage_id for stage_id, record in stage_records.items()
                         if isinstance(record, dict) and record.get('status') == 'failed']
        result = {'status': saved.get('status'), 'run_id': saved.get('run_id'),
                  'archive_sha256': saved.get('archive_sha256'), 'failed_stages': failed_stages,
                  'validation': saved.get('validation', {}), 'state_path': str(resolved),
                  'output_root': str(resolved.parent / 'outputs')}
        return {'call_id': self.state.data.get('package_run_failure_call_id'),
                'tool': 'automation.run', 'ok': True, 'result': result}

    @staticmethod
    def _package_review_repair_instruction(results):
        """Turn failed local ZIP checks into one actionable Copilot repair request."""
        failures = []
        summaries = []
        handoff_errors = []
        for result in results:
            if (not isinstance(result, dict) or result.get('tool') not in {'automation.inspect', 'automation.run'}
                    or result.get('ok')):
                continue
            review = result.get('result', {}).get('review', {})
            if not isinstance(review, dict):
                error = result.get('error', {})
                if isinstance(error, dict):
                    handoff_errors.append(str(error.get('message') or error.get('code') or
                                               'The local reviewer could not open the downloaded ZIP.')[:500])
                continue
            if review.get('summary'):
                summaries.append(str(review['summary'])[:400])
            for failure in review.get('failures', []):
                if not isinstance(failure, dict):
                    continue
                item = str(failure.get('item') or 'Package check')[:160]
                detail = str(failure.get('detail') or 'The local check did not pass.')[:500]
                next_step = str(failure.get('next_step') or 'Correct this issue and rerun the local checks.')[:400]
                failures.append((item, detail, next_step))
        if not failures:
            if not handoff_errors:
                return None
            return (
                'The downloaded package could not be fully checked locally: ' + '; '.join(handoff_errors) +
                '. No package stage was run locally. Provide a fresh clickable ZIP link and request its download '
                'so the local orchestrator can review that revision. Do not ask the user to inspect files.'
            )
        lines = [
            'The local ZIP review did not pass. Please fix every finding below together, rebuild the ZIP, '
            'then run the relevant build and package tests in Copilot\'s cloud sandbox when available and report '
            'the checks and results. Cloud tests do not replace a user-requested live test in the local agent environment; do not claim live success from cloud results.'
        ]
        if summaries:
            lines.append('Review result: ' + '; '.join(dict.fromkeys(summaries)))
        for item, detail, next_step in failures:
            lines.append(f'- {item}: {detail} Change needed: {next_step}')
        lines.extend([
            'In your next response, provide the rebuilt ZIP download link so the local orchestrator can '
            'download and inspect the new revision automatically. Do not ask the user to inspect files or write a repair request.',
            'No local package stages have run. Preserve package integrity hashes, safe scoped file paths and '
            'declared capabilities; do not weaken those required checks to make a code or integrity failure pass.'
        ])
        return '\n'.join(lines)

    @staticmethod
    def _package_local_build_rejection(name):
        if name not in {'files.create', 'files.append', 'files.copy', 'files.mkdir', 'files.replace',
                        'code_runner', 'archives.extract'}:
            return None
        return {
            'ok': False, 'tool': name,
            'result': {'status': 'not_started', 'side_effects_uncertain': False},
            'error': {'code': 'package_delivery_required',
                      'message': 'No local build or extraction ran. Create and test the package in Copilot Chat, then deliver its clickable ZIP link; the local orchestrator will download and review it. Local package execution uses automation.run only after a passing review and exact local approval.'}}

    @staticmethod
    def _routing_description(user_input):
        """Keep serialized tool arguments from distorting the user's task estimate."""
        markers = list(re.finditer(r"(?i)\b(?:tool\s+)?arguments\s*:\s*", user_input))
        for marker in reversed(markers):
            candidate = user_input[marker.end():].strip()
            if candidate.startswith('{'):
                return user_input[:marker.start()].strip()
        return user_input

    def _route_for_turn(self, candidate, recovered_response):
        """Keep package-only delivery rules attached to a recovered package turn."""
        if recovered_response is None:
            if candidate.get('route') != 'package':
                # A new direct user request supersedes an old package failure.
                self.state.data.pop('package_run_failure_call_id', None)
                self.state.data.pop('package_run_failure_state_path', None)
                self.state.data.pop('package_run_failure_archive_sha256', None)
            return candidate
        prior = self.state.data.get('task_routing')
        if isinstance(prior, dict) and prior.get('route') == 'package':
            return prior
        if self.state.data.get('package_run_failure_call_id'):
            return {**candidate, 'route': 'package', 'recovered_package_workflow': True}
        return prior if isinstance(prior, dict) else candidate

    def _review_passed(self, result):
        if not isinstance(result, dict) or result.get('ok') is not True:
            return False
        payload = result.get('result', {})
        review = payload.get('review', {}) if isinstance(payload, dict) else {}
        if not isinstance(review, dict):
            return False
        return ((payload.get('status') in {'validated', 'passed'} and review.get('status') == 'passed')
                or (getattr(self.config, '_package_review_enabled', True) is False
                    and payload.get('status') == 'ready_unreviewed' and review.get('status') == 'skipped'))

    def _record_package_delivery(self, reports, inspection_call_id, outcome):
        """Keep fresh and reused inspections on the same delivery-state path."""
        if not self._review_passed(outcome):
            return
        inspected = outcome['result']
        reports.append({
            'tool': 'automation.inspect', 'status': 'verified',
            'review_status': inspected.get('review', {}).get('status'),
            'path': inspected.get('archive'), 'sha256': inspected.get('archive_sha256'),
            'inspection_call_id': inspection_call_id,
        })

    def _prior_package_review(self, archive_sha256):
        """Find a complete local review for these exact immutable ZIP bytes."""
        if not isinstance(archive_sha256, str) or len(archive_sha256) != 64:
            return None
        for record in reversed(list(self.state.data.get('calls', {}).values())):
            if record.get('request', {}).get('name') != 'automation.inspect':
                continue
            result = record.get('result')
            if not isinstance(result, dict):
                continue
            payload = result.get('result', {})
            review = payload.get('review', {}) if isinstance(payload, dict) else {}
            observed = (review.get('archive_sha256') if isinstance(review, dict) else None) or (
                payload.get('archive_sha256') if isinstance(payload, dict) else None)
            if observed == archive_sha256:
                skipped = isinstance(review, dict) and review.get('status') == 'skipped'
                if skipped != (getattr(self.config, '_package_review_enabled', True) is False):
                    continue  # A startup choice cannot inherit authority from another mode.
                return deepcopy(result)
        return None

    async def _ensure_package_review(self, arguments, context):
        """Restore a missing review by rechecking the exact local ZIP before any run."""
        expected = arguments.get('expected_sha256')
        prior = self._prior_package_review(expected)
        if prior is not None:
            return prior
        review_call = {'call_id': 'auto-package-run-review-' + uuid.uuid4().hex,
                       'name': 'automation.inspect', 'version': '1.0',
                       'arguments': {'path': arguments.get('archive_path', ''),
                                     'expected_sha256': expected},
                       'expected_result': 'Recheck this exact ZIP locally before any package run.'}
        try:
            archive, actual = self._local_archive_sha256(arguments.get('archive_path', ''))
            review_call['arguments']['path'] = str(archive)
            if actual != expected:
                review = {'status': 'failed',
                          'summary': 'The ZIP no longer matches the fingerprint requested for the run.',
                          'archive_sha256': actual,
                          'checks': [{'item': 'Downloaded ZIP matches the promised file', 'status': 'failed',
                                      'detail': 'The current file hash differs from the run request.'}],
                          'failures': [{'item': 'Downloaded ZIP matches the promised file',
                                        'detail': 'The current file hash differs from the run request.',
                                        'next_step': 'Use the exact locally reviewed ZIP fingerprint.'}],
                          'not_checked_count': 0,
                          'future_review_options': ['The exact ZIP fingerprint and local run approval remain required.']}
                result = {'ok': False, 'tool': 'automation.inspect',
                          'result': {'status': 'failed', 'archive_sha256': actual, 'review': review},
                          'error': {'code': 'package_review_failed',
                                    'message': 'The ZIP changed after the run request was prepared.'}}
            else:
                immediate = getattr(self.config, '_package_review_enabled', True) is False
                self.feedback.section('Orchestrator', 'PACKAGE LOAD' if immediate else 'AUTOMATIC ZIP REVIEW', [
                    ('Status', 'Quality review skipped for this session' if immediate else 'Restoring the exact ZIP review with a fresh local check'),
                    ('File', archive.name), ('SHA-256', actual),
                    ('Local execution', 'Session startup authorization is active' if immediate else 'Not started; the run still requires its separate approval')])
                self.state.begin_call(review_call, state_changing=False)
                definition = self.registry.definition('automation.inspect')
                review_context = dict(context, source_request_id=context.get('source_request_id'))
                try:
                    result = await asyncio.wait_for(
                        self.registry.execute('automation.inspect', review_call['arguments'], review_context),
                        timeout=float(definition.get('timeout', 30)) + 1)
                except Exception as error:
                    result = {'ok': False, 'tool': 'automation.inspect',
                              'result': {'status': 'failed', 'archive_sha256': actual, 'review': {
                                  'status': 'failed',
                                  'summary': 'The local reviewer could not restore the ZIP review.',
                                  'archive_sha256': actual,
                                  'checks': [{'item': 'Local package review', 'status': 'failed',
                                              'detail': str(error)[:500]}],
                                  'failures': [{'item': 'Local package review', 'detail': str(error)[:500],
                                                'next_step': 'Review the local inspection result before any run.'}],
                                  'not_checked_count': 0,
                                  'future_review_options': ['A passing local review remains required before a run.']}},
                              'error': {'code': 'package_review_unavailable',
                                        'message': str(error)[:500]}}
                self.state.finish_call(review_call['call_id'], result)
                self._emit_tool_result('automation.inspect', result)
                return result
        except (OSError, PolicyError, ValueError, KeyError) as error:
            review = {'status': 'failed',
                      'summary': 'The local reviewer could not verify the exact ZIP requested for this run.',
                      'archive_sha256': expected,
                      'checks': [{'item': 'Local package review', 'status': 'failed',
                                  'detail': str(error)[:500]}],
                      'failures': [{'item': 'Local package review', 'detail': str(error)[:500],
                                    'next_step': 'Provide a readable ZIP in an approved local delivery folder.'}],
                      'not_checked_count': 0,
                      'future_review_options': ['A passing local review remains required before a run.']}
            result = {'ok': False, 'tool': 'automation.inspect',
                      'result': {'status': 'failed', 'review': review},
                      'error': {'code': 'package_review_unavailable', 'message': str(error)[:500]}}
        self.state.begin_call(review_call, state_changing=False)
        self.state.finish_call(review_call['call_id'], result)
        self._emit_tool_result('automation.inspect', result)
        return result

    def _local_archive_sha256(self, path):
        """Hash one allowed local archive without loading it all into memory."""
        resolved = self.policy.resolve(path, must_exist=True)
        size = resolved.stat().st_size
        if not resolved.is_file() or size > max(50 * 1024 * 1024, self.config.max_download_bytes):
            raise PolicyError('Package review requires a regular ZIP within the local review size limit')
        digest = hashlib.sha256()
        with resolved.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return resolved, digest.hexdigest()

    def _queue_reviewed_package_run(self, calls, inspection):
        """Continue a package task locally after inspection, before another chat turn."""
        if not self._review_passed(inspection):
            return
        reviewed = inspection.get('result', {})
        digest = reviewed.get('archive_sha256')
        archive = reviewed.get('archive')
        if not archive or not digest or any(
                call['name'] == 'automation.run'
                and call.get('arguments', {}).get('expected_sha256') == digest for call in calls):
            return
        resolved, actual = self._local_archive_sha256(archive)
        if actual != digest:
            return  # A changed ZIP must be inspected again before proposing execution.
        call = {'call_id': 'auto-package-run-' + uuid.uuid4().hex,
                'name': 'automation.run', 'version': self.registry.definition('automation.run')['version'],
                'arguments': {'archive_path': str(resolved), 'expected_sha256': digest,
                              'workspace': str(self.config.workspace_dir / 'automation-packages')},
                'expected_result': 'Run the approved package locally and return final verified stage and output results.'}
        calls.append(call)
        self.state.event('package_run_queued', call_id=call['call_id'], archive_sha256=digest,
                         origin='orchestrator')
        self.feedback.emit('Orchestrator',
            'ZIP loaded without quality review. Starting the session-authorized package run.'
            if reviewed.get('review', {}).get('status') == 'skipped' else
            'ZIP review passed. Continuing to local package approval and execution before returning results to Copilot.')

    async def _inspect_downloaded_package(self, download_result, source_request_id):
        """Immediately inspect one verified Copilot ZIP and retain the local review result."""
        call = {'call_id': 'auto-package-review-' + uuid.uuid4().hex,
                'name': 'automation.inspect', 'version': '1.0',
                'arguments': {},
                'expected_result': 'Show every package check and every failure before any local run.'}
        result = None
        try:
            artifact = self._delivery_result('copilot.download', download_result)
            if not isinstance(artifact, dict) or artifact.get('status') not in {'verified', 'downloaded'}:
                raise ValueError('The download result does not confirm a retained, readable ZIP.')
            artifact_path = artifact.get('path')
            if isinstance(artifact_path, str) and artifact_path:
                call['arguments'] = {'path': artifact_path}
            path = self.policy.resolve(artifact.get('path', ''), must_exist=True)
            digest = artifact.get('sha256')
            if path.suffix.casefold() != '.zip':
                raise ValueError('The delivered file is not a ZIP package.')
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
                raise ValueError('The verified download did not include a usable SHA-256 fingerprint.')
            call['arguments'] = {'path': str(path), 'expected_sha256': digest}
            previous = self._prior_package_review(digest)
            if previous is not None:
                result = previous
                # Review authority is bound to ZIP bytes; delivery provenance
                # must describe this freshly verified local copy of those bytes.
                result['result']['archive'] = str(path)
                result['review_reused'] = True
                self.state.begin_call(call, state_changing=False)
                self.state.finish_call(call['call_id'], result)
                self.feedback.emit('Orchestrator', 'This exact ZIP fingerprint was already reviewed; reusing its recorded result instead of repeating the review.')
            else:
                context = dict(self.base_context)
                context['source_request_id'] = source_request_id
                immediate = getattr(self.config, '_package_review_enabled', True) is False
                self.feedback.section('Orchestrator', 'PACKAGE LOAD' if immediate else 'AUTOMATIC ZIP REVIEW', [
                    ('Status', 'Quality review skipped for this session' if immediate else 'Starting local read-only review'),
                    ('File', path.name), ('SHA-256', digest),
                    ('Local execution', 'Session startup authorization is active' if immediate else 'Not started; package run approval remains separate')])
                self.state.begin_call(call, state_changing=False)
                definition = self.registry.definition('automation.inspect')
                try:
                    result = await asyncio.wait_for(
                        self.registry.execute('automation.inspect', call['arguments'], context),
                        timeout=float(definition.get('timeout', 30)) + 1)
                except Exception as error:
                    result = {'ok': False, 'tool': 'automation.inspect',
                              'result': {'status': 'failed'},
                              'error': {'code': 'package_review_unavailable',
                                        'message': str(error)[:500]}}
                self.state.finish_call(call['call_id'], result)
        except Exception as error:
            result = {'ok': False, 'tool': 'automation.inspect',
                      'result': {'status': 'failed', 'review': {
                          'status': 'failed', 'summary': 'The local reviewer could not inspect this delivered ZIP.',
                          'archive_sha256': None,
                          'checks': [{'item': 'Local download handoff', 'status': 'failed',
                                      'detail': str(error)[:400],
                                      'next_step': 'Deliver a fresh actual ZIP link from Copilot Chat.'}],
                          'failures': [{'item': 'Local download handoff', 'detail': str(error)[:400],
                                        'next_step': 'Deliver a fresh actual ZIP link from Copilot Chat.'}],
                          'not_checked_count': 0,
                          'future_review_options': ['Review policy settings can be adjusted later for optional format preferences; file integrity and exact local run approval remain required.']}},
                      'error': {'code': 'package_review_handoff_failed', 'message': str(error)[:500]}}
            if call['arguments']:
                self.state.begin_call(call, state_changing=False)
                self.state.finish_call(call['call_id'], result)
        self._emit_tool_result('automation.inspect', result)
        return {'call_id': call['call_id'], **result}

    @staticmethod
    def _download_recovery_instruction(results):
        """Give Copilot a concrete next step when an artifact download did not start."""
        failed = [item for item in results if isinstance(item, dict)
                  and item.get('tool') == 'copilot.download' and not item.get('ok')
                  and item.get('result', {}).get('status') == 'not_started']
        if not failed:
            return None
        return (
            'The local download did not start. No artifact was downloaded and this result is not a user denial. '
            'In your next response, provide one real clickable link for the requested artifact after the END marker, '
            'then request copilot.download in that same response with expected_name and link_text equal to the '
            'artifact basename and exact visible link label. Use expected_sha256 only if independently verified. '
            'Do not point to a guessed URL, a prior-turn link, a sandbox path, or an existing local file. '
            'If Copilot cannot provide a real link, report that observed delivery limit plainly. '
            'For an automation ZIP, let the local orchestrator download and run automation.inspect before any package execution.'
        )

    def _attachment_record(self, path: Path) -> dict:
        allowed = SUPPORTED_EXTENSIONS
        if not path.is_file() or path.suffix.lower() not in allowed:
            raise PolicyError('Attachment must be a regular supported document or image')
        size = path.stat().st_size
        if size > self.config.max_attachment_bytes:
            raise PolicyError('Attachment exceeds configured size limit')
        digest = self._bounded_hash(path)
        if path.suffix.lower() in TEXT_EXTENSIONS:
            with path.open('r', encoding='utf-8-sig') as handle:
                if SENSITIVE.search(handle.read(self.config.max_attachment_bytes + 1)):
                    raise PolicyError('Credential-like text cannot be attached')
        return {'path': str(path), 'sha256': digest, 'size': size, 'upload_name': upload_name(path)}

    def attachment_queue(self):
        """Prepare selected attachment sources without discovering cloud roots."""
        # Browser uploads are staged beneath an opaque workspace-owned root.
        # Trust that root only for attachment ingestion; it is never added to
        # the broader filesystem tool policy.
        return AttachmentQueue(self.config, account_root=getattr(self.config, '_ui_upload_root', None))

    def _bounded_hash(self, path: Path) -> str:
        if not path.is_file() or path.stat().st_size > self.config.max_attachment_bytes:
            raise PolicyError('Attachment must be a regular file within the configured size limit')
        digest, consumed = hashlib.sha256(), 0
        with path.open('rb') as handle:
            while chunk := handle.read(65536):
                consumed += len(chunk)
                if consumed > self.config.max_attachment_bytes:
                    raise PolicyError('Attachment grew beyond the configured size limit')
                digest.update(chunk)
        return digest.hexdigest()

    def _direction_independent_attachments(self):
        """Files whose inclusion cannot depend on the next user request."""
        paths = []
        if self.findings.attachment_due(self.state.message_count + 1):
            paths.append(self.findings.attachment)
        paths.extend(map(Path, self.base_context['pending_image_attachments']))
        paths.extend(map(Path, self.base_context['pending_file_attachments']))
        paths.extend(map(Path, self.base_context.get('pending_visual_attachments', [])))
        unique = list(dict.fromkeys(map(Path, paths)))
        if len(unique) > 20:
            return []
        for path in unique:
            record = self._attachment_record(path)
            approved = self.approved_attachment_hashes.get(str(path))
            if approved is not None and record['sha256'] != approved:
                raise PolicyError('An approved attachment changed; preparation was cancelled')
        return unique

    async def prepare_pending_attachments(self):
        """Preattach safe request-independent files during the user's think time."""
        prepare = getattr(self.browser, 'preload_attachments', None)
        paths = self._direction_independent_attachments()
        if not callable(prepare) or not paths:
            return {'status': 'skipped', 'count': 0}
        upload_paths = []
        for path in paths:
            approved = self.approved_attachment_hashes.get(str(path))
            upload_paths.append(self._stage_approved(path, approved) if approved else path)
        result = await prepare(upload_paths)
        self._prepared_attachment_uploads.update({
            (str(source), self._bounded_hash(source)): upload
            for source, upload in zip(paths, upload_paths)
        })
        self.state.event('next_turn_attachments_prepared', count=len(paths),
                         names=[path.name for path in paths])
        self.state.save()
        return result

    def _schedule_next_turn_preparation(self):
        """Start preparation without delaying delivery of a completed response."""
        if self._next_turn_preparation is not None and not self._next_turn_preparation.done():
            return
        try:
            if not self._direction_independent_attachments():
                self._next_turn_preparation = None
                return
        except (PolicyError, OSError, ValueError) as exc:
            self.state.event('next_turn_attachment_preparation_skipped', error=str(exc))
            self.state.save()
            return
        self._next_turn_preparation = asyncio.create_task(self.prepare_pending_attachments())

    async def _finish_next_turn_preparation(self):
        task = self._next_turn_preparation
        self._next_turn_preparation = None
        if task is None:
            return
        try:
            await task
        except (BrowserUIError, PolicyError, OSError, ValueError) as exc:
            # Preparation never clicks Send; the normal verified upload path
            # remains available for the actual message.
            self.state.event('next_turn_attachment_preparation_failed', error=str(exc))
            self.state.save()

    def _stage_approved(self, path: Path, expected_hash: str, target_name=None) -> Path:
        """Copy reviewed bytes to a retained unique upload snapshot, verify before use."""
        self._attachment_record(path)
        directory = self.state.directory / 'approved_uploads' / uuid.uuid4().hex
        directory.mkdir(parents=True)
        target = directory / (target_name or upload_name(path))
        digest, consumed = hashlib.sha256(), 0
        with path.open('rb') as source, target.open('xb') as dest:
            while chunk := source.read(65536):
                consumed += len(chunk)
                if consumed > self.config.max_attachment_bytes:
                    raise PolicyError('Approved file grew beyond its size limit; retained unsent partial snapshot')
                digest.update(chunk)
                dest.write(chunk)
        if digest.hexdigest() != expected_hash:
            raise PolicyError('Approved attachment changed; snapshot retained but not uploaded')
        return target

    async def _send(self, kind: str, content, extra_attachments=()):
        started_preparation = time.monotonic()
        self.state.repair_browser_observations()
        await self._finish_next_turn_preparation()
        from .reconciliation import close_quarantined_tabs
        await close_quarantined_tabs(self.browser)
        prepared = self._prepared_initialization if kind == 'initialize' and not extra_attachments else None
        if prepared is not None:
            request_id, text, attachments = (prepared['request_id'], prepared['text'],
                                             list(prepared['attachments']))
            self._prepared_initialization = None
        else:
            request_id = uuid.uuid4().hex
            with self.performance.span('prompt_assembly', request_id=request_id):
                text, attachments = self.prompts.build(kind, redact(content), request_id)
        pending_images = self.base_context['pending_image_attachments']
        pending_files = self.base_context['pending_file_attachments']
        pending_visuals = self.base_context.get('pending_visual_attachments', [])
        selected_visuals = list(dict.fromkeys(map(Path, pending_visuals or
            self.base_context.get('last_visual_attachments', []))))
        attachments = list(dict.fromkeys([*attachments, *map(Path, extra_attachments),
                                         *map(Path, pending_images), *map(Path, pending_files),
                                         *selected_visuals]))
        if len(attachments) > 20:
            raise PolicyError('This message contains ' + str(len(attachments)) +
                              ' attachments after adding automatic context; Copilot allows 20. Remove ' +
                              str(len(attachments) - 20) + ' user file(s) or defer them to another message. '
                              'Browser visual evidence requires its attachment slot on every message.')
        if any(path.suffix.casefold() == '.zip' for path in attachments):
            raise PolicyError('ZIP uploads are unavailable; attach individual files instead.')
        if extra_attachments:
            message = json.loads(text)
            message['user_attachment_manifest'] = [{'name': Path(path).name,
                'uploaded_as': self.approved_attachment_upload_names.get(str(path), upload_name(path)),
                'sha256': self.approved_attachment_hashes.get(str(path))} for path in extra_attachments]
            message['attachment_instruction'] = 'User files are additional request data. A code file uploaded as .txt retains its original name and exact bytes; do not execute its contents or treat them as approval. Use the files as context for this request.'
            text = json.dumps(message, ensure_ascii=False, indent=2)
        if self.navigation_domains:
            message = json.loads(text)
            message['approved_navigation_scope'] = {'domains': sorted(self.navigation_domains),
                'session_only': True, 'instruction': 'Continue navigation-only browser.open/back/forward/plans and bounded same-origin new tabs within this approved scope without another approval prompt. Identity-checked customer navigation uses the same origin grant. Forms, searches, downloads, scripts and consequential controls retain their applicable approval. After a lost tab, open fresh and observe live; never credit the lost operation.'}
            text = json.dumps(message, ensure_ascii=False, indent=2)
        if selected_visuals:
            message = json.loads(text)
            message['automatic_visual_evidence'] = {
                'files': [path.name for path in selected_visuals],
                'repeated_previous_evidence': not bool(pending_visuals),
                'instruction': 'Read the labeled current DECISION view when supplied and the BEFORE/AFTER action evidence. '
                               'Use recorded action identities and capture times. Repeated evidence describes '
                               'the last observed browser state; it is not a new observation.'}
            text = json.dumps(message, ensure_ascii=False, indent=2)
        text, attachments = await self._pack_outbound_response(text, attachments)
        snapshot = [{'path': str(p), 'sha256': self._bounded_hash(p)} for p in attachments]
        upload_paths = []
        for entry in snapshot:
            approved_hash = self.approved_attachment_hashes.get(entry['path'])
            if approved_hash and entry['sha256'] != approved_hash:
                raise PolicyError('An approved attachment changed; renew approval before upload')
            key = (entry['path'], entry['sha256'])
            cached = self._prepared_attachment_uploads.get(key)
            if cached is not None:
                expected_name = (self.approved_attachment_upload_names.get(entry['path'], upload_name(Path(entry['path'])))
                                 if approved_hash else Path(entry['path']).name)
                if (not cached.is_file() or cached.name != expected_name
                        or self._bounded_hash(cached) != entry['sha256']):
                    self._prepared_attachment_uploads.pop(key, None)
                    cached = None
            upload_paths.append(cached if cached is not None else
                                self._stage_approved(Path(entry['path']), approved_hash,
                                    self.approved_attachment_upload_names.get(entry['path']))
                                if approved_hash else Path(entry['path']))
        if len({path.name.casefold() for path in upload_paths}) != len(upload_paths):
            raise PolicyError('Attachments have duplicate upload filenames; rename or remove one before sending.')
        if SENSITIVE.search(text):
            raise PolicyError('Sensitive values cannot be transmitted to Copilot')
        self.live_seen.clear()
        attachment_note = (' with ' + str(len(upload_paths)) + ' attachment(s)'
                           if upload_paths else '')
        self.feedback.emit('Orchestrator', 'Sending your request to Copilot' + attachment_note + '.',
                           request_id=request_id)
        delivered = redact(content)
        self.feedback.emit('Orchestrator', exchange_summary(kind,delivered), request_id=request_id)
        if self.event_sink:
            self.event_sink('exchange', {'actor': 'Orchestrator', 'label': 'Orchestrator → Copilot',
                                         'text': delivered if isinstance(delivered, str) else json.dumps(delivered, ensure_ascii=False, indent=2),
                                         'request_id': request_id, 'message_kind': kind})
        if upload_paths:
            self.feedback.emit('System', 'Upload files: ' + ', '.join(path.name for path in upload_paths), request_id=request_id)
        self.state.begin_submission(request_id, text)
        self.performance.record('attachment_preparation', request_id=request_id,
                                duration_ms=(time.monotonic() - started_preparation) * 1000,
                                characters=len(text), bytes=sum(entry.get('size', 0) for entry in snapshot))
        self.state.data['status'] = 'submitting'
        self.state.save()
        def committed():
            self.state.confirm_submission(request_id, attachments=snapshot,
                                          findings_path=self.findings.attachment)
            ordinal = self.state.message_count
            for entry in snapshot:
                if Path(entry['path']) in list(map(Path, pending_files)):
                    history = self.base_context['transferred_attachment_hashes']
                    history[entry['sha256']] = history.get(entry['sha256'], 0) + 1
                self._prepared_attachment_uploads.pop((entry['path'], entry['sha256']), None)
            pending_images.clear()
            pending_files.clear()
            pending_visuals[:] = [path for path in pending_visuals if Path(path) not in selected_visuals]
            if selected_visuals:
                self.base_context['last_visual_attachments'] = list(map(str, selected_visuals))
            self.state.save()
        try:
            with self.performance.span('browser_exchange', request_id=request_id):
                raw = await self.browser.exchange(text, request_id, attachments=upload_paths,
                                                  on_submitted=committed)
        except SubmissionNotSentError:
            self.state.reconcile_submission(False)
            self.state.data['status'] = 'blocked'
            self.state.event('submission_proven_not_sent', request_id=request_id)
            self.state.save()
            raise
        except SubmissionAmbiguousError:
            self.state.data['status'] = 'submission_uncertain'
            self.state.event('submission_uncertain', request_id=request_id)
            self.state.save()
            raise
        except CaptureTimeoutError:
            self.state.data['status'] = 'capture_failed'
            self.state.event('capture_failed', request_id=request_id)
            self.state.save()
            raise
        except Exception:
            # Browser adapter leaves a pending intent when it cannot prove non-submission.
            self.state.data['status'] = 'blocked'
            self.state.save()
            raise
        finally:
            self.performance.flush()
        self._record_raw_response(raw, request_id)
        return raw, request_id

    def _record_raw_response(self, raw: str, request_id: str) -> None:
        """Retain a recaptured reply once, including after a crash between file and ledger saves."""
        raw_path = self.state.directory / 'responses' / (request_id + '.txt')
        from .web_privacy import PRIVATE_TOOLS
        if any('"' + name + '"' in raw for name in PRIVATE_TOOLS):
            self.state.data['website_private'] = True
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        from .web_privacy import audit_evidence
        persisted_content = audit_evidence(raw) if self.state.data.get('website_private') else redact(raw)
        serialized = json.dumps(persisted_content) if self.state.data.get('website_private') else persisted_content
        try:
            with raw_path.open('x', encoding='utf-8') as handle:
                handle.write(serialized)
        except FileExistsError:
            if raw_path.read_text(encoding='utf-8') != serialized:
                raise BrowserUIError('Recovered reply differs from the retained response artifact; no continuation ran.')
        prior = [message for message in self.state.data['messages']
                 if message.get('role') == 'copilot_raw' and message.get('request_id') == request_id]
        if prior:
            if len(prior) != 1 or prior[0].get('content') not in (persisted_content, redact(raw)):
                raise BrowserUIError('Recovered reply differs from the retained session record; no continuation ran.')
            return
        self.state.message('copilot_raw', raw, request_id=request_id, artifact=str(raw_path))

    async def _pack_outbound_response(self, text, attachments):
        from .outbound_results import pack_outbound, composer_characters, HISTORICAL_COMPOSER_LIMIT
        if SENSITIVE.search(text):
            raise PolicyError('Sensitive values cannot be transmitted to Copilot')
        exposed = None
        observe = getattr(self.browser, 'composer_character_limit', None)
        if callable(observe):
            try:
                exposed = await observe()
            except (BrowserUIError, asyncio.TimeoutError):
                pass
        limit = min(getattr(self.config, 'max_composer_chars', 20000),
                    exposed if type(exposed) is int and exposed > 0 else HISTORICAL_COMPOSER_LIMIT)
        private = self.state.data.get('website_private', False)
        if private:
            message = json.loads(text)
            dense = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
            if composer_characters(dense) > limit - 128:
                # Remove repeated strategy prose before considering transport.
                # Live data, current routing, exact approvals and constraints
                # remain intact. The verified startup contracts still apply.
                strategy = message.get('execution_strategy', {})
                keep = {'planning', 'answering', 'recovery', 'progress', 'target_navigation'}
                message['execution_strategy'] = {key: value for key, value in strategy.items() if key in keep}
                discovery = message.get('discovery_navigation')
                if isinstance(discovery, dict):
                    message['discovery_navigation'] = {key: value for key, value in discovery.items()
                        if key not in {'planning', 'navigation', 'synthesis', 'knowledge'}}
                for key in ('local_crawl4ai_instruction', 'local_tool_request_instruction'):
                    message.pop(key, None)
                message['strategy_reference'] = 'Use the verified startup guidance and tool catalogue for other strategies. All local policy and approval checks still apply.'
                text = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
                recent = message.get('context', {}).get('recent_messages', [])
                omitted = 0
                while recent and composer_characters(text) > limit - 128:
                    recent.pop(0)
                    omitted += 1
                    message['older_messages_omitted_for_transport'] = omitted
                    text = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
                if composer_characters(text) > limit - 128:
                    routing = message.get('research_routing')
                    if isinstance(routing, dict):
                        message['research_routing'] = {key: value for key, value in routing.items()
                            if key in {'selector', 'rea', 'current_request'}}
                    # The exact same storage roots remain in context.constraints.
                    message.pop('navigation_knowledge_root', None)
                    text = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
                if composer_characters(text) > limit - 128:
                    routing = message.get('research_routing', {})
                    health = routing.get('rea')
                    expected = self.prompts.rea_availability
                    # Only reference the exact snapshot already in the verified
                    # startup catalogue. Never rewrite current task/tool data or
                    # independently supplied availability claims.
                    self.prompts.verify_guidance()
                    catalogue = json.loads(self.prompts.catalogue.read_text(encoding='utf-8'))
                    bound = any(item.get('name') == 'rea.inspect_page' and item.get('availability') == expected
                                for item in catalogue.get('tools', []))
                    if bound and health == expected:
                        reference = {key: health[key] for key in
                                     ('available', 'status', 'selected_backend', 'requested_backend') if key in health}
                        reference['details_reference'] = {'startup_component': 'tool-catalogue.json',
                            'tool': 'rea.inspect_page', 'field': 'availability', 'sha256': canonical_hash(expected)}
                        routing['rea'] = reference
                        for route in routing.get('current_request', []):
                            if isinstance(route, dict) and route.get('rea') == expected:
                                route['rea'] = dict(reference)
                        text = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
                if composer_characters(text) > limit - 128:
                    context = message.get('context', {})
                    startup_hashes = self.prompts.bundle.get('sha256_by_path', {})
                    prior = context.get('attachments', [])
                    kept = [item for item in prior if not (isinstance(item, dict)
                        and item.get('path') in startup_hashes
                        and item.get('sha256') == startup_hashes[item['path']])]
                    if len(kept) != len(prior):
                        context['attachments'] = kept
                        message['startup_upload_history_reference'] = {
                            'omitted_records': len(prior) - len(kept),
                            'instruction': 'The hash-verified startup references remain authoritative in this chat; repeated upload history only was omitted. Current user attachments and all policy state remain inline.'}
                        text = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
        packed, paths = pack_outbound(text, attachments, self.state.directory / 'tool-results',
            composer_limit=limit, max_file_bytes=min(self.config.max_attachment_bytes, 8 * 1024 * 1024),
            # Existing current tool-result artifacts retain their explicit
            # transport contract; raw private conversation cannot spill.
            allow_content_attachments=not private or json.loads(text).get('kind') in {'tool_results', 'initialize'})
        if len(paths) > len(attachments):
            self.feedback.emit('System', 'Long response compiled into ' + str(len(paths) - len(attachments)) +
                ' structured result attachment(s); composer text is ' + str(composer_characters(packed)) + ' characters.')
            self.state.event('outbound_results_compiled', attachment_count=len(paths),
                composer_characters=composer_characters(packed), composer_limit=limit)
        return packed, paths

    async def prepare_initialization(self):
        """Upload the immutable startup contract while model choice is pending."""
        if self.initialized:
            raise RuntimeError('The verified contract is already initialized')
        if self._prepared_initialization is not None:
            return {'request_id': self._prepared_initialization['request_id'],
                    'text': self._prepared_initialization['text'],
                    'attachment_count': len(self._prepared_initialization['attachments'])}
        request_id = uuid.uuid4().hex
        content = 'Initialize the continuous conversation under the attached contract.'
        text, attachments = self.prompts.build('initialize', redact(content), request_id)
        attachments = list(dict.fromkeys(map(Path, attachments)))
        text, attachments = await self._pack_outbound_response(text, attachments)
        if len(attachments) > 20:
            raise PolicyError('This message would exceed Copilot\'s 20-attachment limit.')
        if SENSITIVE.search(text):
            raise PolicyError('Sensitive values cannot be transmitted to Copilot')
        self.feedback.emit('Orchestrator', 'Preparing Copilot with the startup contract and files.',
                           request_id=request_id)
        await self.browser.preload_exchange(text, request_id, attachments=attachments)
        self._prepared_initialization = {'request_id': request_id, 'text': text,
                                         'attachments': tuple(attachments)}
        return {'request_id': request_id, 'text': text,
                'attachment_count': len(attachments)}

    async def _validated_exchange(self, kind, content, extra_attachments=(), recovered_response=None):
        for attempt in range(self.config.max_corrections + 1):
            if attempt == 0 and recovered_response is not None:
                raw, request_id = recovered_response
                self._record_raw_response(raw, request_id)
            else:
                raw, request_id = await self._send(kind, content, extra_attachments if attempt == 0 else ())
            try:
                with self.performance.span('validation', request_id=request_id):
                    response = parse_response(raw, self.state.session_id, request_id, self.registry, self.state.data['response_ids'])
                    self._preflight(response)
                if any(call['name'].startswith(('browser.', 'documents.', 'site_knowledge.', 'discovery.', 'navigation.'))
                       or call['name'] == 'files.transfer_to_copilot' for call in response['tool_requests']):
                    self.state.data['website_task_active'] = True
                self.state.data['response_ids'].append(response['response_id'])
                self.state.data['current_plan'] = response['action_plan']
                self.state.message('copilot', response, request_id=request_id)
                if self.state.data.get('website_task_active'):
                    findings_result = {'accepted': 0, 'rejected': len(response['useful_findings']),
                                       'reason': 'Website findings are ephemeral; saving knowledge requires separate consent.'}
                else:
                    findings_result = self.findings.accept(response['useful_findings'], request_id)
                self.state.event('findings_processed', **findings_result)
                self.feedback.record('Orchestrator', 'Validated response.', request_id=request_id,
                                     response_type=response['response_type'],
                                     findings_accepted=findings_result['accepted'])
                self._emit_validated_response(response, response['response_type'].upper())
                return response
            except (ProtocolError, PolicyError, ValueError) as exc:
                from .discovery_contracts import DiscoveryError
                from .web_privacy import PRIVATE_TOOLS
                new_raw_hint = any(name in raw for name in PRIVATE_TOOLS
                                   if name.startswith(('discovery.', 'navigation.')))
                new_rejection = (isinstance(exc, DiscoveryError) or new_raw_hint
                                 or isinstance(exc, ProtocolError) and exc.code.startswith('discovery_'))
                if new_raw_hint and isinstance(exc, ProtocolError) and not exc.code.startswith('discovery_'):
                    exc = ProtocolError('discovery_rejected', ['The current discovery/navigation envelope is malformed or uncorrelated; zero execution and no automatic repair/fallback.'])
                if not isinstance(exc, ProtocolError):
                    code = ('discovery_rejected' if new_rejection else
                            'local_action_rejected' if isinstance(exc, PolicyError) else 'unsafe_tool_arguments')
                    exc = ProtocolError(code, [str(exc)])
                if new_rejection:
                    self.state.data['status'] = 'blocked'
                    self.state.event('discovery_contract_rejected', code=exc.code, zero_execution=True)
                    self.state.save()
                    self.feedback.emit('Error', 'Discovery/navigation contract rejected locally; zero execution. ' + '; '.join(exc.errors))
                    raise exc
                self.state.data['retry_records'].append({'request_id': request_id, 'attempt': attempt, 'reason': exc.code, 'errors': exc.errors})
                self.state.event('response_invalid', request_id=request_id, attempt=attempt, code=exc.code, errors=exc.errors)
                if exc.code == 'local_action_rejected':
                    message = 'Copilot proposed a local action that failed a preflight check. No local action ran. '
                else:
                    message = 'Copilot finished its reply, but the response format was invalid. No local action ran. '
                if attempt == self.config.max_corrections:
                    message += 'The correction limit was reached.'
                else:
                    message += 'Asking Copilot to correct it (' + str(attempt + 1) + '/' + str(self.config.max_corrections) + ').'
                if exc.errors:
                    message += ' Review issue: ' + '; '.join(exc.errors[:3])[:1200]
                self.feedback.emit('Error', message, request_id=request_id)
                self.feedback.record('Error', 'Completed response rejected: ' + str(exc),
                                     request_id=request_id, protocol_code=exc.code, errors=exc.errors)
                # A finished malformed reply is already captured and recorded.
                # Send the correction promptly; collect heavier UI evidence only
                # when the correction budget is exhausted.
                if attempt == self.config.max_corrections and hasattr(self.browser, 'diagnostics'):
                    try:
                        evidence = await self.browser.diagnostics('protocol_' + exc.code)
                        self.state.event('protocol_ui_evidence', request_id=request_id, artifact=str(evidence) if evidence else None)
                    except Exception as diagnostic_error:
                        self.state.event('protocol_ui_evidence_unavailable', request_id=request_id, error=str(diagnostic_error))
                self.state.save()
                if attempt == self.config.max_corrections:
                    self.state.data['status'] = 'blocked'
                    self.state.save()
                    raise exc
                kind, content = 'correction', json.loads(correction_message(exc))
        raise RuntimeError('Unreachable retry state')

    def _preflight(self, response):
        self.state.repair_browser_observations()
        self._recover_uncertain_knowledge()
        recovered = recover_missing_navigation(self.state, self.browser)
        if recovered:
            self.feedback.emit('Orchestrator', 'Lost navigation tab: prior outcome retained as unverified. Fresh approved navigation may proceed; re-observe the page before using its facts.')
        if (self.base_context.get('discovery_synthesis_pending') and response['tool_requests']
                and not self.approvals.supervised_session):
            from .discovery_contracts import DiscoveryError
            raise DiscoveryError('synthesis_only', '$', 'The consolidated discovery/navigation run has ended. Synthesize actual evidence and gaps; new execution requires a new user request.')
        catalog = {d['name']: d for d in self.registry.definitions()}
        for call in response['tool_requests']:
            from .web_privacy import private_id
            if call['call_id'] in self.state.data['calls'] or private_id(call['call_id']) in self.state.data['calls']:
                raise PolicyError('Previously processed call ID must not be replayed')
            action_hash = canonical_hash({k: call[k] for k in ('name', 'version', 'arguments')})
            if not browser_inventory(call) and any(c.get('action_hash') == action_hash and c['status'] in {'uncertain', 'abandoned_unverifiable'} for c in self.state.data['calls'].values()):
                raise PolicyError('An identical action has unresolved or quarantined effects. Inspect the relevant subsystem and reconcile from fresh evidence where supported; do not replay it.')
            prior_failure = next((c for c in self.state.data['calls'].values()
                                  if c.get('action_hash') == action_hash and c['status'] == 'completed'
                                  and not c.get('result', {}).get('ok')), None)
            from .session_mode import fast_mode
            prior_detail = (prior_failure or {}).get('result', {}).get('result', {})
            certain_retry = browser_inventory(call) or fast_mode(self.config) and (prior_detail.get('side_effects_uncertain') is False
                                                                                 or prior_detail.get('status') == 'not_started')
            if prior_failure and not certain_retry:
                if (call['name'] == 'automation.inspect'
                        and self._prior_package_review(call.get('arguments', {}).get('expected_sha256'))):
                    # Exact read-only ZIP reviews are returned from the local
                    # review ledger by the dispatcher; do not repeat work.
                    continue
                evidence = json.dumps(redact(prior_failure.get('result', {})), ensure_ascii=False)[:900]
                raise PolicyError(
                    'The identical ' + str(prior_failure.get('request', {}).get('name', call['name'])) +
                    ' action already failed under call_id ' + str(prior_failure.get('call_id', 'unknown')) +
                    '. Its observed result is: ' + evidence +
                    '. No new action ran. Correct the specific failing argument, selector, path or code using this result; a small justified repair to the same approach is enough, '
                    'or explain the actual blocker; changing only call_id is not a recovery.'
                )
            if (catalog[call['name']]['approval_policy'] != 'read_only' and not browser_inventory(call)
                    and call['name'] not in {'browser.recover_uncertain', 'operation.quarantine'}
                    and any(c['status'] == 'uncertain' and c.get('state_changing', True)
                            and ('global' in operation_domains(call['name'])
                                 or 'global' in operation_domains(c['request']['name'])
                                 or bool(operation_domains(call['name']) & operation_domains(c['request']['name'])))
                            for c in self.state.data['calls'].values())):
                raise PolicyError('A prior action in this operation domain has uncertain effects. Reconcile navigation-only calls from fresh evidence, use approved browser.recover_uncertain for browser effects, or approved operation.quarantine for non-browser effects.')
            # Validate argument shape before execution; page/filesystem state may
            # depend on an earlier successful step in this same ordered batch.
            if hasattr(self.registry, 'validate_input'):
                self.registry.validate_input(call['name'], call['arguments'])
            if (call['name'] == 'code_runner'
                    and self.state.data.get('task_routing', {}).get('route') == 'package'):
                # Package tasks deliver through Copilot's ZIP and automation.run;
                # do not run Code Runner's local-source preflight before the
                # package-only rejection is returned to Copilot.
                continue
            if call['name'] == 'browser.open' and hasattr(self.registry, 'validate_call'):
                self.registry.validate_call(call['name'], call['arguments'], self.base_context)
            if call['name'].startswith(('discovery.', 'navigation.')) and hasattr(self.registry, 'validate_call'):
                if len(response['tool_requests']) != 1:
                    raise PolicyError('A discovery/navigation contract is one independent call; do not mix it with legacy side-effect tools')
                context = dict(self.base_context, source_request_id=response['request_id'])
                self.registry.validate_call(call['name'], call['arguments'], context)
                if call['name'] in {'discovery.manifest', 'navigation.intent'}:
                    self.base_context['discovery_accepted_at'] = time.time()
                    self.base_context['discovery_accepted_monotonic'] = time.monotonic()
            if call['name'] == 'code_runner':
                self._code_runner().validate(call['arguments'])
                if response['code_runner_proposal'] is not None and response['code_runner_proposal'] != call['arguments']:
                    raise PolicyError('Code proposal and execution arguments conflict')

    async def initialize(self):
        self._recover_uncertain_knowledge()
        response = await self._validated_exchange('initialize', 'Initialize the continuous conversation under the attached contract.')
        if response['response_type'] != 'final' or response['tool_requests']:
            raise ProtocolError('contradictory_execution_state', ['Initialization must acknowledge readiness without tools'])
        self.initialized = True
        self.state.data['status'] = 'ready_with_uncertain_operations' if any(c['status'] == 'uncertain' for c in self.state.data['calls'].values()) else 'ready'
        self.state.save()
        return response

    async def recover_capture_failed_turn(self):
        """Capture and process the last committed response without submitting again."""
        recoverable_id = recoverable_capture_request_id(self.state)
        if not recoverable_id:
            raise RuntimeError('The session has no unrecovered, committed capture failure.')
        outbound = [message for message in self.state.data.get('messages', [])
                    if message.get('role') == 'copilot_outbound']
        if not outbound or outbound[-1].get('request_id') != recoverable_id:
            raise RuntimeError('The failed turn has no persisted outbound request identity.')
        request_id = recoverable_id
        capture = getattr(self.browser, 'capture_committed_response', None)
        if not callable(capture):
            raise RuntimeError('The browser adapter cannot recover an existing committed response.')
        self.feedback.emit('Orchestrator', 'Recovering the existing Copilot response. The user message will not be resent.',
                           request_id=request_id)
        raw = await capture(request_id)
        self.state.event('committed_response_recovered', request_id=request_id,
                         response_length=len(raw), capture_method='existing_chat_text')
        goal = 'Resume the already committed request. Do not resend it, rebuild artifacts, or execute delivered code.'
        return await self.turn(goal, recovered_response=(raw, request_id))

    def _recover_uncertain_knowledge(self):
        """Resolve optional persistence effects once; never replay a write."""
        from .site_knowledge import reconcile_knowledge_call, quarantine_knowledge_record
        recovered = {}
        for call_id, call in list(self.state.data['calls'].items()):
            if call.get('status') != 'uncertain' or operation_domains(call['request']['name']) != {'knowledge'}:
                continue
            try:
                outcome = reconcile_knowledge_call(self.state, self.base_context, call_id)
            except Exception as error:
                namespace = (call.get('reconciliation_baseline') or {}).get('namespace_id')
                archive_status = 'not_applicable'
                if namespace and getattr(error, 'code', '') in {'integrity_failure', 'knowledge_integrity'}:
                    try:
                        quarantine_knowledge_record(self.base_context, namespace)
                        archive_status = 'retained'
                    except Exception:
                        archive_status = 'storage_unavailable'
                self.state.quarantine_call(call_id)
                outcome = {'status': 'abandoned_unverifiable', 'completion_credited': False,
                           'diagnostic': type(error).__name__, 'evidence_archive': archive_status}
            recovered[call_id] = outcome
            self.state.event('knowledge_recovery', operation_id=call_id, **outcome)
        return recovered

    async def turn(self, user_input: str, attachments=(), active_run_id=None, recovered_response=None):
        self._active_turn_run_id = active_run_id
        try:
            with self.performance.span('task_total'):
                return await self._turn(user_input, attachments, recovered_response)
        finally:
            self.performance.flush()
            pending, self._pending_steering_items = self._pending_steering_items, []
            if pending:
                status = 'cancelled' if self.cancel_event.is_set() else 'failed'
                summary = ('The active run ended before this message was incorporated.'
                           if status == 'failed' else 'Run cancelled before this message was incorporated.')
                if self.event_sink:
                    for item in pending:
                        self.event_sink('steering', {'message_id': item.get('message_id'),
                            'active_run_id': item.get('active_run_id'), 'sequence': item.get('sequence'),
                            'status': status, 'summary': summary})
                if self.steering_complete:
                    self.steering_complete([item.get('message_id') for item in pending
                                            if isinstance(item, dict) and item.get('message_id')])
            self._active_turn_run_id = None

    async def _turn(self, user_input: str, attachments=(), recovered_response=None):
        self.cancel_event.clear()
        goal_outcomes = {}
        goal_completion_corrections = 0
        if recovered_response is None:
            self.browser._goal_navigation = {}
        self.base_context.pop('discovery_synthesis_pending', None)
        self.base_context.pop('discovery_accepted_at', None)
        self.base_context.pop('discovery_accepted_monotonic', None)
        if not self.initialized:
            raise RuntimeError('Initialize the verified contract first')
        if self.state.data['pending_submission']:
            raise RuntimeError('Reconcile uncertain submission before another turn')
        if SENSITIVE.search(user_input):
            raise PolicyError('Input contains credential-like material; remove it before sending')
        attachments = await self._prepare_user_attachments(attachments) if attachments else []
        if attachments is None:
            self.feedback.emit('Orchestrator', 'Attachment denied; no files uploaded. The request text was not sent.')
            return {'response_type': 'clarification', 'user_response': 'Attachment denied.'}
        self.state.data['status'] = 'running'
        self.state.save()
        if recovered_response is None:
            self.state.message('user', user_input)
            self.state.data['requirements'].append(user_input)
        else:
            self.state.event('turn_continued_from_recovered_response', request_id=recovered_response[1])
        from .delivery import delivery_requirements, retry_message
        delivery = delivery_requirements(user_input)
        delivery_attempts = 0
        delivery_reports = []
        turn_call_ids = set()
        delivery_denied = False
        delivery_link_rejected = False
        package_review_failure = None
        package_run_failure = None
        if recovered_response is not None:
            calls = self.state.data.get('calls', {})
            has_run_history = any(isinstance(record, dict)
                                  and record.get('request', {}).get('name') == 'automation.run'
                                  for record in calls.values())
            if has_run_history:
                package_run_failure = self._latest_failed_package_run(calls)
                if package_run_failure is None:
                    package_run_failure = self._recovered_package_run_failure()
            else:
                failed_call_id = self.state.data.get('package_run_failure_call_id')
                failed_record = calls.get(failed_call_id) if failed_call_id else None
                if isinstance(failed_record, dict):
                    package_run_failure = {'call_id': failed_call_id, **failed_record.get('result', {})}
                if package_run_failure is None:
                    package_run_failure = self._recovered_package_run_failure()
        self.base_context['created_baseline'] = (CreatedSync(self.config.created_dir).baseline()
                                               if self.config.created_sync_enabled and self.config.created_dir else None)
        kind, content = 'user_turn', user_input
        self.base_context['research_user_request'] = user_input
        self._authorize_user_targets(user_input)
        from .automation_packages import estimate_task
        candidate_route = estimate_task(self._routing_description(user_input), {
            'package_score': self.config.automation_package_score,
            'minimum_steps': self.config.automation_minimum_steps,
            'minimum_files': self.config.automation_minimum_files,
            'minimum_runtime_seconds': self.config.automation_minimum_runtime_seconds,
        })
        route = self._route_for_turn(candidate_route, recovered_response)
        self.state.data['task_routing'] = route
        self.state.save()
        catalog = {d['name']: d for d in self.registry.definitions()}
        round_number = 0
        round_attachments = list(attachments)
        round_steering_ids = []
        while True:
            incoming = await self._take_steering(user_input)
            if incoming:
                self.browser._goal_navigation = {}
                goal_outcomes.clear()
                if kind == 'tool_results' and isinstance(content, dict):
                    incoming['content']['completed_tool_results'] = content.get('results', [])
                    incoming['content']['not_executed_prior_plan'] = content.get('not_executed', [])
                kind, content = 'steering', incoming['content']
                round_attachments.extend(incoming['attachments'])
                round_steering_ids.extend(incoming['message_ids'])
            try:
                response = await self._validated_exchange(kind, content, round_attachments,
                                                          recovered_response=recovered_response)
                recovered_response = None
            finally:
                if round_steering_ids and self.steering_complete:
                    self.steering_complete(list(round_steering_ids))
                round_steering_ids = []
            round_attachments = []
            round_number += 1
            if self.cancel_event.is_set():
                self.state.data['status'] = 'cancelled'
                self.state.save()
                return dict(response, completion_status='blocked',
                            user_response='Cancellation received; no further tools will execute. Inspect any already submitted effects.')
            incoming = await self._take_steering(user_input)
            if incoming:
                # A newly arrived correction supersedes an unexecuted response plan.
                # Re-prompt Copilot before any local tool from that plan can run.
                self.browser._goal_navigation = {}
                goal_outcomes.clear()
                kind, content = 'steering', incoming['content']
                round_attachments = incoming['attachments']
                round_steering_ids.extend(incoming['message_ids'])
                continue
            if package_run_failure and response['response_type'] in {'final', 'clarification'}:
                repair = self._package_run_repair_instruction([package_run_failure])
                if repair:
                    self.feedback.emit('Orchestrator', 'The local package run failed. Returning the captured stage and output failures to Copilot automatically for repair.')
                    kind, content = 'recovery', {
                        'goal': user_input,
                        'instruction': ('Continue automatically from the local run result. Correct the reported package failure, run relevant tests in Copilot\'s cloud sandbox when available, and deliver a fresh clickable ZIP for automatic local inspection. Do not ask the user to inspect files or write a repair request. Cloud tests do not replace any user-requested live test in the local agent environment; do not claim live success until it passes.\n\n' + repair),
                        'failed_package_run': redact(package_run_failure)}
                    continue
            if package_review_failure and response['response_type'] in {'final', 'clarification'}:
                repair = self._package_review_repair_instruction([package_review_failure])
                if not repair:
                    repair = ('The last delivered ZIP did not pass local review. Provide a corrected new ZIP '
                              'revision and allow the local orchestrator to inspect it before claiming completion.')
                self.feedback.emit('Orchestrator', 'Package review is still failing; the package result cannot be marked complete. Returning the full review findings to Copilot for repair.')
                kind, content = 'recovery', {
                    'goal': user_input,
                    'instruction': ('Continue automatically from the local review. Do not ask the user to inspect the ZIP or write a repair request. '
                                    'Fix every listed issue together, run relevant tests in your cloud sandbox when available, and deliver a fresh clickable ZIP. '
                                    'Cloud tests do not replace any user-requested live test in the local agent environment; do not claim live success until it passes.\n\n' + repair),
                    'failed_package_review': redact(package_review_failure)}
                continue
            if response['response_type'] == 'final':
                unfinished = [r for r in goal_outcomes.values() if r.get('status') != 'target_verified'
                              or not r.get('visual_context', {}).get('queued_for_copilot')]
                if unfinished and response.get('completion_status') == 'complete':
                    if goal_completion_corrections < 2 and all(r.get('status') == 'needs_visual_decision' for r in unfinished):
                        goal_completion_corrections += 1
                        kind, content = 'tool_results', {'navigation_results': unfinished,
                            'instruction': 'The target has not been verified. Read the current screenshot and continue '
                            'with browser.navigate_goal and its observation_id. Do not claim completion from an intermediate page.'}
                        continue
                    response = dict(response, completion_status='blocked',
                                    user_response='Navigation target is unverified; inspect the current visual evidence and returned boundary.')
                if delivery.get('mode', 'none') != 'none' and delivery_denied:
                    response = dict(response, completion_status='blocked', user_response='File delivery was denied; no complete delivery is claimed. ' + response['user_response'])
                if delivery.get('mode', 'none') != 'none' and not delivery_denied and not self._delivery_verified(delivery, delivery_reports):
                    if delivery_attempts < self.config.max_delivery_retries:
                        delivery_attempts += 1
                        reason = 'No verified local artifact satisfies this requested delivery. A UI link or a Copilot claim alone is insufficient.'
                        content = retry_message(reason, delivery_attempts, self.config.max_delivery_retries, office=delivery['mode'] == 'zip')
                        kind = 'delivery_retry'
                        self.feedback.emit('Orchestrator', 'Delivery is not verified; requesting downloadable-link correction ' + str(delivery_attempts) + '/' + str(self.config.max_delivery_retries) + '.')
                        continue
                    response = dict(response, completion_status='blocked', user_response='File delivery is unverified after bounded retries. ' + response['user_response'])
                    self.state.event('delivery_unverified', requested=delivery, attempts=delivery_attempts)
                self.state.data['status'] = 'ready_with_uncertain_operations' if any(c['status'] == 'uncertain' for c in self.state.data['calls'].values()) else 'ready'
                if response.get('completion_status') == 'blocked': self.state.data['status'] = 'delivery_blocked'
                self.state.data['summary'] = response['task_interpretation'] + '\n' + response['user_response']
                self.state.data['decisions'].append({'request': user_input, 'outcome': response['user_response']})
                self.state.save()
                self.feedback.emit('Copilot', 'FINAL RESULT / ' + str(response.get('completion_status')) + '\n' + response['user_response'],
                                   request_id=response.get('request_id'), validated=True)
                if self.event_sink:
                    self.event_sink('copilot', {'text': response['user_response'],
                                                'completion_status': response.get('completion_status')})
                if delivery.get('mode') != 'none' and response.get('completion_status') == 'complete':
                    for report in delivery_reports:
                        if report.get('tool') == 'copilot.download':
                            self.feedback.emit('Orchestrator', 'Retained artifact: ' + report['path'])
                        elif report.get('tool') == 'archives.extract':
                            self.feedback.emit('Orchestrator', 'Verified extraction: ' + report['destination'] + ' (' + str(len(report.get('verified_files', []))) + ' files). Evidence: ' + report.get('report_path', ''))
                self._schedule_next_turn_preparation()
                return response
            if response['response_type'] in {'clarification', 'error'}:
                failed_calls = [item for key, item in self.state.data['calls'].items()
                                if key in turn_call_ids and not item.get('result', {}).get('ok')]
                if (response['response_type'] == 'error' and failed_calls
                        and not delivery_denied
                        and not self.base_context.get('discovery_synthesis_pending')
                        and not any(item.get('result', {}).get('error', {}).get('code') == 'approval_denied'
                                    for item in failed_calls)):
                    kind, content = 'recovery', {
                        'goal': user_input,
                        'instruction': ('Continue from actual retained outcomes. Do not replay uncertain effects. '
                                        'After uncertain state changes, use read-only inspection until reconciliation. '
                                        'Respect denial, authentication, safety and resource budgets.'),
                        'failed_calls': redact(failed_calls[-3:])}
                    continue
                if (response['response_type'] == 'error' and delivery.get('mode') != 'none' and delivery_link_rejected and
                        not delivery_denied and delivery_attempts < self.config.max_delivery_retries):
                    delivery_attempts += 1
                    kind, content = 'delivery_retry', retry_message('The observed link was rejected before any download started. Try an actual downloadable UI artifact; for a single non-Office file, try ZIP fallback.', delivery_attempts, self.config.max_delivery_retries, office=delivery['mode'] == 'zip')
                    delivery_link_rejected = False
                    self.feedback.emit('Orchestrator', 'Requesting a usable delivery link or ZIP fallback after a proven pre-click rejection.')
                    continue
                self.state.data['status'] = 'awaiting_clarification' if response['response_type'] == 'clarification' else 'blocked'
                if response['clarification']:
                    self.state.data['unresolved_questions'].append(response['clarification'])
                self.state.save()
                self.feedback.section('Copilot', response['response_type'].upper(), [
                    ('Message', response['clarification'] or response['user_response']),
                    ('Status', response.get('completion_status'))])
                self._schedule_next_turn_preparation()
                return response
            execution_calls = list(response['tool_requests'])
            plan = {'action_plan': response['action_plan'], 'tool_requests': execution_calls, 'risk_summary': response['risk_summary']}
            prepared_plan = None
            package_local_build_requested = (not self.approvals.supervised_session and route.get('route') == 'package' and any(
                self._package_local_build_rejection(call['name']) is not None
                for call in response['tool_requests']))
            if (not package_local_build_requested and len(response['tool_requests']) > 1
                    and all(call['name'] == 'code_runner' for call in response['tool_requests'])):
                prepared_plan = {call['call_id']: self._code_runner().prepare(call['arguments'])
                                 for call in response['tool_requests']}
            if len(response['tool_requests']) > 1 and all(call['name'].startswith('browser.') for call in response['tool_requests']):
                prepared_plan = {call['call_id']: self._browser_preparation(call)
                                 for call in response['tool_requests']}
            results = []
            interrupted_by_steering = None
            parallel_readonly_results = await self._parallel_readonly_group(
                response['tool_requests'], response['request_id'])
            for call in execution_calls:
                if self.cancel_event.is_set():
                    break
                incoming = await self._take_steering(user_input)
                if incoming:
                    interrupted_by_steering = incoming
                    break
                if parallel_readonly_results is not None:
                    result = parallel_readonly_results[call['call_id']]
                    self._emit_tool_result(call['name'], result)
                    results.append({'call_id': call['call_id'], **result})
                    continue
                self.feedback.section('Orchestrator', 'TOOL REQUEST', [
                    ('Tool', call['name']),
                    ('Purpose', call.get('arguments', {}).get('purpose'))])
                definition = catalog[call['name']]
                context = dict(self.base_context)
                self._knowledge_authority(context)
                context['remaining_attachment_capacity'] = max(0, 10 - len(context['pending_image_attachments']))
                context['source_request_id'] = response['request_id']
                context['source_call_id'] = call['call_id']
                if call['name'] == 'automation.inspect':
                    try:
                        archive, actual_digest = self._local_archive_sha256(call['arguments']['path'])
                        expected_digest = call['arguments'].get('expected_sha256')
                        cached_review = (self._prior_package_review(actual_digest)
                                         if expected_digest in (None, actual_digest) else None)
                    except (OSError, PolicyError, ValueError, KeyError):
                        cached_review = None
                    if cached_review is not None:
                        cached_review['result']['archive'] = str(archive)
                        cached_review['review_reused'] = True
                        self.state.begin_call(call, state_changing=False)
                        self.state.finish_call(call['call_id'], cached_review)
                        self.feedback.emit('Orchestrator', 'This exact ZIP fingerprint already has a local review; returning the recorded checks without repeating them.')
                        self._emit_tool_result(call['name'], cached_review)
                        results.append({'call_id': call['call_id'], **cached_review})
                        self._record_package_delivery(delivery_reports, call['call_id'], cached_review)
                        if not cached_review.get('ok'):
                            package_review_failure = {'call_id': call['call_id'], **cached_review}
                            break
                        if route.get('route') == 'package':
                            self._queue_reviewed_package_run(execution_calls, cached_review)
                        continue
                if route.get('route') == 'package' and not self.approvals.supervised_session:
                    rejected = self._package_local_build_rejection(call['name'])
                    if rejected is not None:
                        self.state.begin_call(call, state_changing=False)
                        self.state.finish_call(call['call_id'], rejected)
                        self._emit_tool_result(call['name'], rejected)
                        results.append({'call_id': call['call_id'], **rejected})
                        break
                if call['name'] == 'automation.run':
                    prior_review = await self._ensure_package_review(call['arguments'], context)
                    if not self._review_passed(prior_review):
                        if prior_review is None:
                            review = {'status': 'failed',
                                      'summary': 'This exact ZIP has no passing local package review yet.',
                                      'archive_sha256': call['arguments'].get('expected_sha256'),
                                      'checks': [{'item': 'Local package review', 'status': 'failed'}],
                                      'failures': [{'item': 'Local package review',
                                                    'detail': 'The exact ZIP could not be rechecked locally.',
                                                    'next_step': 'Review the local inspection result and correct the delivery boundary.'}],
                                      'not_checked_count': 0,
                                      'future_review_options': ['This review is required before a run; optional format preferences can be adjusted in a later policy update.']}
                            blocked_run = {'ok': False, 'tool': 'automation.run',
                                           'result': {'status': 'not_started', 'review': review},
                                           'error': {'code': 'package_review_required',
                                                     'message': 'The package was not run because it has no passing local review.'}}
                        else:
                            blocked_run = deepcopy(prior_review)
                            blocked_run['tool'] = 'automation.run'
                            blocked_run['error'] = {'code': 'package_review_failed',
                                                    'message': 'The exact ZIP failed its local review; no package stage ran.'}
                            blocked_run.setdefault('result', {})['status'] = 'not_started'
                        self.state.begin_call(call, state_changing=False)
                        self.state.finish_call(call['call_id'], blocked_run)
                        self._emit_tool_result(call['name'], blocked_run)
                        results.append({'call_id': call['call_id'], **blocked_run})
                        package_review_failure = {'call_id': call['call_id'], **blocked_run}
                        break
                needs_approval = not browser_inventory(call) and definition['approval_policy'] not in {'none', 'read_only', 'automatic', 'auto_readonly'}
                effectful = needs_approval or call['name']=='research.perform' and call['arguments'].get('operation') in {'search','navigate','open_profile','open_document_library','open_document'}
                navigation_authorized = needs_approval and navigation_scope_allows(call, self.browser, self.navigation_domains, self.navigation_binding)
                if navigation_authorized:
                    needs_approval = False
                    context['approved'] = True
                    context['navigation_scope_granted'] = True
                prepared = None
                artifact = None
                if call['name'] == 'files.grant_path':
                    prepared = self.registry.validate_call(call['name'], call['arguments'], context)
                    context.pop('reviewed_path_extension', None)
                if call['name'] == 'operation.quarantine':
                    from .web_privacy import private_id
                    target_id = call['arguments']['call_id']
                    target = (self.state.data['calls'].get(target_id)
                              or self.state.data['calls'].get(private_id(target_id)))
                    if target is None or target.get('status') != 'uncertain':
                        raise PolicyError('Choose an uncertain operation for quarantine')
                    if not operation_domains(target['request']['name']) <= {'knowledge', 'filesystem'}:
                        raise PolicyError('This effect needs subsystem-specific verified recovery')
                    prepared = {'uncertain_operation': {'tool': target['request']['name'],
                                'status': target['status'],
                                'effect_domains': sorted(operation_domains(target['request']['name'])),
                                'outcome_credited': False}}
                if call['name'] in {'files.create', 'files.mkdir', 'files.append', 'files.copy', 'files.replace'}:
                    file_preflight = self.registry.validate_call(call['name'], call['arguments'], context)
                    if isinstance(file_preflight, dict) and file_preflight.get('s_drive_destination'):
                        prepared = {'mapped_s_drive_destination': file_preflight['s_drive_destination'],
                                    'identity_checked': True, 'write_scope': 'one exact approved output'}
                        if call['name'] in {'files.create', 'files.mkdir'}:
                            prepared['storage_folder'] = self.prompts.storage_paths['unc_path']
                            prepared['storage_folder_s_path'] = self.prompts.storage_paths['s_path']
                if call['name'] == 'code_runner':
                    needs_approval = True
                    prepared = self._code_runner().prepare(call['arguments'])
                if call['name'] == 'automation.run':
                    needs_approval = True
                    prepared = self.registry.validate_call(call['name'], call['arguments'], context)
                if call['name'].startswith('browser.'):
                    if call['name'] == 'browser.open':
                        self.registry.validate_call(call['name'], call['arguments'], context)
                    prepared = self._browser_preparation(call)
                    from .session_mode import discovery_mode, website_policy
                    if discovery_mode(self.config) and call['name'] in {
                            'browser.scroll', 'browser.screenshot', 'browser.inspect', 'browser.login_once'}:
                        from .web_navigation import get_navigation_page
                        owned = get_navigation_page(context, call['arguments'].get('tab_id'))
                        website_policy(self.config, self.state.data['approved_domains']).resolve(owned.url)
                        needs_approval = False
                        context['approved'] = True
                        context['session_login_authorized'] = call['name'] == 'browser.login_once'
                if call['name'] in {'permissions.grant','permissions.edit','permissions.renew'}:
                    prepared = prepare_permissions(call['name'],call['arguments'],context)
                if call['name'].startswith('site_knowledge.'):
                    from .site_knowledge import prepare_knowledge
                    try:
                        prepared = prepare_knowledge(call['arguments'], context, name=call['name'])
                    except (ValueError, PolicyError) as exc:
                        failure = {'ok': False, 'tool': call['name'],
                                   'error': {'code': 'invalid_knowledge_proposal', 'message': str(exc)},
                                   'result': {'status': 'not_started', 'side_effects_uncertain': False}}
                        self.state.begin_call(call, state_changing=False)
                        self.state.finish_call(call['call_id'], failure)
                        results.append({'call_id': call['call_id'], **failure})
                        self.feedback.emit('Tool/' + call['name'], 'Proposal rejected before approval or storage: ' + str(exc))
                        break
                if call['name'] == 'discovery.manifest':
                    from .discovery_engine import prepare_discovery
                    prepared = prepare_discovery(call['arguments'], context)
                if call['name'] in {'discovery.knowledge_save', 'discovery.knowledge_invalidate', 'navigation.intent'}:
                    from .discovery_knowledge import prepare_knowledge_tool
                    prepared = prepare_knowledge_tool(call['name'], call['arguments'], context)
                if (self.base_context['local_navigation_grant'].approved and
                        call['name'] in {'site_knowledge.bind', 'site_knowledge.save', 'site_knowledge.invalidate',
                                         'discovery.knowledge_save', 'discovery.knowledge_invalidate', 'knowledge.note'}):
                    needs_approval = False
                    context['approved'] = True
                    context['approval_hash'] = canonical_hash({'session': self.state.session_id,
                        'authority': 'confirmed_local_navigation_and_knowledge', 'call': call})
                    if getattr(self.config, '_knowledge_session_confirmed', False):
                        from .site_knowledge import knowledge_session_grant
                        context['knowledge_session_authorized'] = True
                        context['knowledge_session_grant'] = knowledge_session_grant(context)
                    if call['name'].startswith('site_knowledge.'):
                        context['site_knowledge_reviewed'] = prepared
                        context['site_knowledge_consent'] = prepared
                    else:
                        context['discovery_reviewed'] = prepared
                        context['discovery_save_consent'] = prepared
                if call['name'] == 'ocr.image':
                    artifact = self._attachment_record(self.policy.resolve(call['arguments']['path'], True))
                    prepared = {'approved_image_attachment': artifact, 'destination': self.config.copilot_url}
                if call['name'] == 'copilot.download':
                    from .downloads import DownloadService, DownloadError
                    if self.download_service is None:
                        self.download_service = DownloadService(self.browser, self.config, self.policy, self.state.directory)
                    try:
                        prepared = await self.download_service.prepare(call['arguments'], response['request_id'])
                    except DownloadError as exc:
                        delivery_link_rejected = exc.code in {'link_unavailable', 'generation_timeout', 'unsupported_link', 'settings_unavailable'}
                        failure = {'ok': False, 'tool': call['name'], 'error': {'code': exc.code, 'message': str(exc)}, 'result': {'status': 'not_started', 'side_effects_uncertain': False}}
                        self.state.begin_call(call, state_changing=False)
                        self.state.finish_call(call['call_id'], failure)
                        results.append({'call_id': call['call_id'], **failure})
                        self.feedback.emit('Tool/copilot.download', 'No file clicked: ' + str(exc))
                        break
                    context['download_service'] = self.download_service
                    context['download_binding'] = prepared
                if call['name'] == 'archives.extract':
                    from .archives import ArchiveService
                    manifest = ArchiveService(self.policy, self.state.directory).inspect({'path': call['arguments']['path']})
                    if manifest.get('office'):
                        raise PolicyError('A native Office container was delivered as ZIP; request a real outer ZIP containing the Office file.')
                    prepared = {'archive_manifest': manifest, 'destination': str(self.policy.resolve(call['arguments']['destination'])), 'expected_files': call['arguments'].get('expected_files', [])}
                if call['name'] in {'files.create', 'files.mkdir', 'files.append', 'files.copy', 'files.replace',
                                    'site_knowledge.invalidate', 'discovery.knowledge_invalidate'}:
                    target = (prepared or {}).get('mapped_s_drive_destination') or (prepared or {}).get('directory') or self.prompts.storage_paths['unc_path']
                    self.feedback.emit('System', 'Save target: intended S: path ' + self._display_s_path(target) +
                                       '; resolved filesystem destination ' + str(target))
                if needs_approval:
                    self.state.data['status'] = 'awaiting_approval'
                    self.state.save()
                    allowed, approval_hash = await self.approvals.request(plan, call, prepared, prepared_plan=prepared_plan)
                    if not allowed:
                        if call['name'] in {'copilot.download', 'archives.extract'}: delivery_denied = True
                        denied = {'ok': False, 'error': {'code': 'approval_denied', 'message': 'User denied the immutable plan; do not retry this action through another mechanism.'}}
                        self.state.begin_call(call)
                        self.state.finish_call(call['call_id'], denied)
                        results.append({'call_id': call['call_id'], **denied})
                        self.feedback.emit('Orchestrator', 'Denied: no execution; remaining dependent steps were stopped.')
                        # Denial prevents remaining possibly dependent steps of this plan.
                        break
                    context['approved'] = True
                    context['approval_hash'] = approval_hash
                    if call['name'] == 'files.grant_path':
                        context['reviewed_path_extension'] = prepared
                    if call['name'] == 'automation.run':
                        context['package_plan_hash'] = prepared['package_plan_hash']
                        context['approved_hash'] = prepared['package_plan_hash']
                    if call['name'].startswith('permissions.'):
                        context['permission_reviewed'] = prepared
                    if call['name'] in {'discovery.manifest', 'discovery.knowledge_save', 'discovery.knowledge_invalidate', 'navigation.intent'}:
                        context['discovery_reviewed'] = prepared
                        if call['name'] == 'discovery.knowledge_save':
                            context['discovery_save_consent'] = prepared
                    if call['name'].startswith('site_knowledge.'):
                        context['site_knowledge_reviewed'] = prepared
                        if call['name'] == 'site_knowledge.save':
                            context['site_knowledge_consent'] = prepared
                    if call['name'] == 'browser.plan':
                        def consequential(steps):
                            return any(step.get('effect') == 'consequential' or
                                       any(consequential(step.get(key, [])) for key in ('steps', 'then', 'else'))
                                       for step in steps)
                        if consequential(call['arguments']['steps']):
                            from .web_navigation import plan_hash
                            digest = plan_hash(call['arguments'])
                            confirmation = dict(call, call_id=call['call_id'] + '-consequential')
                            boundary = {'tool_requests': [confirmation],
                                        'risk_summary': 'Specifically confirm the consequential effects in this exact browser plan.'}
                            confirmed, _ = await self.approvals.request(
                                boundary, confirmation, {'consequential_plan_hash': digest,
                                                         'purpose': 'Confirm irreversible or customer-impacting effects'})
                            if not confirmed:
                                denied = {'ok': False, 'error': {'code': 'approval_denied',
                                                               'message': 'Consequential confirmation was declined.'}}
                                self.state.begin_call(call)
                                self.state.finish_call(call['call_id'], denied)
                                results.append({'call_id': call['call_id'], **denied})
                                break
                            context['consequential_approved_plan_hash'] = digest
                    if call['name'] in {'browser.open', 'browser.recover_uncertain'}:
                        from .session_mode import OpenWebsitePolicy, website_origin
                        approved_url = call['arguments'].get('url') or call['arguments']['checkpoint_url']
                        domains = [OpenWebsitePolicy.website_domain(approved_url),
                                   *call['arguments'].get('allowed_domains', [])]
                        self.config._session_approved_origins = set(getattr(self.config, '_session_approved_origins', ()))
                        self.config._session_approved_origins.add(website_origin(approved_url))
                        authorize = getattr(self.browser, 'authorize_tool_domain', None)
                        for domain in domains:
                            self.state.approve_domain(domain)
                            if callable(authorize):
                                authorize(domain)
                        context['approved_domains'] = self.state.data['approved_domains']
                    if prepared:
                        if 'proposal_hash' in prepared and call['name'] != 'automation.run':
                            context['approved_hash'] = prepared['proposal_hash']
                        if 'mapped_s_drive_destination' in prepared:
                            context['s_drive_destination'] = prepared['mapped_s_drive_destination']
                    if artifact:
                        self.approved_attachment_hashes[artifact['path']] = artifact['sha256']
                    if call['name'].startswith('browser.'):
                        self.navigation_domains.update(self.state.data['approved_domains'])
                        self.navigation_binding = _binding(self.browser)
                if call['name'] == 'browser.open' and hasattr(self.browser, 'tool_page'):
                    page = self.browser.tool_page
                    if page is None or page.is_closed():
                        self.browser.tool_page = await self.browser.new_tool_page()
                baseline = (await capture_baseline(self.browser, call)
                            if call['name'] in {'browser.open', 'browser.back', 'browser.forward', 'browser.plan'}
                            and not context.get('consequential_approved_plan_hash')
                            and hasattr(self.browser, 'tool_page') else None)
                if call['name'] == 'site_knowledge.save':
                    from .site_knowledge import reconciliation_baseline
                    baseline = reconciliation_baseline(call['arguments'], context, prepared)
                self.state.begin_call(call, state_changing=effectful, reconciliation_baseline=baseline,
                                      uncertainty_recovery=call['name'] in {'browser.recover_uncertain', 'operation.quarantine'})
                if effectful or call['name']=='research.perform':
                    self.feedback.emit('Action', 'APPROVED ACTION\n'+call_summary(call))
                    if self.event_sink:
                        self.event_sink('action', {'text':'Approved action\n'+call_summary(call)})
                self.feedback.section('Tool/' + call['name'], 'STARTING', [
                    ('Authority', 'approved session navigation scope' if navigation_authorized else 'exact explicit approval' if needs_approval else 'read-only policy'),
                    ('Language', call.get('arguments', {}).get('language')),
                    ('Expected effects', call.get('arguments', {}).get('expected_effects'))])
                if self.event_sink:
                    self.event_sink('tool', {'name': call['name'], 'status': 'running',
                                             'summary': 'Executing under the recorded approval and policy.'})
                try:
                    from .automatic_visuals import relevant as visual_companion
                    visual_allowance = 28 if visual_companion(call['name'], call['arguments']) else 0
                    with self.performance.span('tool', request_id=response.get('request_id'), call_id=call['call_id']):
                        result = await asyncio.wait_for(self.registry.execute(call['name'], call['arguments'], context), timeout=float(definition.get('timeout', definition.get('limits', {}).get('timeout_seconds', 30))) + visual_allowance + 1)
                except asyncio.TimeoutError:
                    result = {'ok': False, 'error': {'code': 'timeout', 'message': 'Tool timed out; inspect partial effects before any retry.'}}
                except Exception as exc:
                    result = {'ok': False, 'error': {'code': 'tool_error', 'message': str(exc)}}
                finally:
                    if call['name'].startswith(('browser.', 'documents.')):
                        focus = getattr(self.browser, 'focus_chat', None)
                        if callable(focus):
                            try:
                                await asyncio.wait_for(focus(), timeout=3)
                            except Exception:
                                pass  # The tool outcome remains authoritative.
                self.state.finish_call(call['call_id'], result)
                self.performance.flush()
                if call['name'] == 'browser.navigate_goal':
                    goal_outcomes[call['arguments']['task_id']] = result.get('result', {})
                recovery = self._recover_uncertain_knowledge().get(call['call_id'])
                if recovery:
                    result.setdefault('result', {})['recovery'] = recovery
                if call['name'] in {'discovery.manifest', 'navigation.intent'}:
                    self.base_context['discovery_synthesis_pending'] = True
                if result.get('ok') and call['name'] == 'browser.open':
                    self.base_context['research_context']['active'] = False
                    for field in ('task_id', 'customer_key'):
                        self.base_context.pop(field, None)
                    from urllib.parse import urlsplit
                    origin = 'https://' + urlsplit(result.get('result', {}).get('url', '')).hostname.lower() if urlsplit(result.get('result', {}).get('url', '')).hostname else None
                    if origin not in self.base_context.get('site_knowledge_bindings', {}):
                        for field in ('tenant_id', 'site_namespace_id'):
                            self.base_context.pop(field, None)
                if result.get('ok') and call['name'] == 'browser.recover_uncertain':
                    self.base_context['research_context']['active'] = False
                    for field in ('task_id', 'customer_key'):
                        self.base_context.pop(field, None)
                    self.base_context['web_document_tickets'].clear()
                    self.base_context['document_catalogues'].clear()
                if result.get('ok') and call['name'] == 'site_knowledge.bind':
                    scope = result.get('result', {}).get('scope', {})
                    self.base_context['tenant_id'] = scope.get('tenant')
                    self.base_context['site_namespace_id'] = result.get('result', {}).get('namespace_id')
                    self.base_context['web_document_tickets'].clear()
                    self.base_context['document_catalogues'].clear()
                if (result.get('ok') or call['name'] == 'browser.customer_summary' and result.get('result', {}).get('identity_verified')) and call['name'] in {'browser.plan', 'browser.navigate_goal', 'browser.customer_summary', 'browser.tabs'}:
                    if call['name'] == 'browser.tabs' and call['arguments'].get('operation') == 'reset':
                        self.base_context.pop('customer_key', None)
                        self.base_context['web_document_tickets'].clear()
                        self.base_context['document_catalogues'].clear()
                    for field in ('task_id', 'customer_key'):
                        if field in call['arguments']:
                            self.base_context[field] = call['arguments'][field]
                self._emit_tool_result(call['name'], result)
                results.append({'call_id': call['call_id'], **result})
                if call['name'] == 'automation.run':
                    run_result = result.get('result', {})
                    validation = run_result.get('validation', {}) if isinstance(run_result, dict) else {}
                    run_cancelled = isinstance(run_result, dict) and run_result.get('status') == 'cancelled'
                    run_failed = (not run_cancelled and (not result.get('ok') or not isinstance(run_result, dict)
                                  or run_result.get('status') not in {'completed', 'not_started'}
                                  or run_result.get('status') == 'completed'
                                  and (run_result.get('failed_stages')
                                        or not isinstance(validation, dict) or validation.get('ok') is not True)))
                    if run_failed:
                        package_run_failure = {'call_id': call['call_id'], **result}
                        self.state.data['package_run_failure_call_id'] = call['call_id']
                        if isinstance(run_result, dict) and isinstance(run_result.get('state_path'), str):
                            self.state.data['package_run_failure_state_path'] = run_result['state_path']
                            self.state.data['package_run_failure_archive_sha256'] = run_result.get('archive_sha256')
                    elif run_result.get('status') in {'completed', 'cancelled'}:
                        package_run_failure = None
                        self.state.data.pop('package_run_failure_call_id', None)
                        self.state.data.pop('package_run_failure_state_path', None)
                        self.state.data.pop('package_run_failure_archive_sha256', None)
                    self.state.save()
                if result.get('ok') and call['name'] in {'copilot.download', 'archives.extract'}:
                    delivery_reports.append({'tool': call['name'], **self._delivery_result(call['name'], result)})
                if call['name'] == 'automation.inspect' and self._review_passed(result):
                    # Explicit inspection is the same local evidence as the
                    # automatic download handoff. The delivery gate rechecks
                    # its recorded call, exact archive path and current hash.
                    self._record_package_delivery(delivery_reports, call['call_id'], result)
                    if route.get('route') == 'package':
                        self._queue_reviewed_package_run(execution_calls, result)
                if (result.get('ok') and call['name'] == 'copilot.download'
                        and route.get('route') == 'package'):
                    package_review = await self._inspect_downloaded_package(result, response['request_id'])
                    results.append(package_review)
                    if package_review.get('ok'):
                        package_review_failure = None
                        downloaded = self._delivery_result('copilot.download', result)
                        inspected = package_review.get('result', {})
                        review = inspected.get('review', {}) if isinstance(inspected, dict) else {}
                        expected_digest = downloaded.get('sha256') if isinstance(downloaded, dict) else None
                        inspected_digest = (review.get('archive_sha256') if isinstance(review, dict) else None)
                        inspected_path = inspected.get('archive') if isinstance(inspected, dict) else None
                        try:
                            download_path = downloaded.get('path', '') if isinstance(downloaded, dict) else ''
                            same_path = (self.policy.resolve(download_path, must_exist=True)
                                         == self.policy.resolve(inspected_path or '', must_exist=True))
                        except (OSError, PolicyError, TypeError, ValueError):
                            same_path = False
                        if (self._review_passed(package_review) and isinstance(expected_digest, str)
                                and len(expected_digest) == 64 and inspected_digest == expected_digest
                                and inspected.get('archive_sha256') == expected_digest and same_path):
                            self._record_package_delivery(delivery_reports, package_review.get('call_id'), package_review)
                            self._queue_reviewed_package_run(execution_calls, package_review)
                    else:
                        package_review_failure = package_review
                        break
                if not result.get('ok'):
                    if call['name'] == 'copilot.download' and result.get('result', {}).get('status') == 'not_started':
                        delivery_link_rejected = True
                    break
            if self.cancel_event.is_set():
                self.state.data['status'] = 'cancelled'
                self.state.save()
                return dict(response, completion_status='blocked', user_response='Cancelled; verified partial results are retained. Already submitted effects require inspection.')
            completed_ids = {item['call_id'] for item in results}
            turn_call_ids.update(completed_ids)
            not_executed = [{'call_id': call['call_id'], 'name': call['name'],
                             'reason': 'Earlier prerequisite failed or was denied; not executed.'}
                            for call in execution_calls if call['call_id'] not in completed_ids]
            if interrupted_by_steering:
                self.browser._goal_navigation = {}
                goal_outcomes.clear()
                kind, content = 'steering', interrupted_by_steering['content']
                content['completed_tool_results'] = redact(results)
                content['not_executed_prior_plan'] = not_executed
                round_attachments = interrupted_by_steering['attachments']
                round_steering_ids.extend(interrupted_by_steering['message_ids'])
                continue
            kind, content = 'tool_results', {'results': redact(results), 'not_executed': not_executed, 'instruction': (
                'Use these actual outcomes. Never infer unexecuted steps succeeded. A denial is authoritative. '
                'When a method fails with verified certain effects, continue using '
                'a targeted repair to that same approach, including a small selector, argument, path, timeout or script correction, through registered tools or a newly proposed exact '
                'Code Runner script. Preserve successful work. The supervised session grant authorizes valid revisions automatically; other sessions use their applicable approval flow. '
                'If a navigation-only browser call is uncertain, request browser.info, then browser.reconcile '
                'with fresh evidence. If a non-navigation browser effect cannot be reconciled, request the separately '
                'approved browser.recover_uncertain action; it quarantines the unknown outcome, verifies a fresh '
                'same-origin checkpoint, and permits this original run to continue without replay. '
                'For uncertain site_knowledge.save, request operation.reconcile after a fresh bound-namespace readback. '
                'For uncertain filesystem or other knowledge effects, inspect the result and request approved '
                'operation.quarantine when the outcome cannot be established; unrelated effect domains remain available. '
                'Stop only at success, denial, cancellation, or a genuine safety/permission boundary.')}
            package_repair = self._package_review_repair_instruction(results)
            if package_repair:
                content['instruction'] += '\n\n' + package_repair
            elif package_review_failure:
                prior_repair = self._package_review_repair_instruction([package_review_failure])
                if prior_repair:
                    content['instruction'] += '\n\n' + prior_repair
            run_repair = self._package_run_repair_instruction(results)
            if any(item.get('tool') == 'automation.run'
                   and item.get('call_id', '').startswith('auto-package-run-')
                   and item.get('result', {}).get('status') == 'completed' for item in results):
                content['instruction'] += (
                    '\n\nThe approved ZIP has already finished executing locally. Use its final stage and output '
                    'verification results to produce the final answer; do not request another run of this completed package.')
            if run_repair:
                package_run_failure = next((item for item in reversed(results)
                                            if isinstance(item, dict) and item.get('tool') == 'automation.run'
                                             and item.get('result', {}).get('status') not in {'completed', 'not_started', 'cancelled'}),
                                           package_run_failure)
                content['instruction'] += '\n\n' + run_repair
            if any(item.get('error', {}).get('code') == 'package_delivery_required'
                   for item in results if isinstance(item, dict)):
                content['instruction'] += (
                    '\n\nThis is a Copilot-delivered package task. Do not build or unpack a local substitute. '
                    'Create the ZIP in Copilot Chat, run relevant tests in Copilot\'s cloud sandbox when available, '
                    'and include a fresh clickable download link with the matching download request. '
                    'The local orchestrator will inspect it immediately. Cloud tests do not replace any user-requested live test in the local agent environment; do not claim live success until it passes.'
                )
            download_recovery = self._download_recovery_instruction(results)
            if download_recovery:
                content['instruction'] += '\n\n' + download_recovery
            if self.base_context.get('discovery_synthesis_pending'):
                content['instruction'] = ('This consolidated discovery/navigation run is terminal. Produce final evidence-ID-grounded synthesis or a blocked error with material gaps. '
                                          'No further tool, Code Runner, fallback, routine retry or replan call is accepted in this turn; a new execution needs a new explicit user request.')
        raise RuntimeError('Conversation turn exhausted')

    async def _prepare_user_attachments(self, attachments):
        """Review and approve one user-provided batch before any upload."""
        if not attachments:
            return []
        paths = [Path(path) for path in attachments]
        if any(path.suffix.casefold() in {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.png', '.jpg', '.jpeg'}
               for path in paths):
            self.state.data['website_task_active'] = True
        queue = self.attachment_queue()
        records = queue.add(paths)
        file_hashes = {record['path']: record['sha256'] for record in records}
        preview = {'action': 'attach_user_files', 'upload_id': uuid.uuid4().hex,
                   'files': records, 'destination': self.config.copilot_url}
        call = {'call_id': uuid.uuid4().hex, 'name': 'local_attachment',
                'version': '1.0', 'arguments': preview}
        allowed, _ = await self.approvals.request(preview, call)
        if not allowed:
            return None
        self.approved_attachment_hashes.update(file_hashes)
        self.approved_attachment_upload_names.update({record['path']: record['upload_name']
                                                      for record in records})
        return queue.paths()

    async def _take_steering(self, active_goal):
        """Incorporate ordered UI steering only at safe orchestration boundaries."""
        if self.steering_poll is None:
            return None
        items = list(self._pending_steering_items)
        self._pending_steering_items.clear()
        items.extend(self.steering_poll())
        if not items:
            return None
        if self._active_turn_run_id is not None:
            accepted, stale = [], []
            for item in items:
                target_id = item.get('active_run_id') or item.get('parent_run_id') if isinstance(item, dict) else None
                (accepted if target_id in (None, self._active_turn_run_id) else stale).append(item)
            if stale:
                reason = 'Steering message targeted a different or completed run.'
                self.feedback.emit('Warning',
                    'A queued steering message was not applied because its original run ended. Resubmit it to continue.')
                if self.event_sink:
                    for item in stale:
                        self.event_sink('steering', {'message_id': item.get('message_id'),
                            'active_run_id': item.get('active_run_id'), 'sequence': item.get('sequence'),
                            'status': 'failed', 'summary': reason})
                if self.steering_complete:
                    self.steering_complete([item.get('message_id') for item in stale
                                            if isinstance(item, dict) and item.get('message_id')])
            items = accepted
            if not items:
                return None
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                raise PolicyError('Queued steering input is invalid; it was not incorporated')
            message_id = item.get('message_id')
            sequence = item.get('sequence')
            text = item.get('text')
            attachments = item.get('attachments', ())
            if (not isinstance(message_id, str) or not message_id or type(sequence) is not int
                    or not isinstance(text, str) or not text.strip() or len(text) > 100000
                    or not isinstance(attachments, (list, tuple)) or len(attachments) > 20):
                raise PolicyError('Queued steering input failed validation; it was not incorporated')
            if SENSITIVE.search(text):
                raise PolicyError('Steering text contains credential-like material; remove it before retrying')
            normalized.append({'message_id': message_id, 'sequence': sequence,
                               'text': text.strip(), 'attachments': list(attachments),
                               'submitted_at': item.get('submitted_at'),
                               'active_run_id': item.get('active_run_id'),
                               'parent_run_id': item.get('parent_run_id')})
        normalized.sort(key=lambda item: item['sequence'])
        if len({item['message_id'] for item in normalized}) != len(normalized):
            raise PolicyError('Duplicate steering message identity was rejected')
        # Keep each user's message and its files together. Rapid messages are
        # replayed as separate Copilot exchanges so each may use the full
        # per-message allowance without dropping or merging file provenance.
        self._pending_steering_items.extend(normalized[1:])
        normalized = normalized[:1]
        all_attachments = normalized[0]['attachments']
        attachment_error = None
        try:
            approved = await self._prepare_user_attachments(all_attachments) if all_attachments else []
        except (PolicyError, OSError, ValueError):
            # Keep the user's steering text and report the missing file context;
            # this avoids aborting the original run on a stale S:/OneDrive path.
            approved = []
            attachment_error = 'Selected files could not be read or validated; no file content was sent.'
            self.feedback.emit('Warning', attachment_error + ' The steering text will continue without those files.')
        if all_attachments and approved is None:
            attachment_error = 'File attachment approval was denied; no file content was sent.'
        if attachment_error and self.steering_complete:
            self.steering_complete([normalized[0]['message_id']])
        attachment_status = ('none' if not all_attachments else
                             'denied' if approved is None else
                             'failed' if attachment_error else 'available')
        approved_by_path = {str(path) for path in approved or []}
        message_records = []
        for item in normalized:
            accepted_attachments = [str(Path(path)) for path in item['attachments']
                                    if str(Path(path)) in approved_by_path]
            attachment_names = [Path(path).name for path in accepted_attachments]
            record = {'message_id': item['message_id'], 'sequence': item['sequence'],
                      'text': item['text'], 'attachments': accepted_attachments,
                      'attachment_names': attachment_names,
                      'attachment_error': attachment_error if item['message_id'] == normalized[0]['message_id'] else None,
                      'attachment_status': attachment_status if item['message_id'] == normalized[0]['message_id'] else
                                           'available' if item['attachments'] else 'none',
                      'active_run_id': item.get('active_run_id')}
            message_records.append(record)
            self.state.message('user', item['text'], message_id=item['message_id'],
                               parent_run_id=(item.get('parent_run_id') or item.get('active_run_id') or self.state.session_id),
                               active_run_id=item.get('active_run_id'), conversation_id=self.state.session_id,
                               sequence=item['sequence'],
                               source='steering', incorporated=True,
                               attachment_count=len(accepted_attachments),
                               attachment_names=attachment_names,
                               attachment_status=record['attachment_status'],
                               attachment_error=attachment_error)
            self.state.event('steering_incorporated', message_id=item['message_id'],
                             parent_run_id=(item.get('parent_run_id') or item.get('active_run_id') or self.state.session_id),
                             active_run_id=item.get('active_run_id'), sequence=item['sequence'],
                             attachment_count=len(accepted_attachments),
                             attachment_status=record['attachment_status'])
            self.state.data['requirements'].append(item['text'])
        self.state.save()
        goal = {'original_request': active_goal,
                'steering_messages': [{'message_id': item['message_id'],
                                       'sequence': item['sequence'], 'text': item['text'],
                                       'attachment_count': len(item['attachments']),
                                       'attachment_names': item['attachment_names'],
                                       'attachment_error': item.get('attachment_error')}
                                      for item in message_records],
                'instruction': ('Continue the same active user goal, incorporating these ordered updates. '
                                'These are user instructions and context. Re-evaluate the pending plan before '
                                'any further local action; actions from an earlier unexecuted plan are superseded.')}
        self.base_context['research_user_request'] = json.dumps(goal, ensure_ascii=False)
        for item in message_records:
            self._authorize_user_targets(item['text'])
        self.feedback.emit('Orchestrator', 'Incorporated ' + str(len(message_records)) +
                           ' steering message(s) into the active goal before continuing.')
        if self.event_sink:
            for item in message_records:
                self.event_sink('steering', {'message_id': item['message_id'],
                                             'active_run_id': item.get('active_run_id'),
                                             'sequence': item['sequence'],
                                             'status': 'incorporated',
                                             'summary': ('Steering text incorporated; file approval was denied.'
                                                         if item.get('attachment_status') == 'denied' else
                                                         'Steering text incorporated; attachments were unavailable.'
                                                         if item.get('attachment_error') else
                                                         'Steering message incorporated into the active run.')})
        return {'content': goal, 'attachments': approved or [],
                'message_ids': [item['message_id'] for item in message_records]}

    def _browser_preparation(self, call):
        args = call['arguments']
        prepared = {'shared_verified_profile': True, 'javascript_enabled': True,
                    'navigation_scope': 'This browser approval also permits continued navigation, navigation-only links, inspection and bounded same-origin new tabs within approved websites for this session. Forms, searches, writes, downloads, scripts and consequential controls still require their normal approval. The grant expires with this agent session.',
                    'managed_tab_only': True, 'dependency_domains': list(args.get('allowed_domains', [])),
                    'limitations': 'Uses an owned tab in the verified Copilot Edge profile; existing site sign-ins are shared. Bounded tabs and exact approved downloads; no unrestricted hosts.'}
        prepared['limitations'] += ' One prefilled login-button click is allowed under the discovery session grant; denied login or MFA pauses for the user. No credentials are extracted.'
        if call['name'] == 'browser.open':
            from .session_mode import website_policy
            prepared.update(website_domain=website_policy(self.config).website_domain(args['url']), includes_subdomains=True)
        return prepared

    def _delivery_result(self, name, outcome):
        """Recover our hash-bound full evidence when a package exceeds chat limits."""
        result = outcome.get('result', {})
        if not result.get('truncated'): return result
        policy = PathPolicy([self.state.directory / 'tool_results'])
        path = policy.resolve(result['retained_result'], True)
        if path.stat().st_size > 20 * 1024 * 1024: raise PolicyError('Retained delivery report exceeds local verification bounds')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != result['sha256']: raise PolicyError('Retained delivery evidence changed')
        full = json.loads(data)
        if full.get('tool') != name or full.get('ok') is not True: raise PolicyError('Retained delivery report identity mismatch')
        return full['result']

    def _delivery_verified(self, requirement, reports):
        """Require verified on-disk results from this turn, never model assertions."""
        def current(artifact):
            try:
                path = self.policy.resolve(artifact['path'], True)
                if not path.is_file() or path.stat().st_size > self.config.max_download_bytes: return False
                return hashlib.sha256(path.read_bytes()).hexdigest() == artifact.get('sha256')
            except (KeyError, OSError, PolicyError): return False
        downloads = [report for report in reports if report.get('tool') == 'copilot.download' and
                     report.get('status') in {'verified', 'downloaded'} and current(report)]
        if (requirement.get('mode') == 'zip'
                and requirement.get('reason', '').startswith('A complete coding project/package')):
            zip_names = {Path(report.get('path', '')).name.casefold() for report in downloads
                         if Path(report.get('path', '')).suffix.casefold() == '.zip'}
            explicitly_named_zips = {name.casefold() for name in requirement.get('expected_names', [])
                                      if Path(name).suffix.casefold() == '.zip'}
            return bool(zip_names) and (not explicitly_named_zips or bool(zip_names & explicitly_named_zips))
        if (requirement.get('mode') == 'zip'
                and not requirement.get('reason', '').startswith('Office outputs ')):
            expected_names = requirement.get('expected_names', [])
            zip_only = (isinstance(expected_names, (list, tuple))
                        and all(isinstance(name, str) and Path(name).suffix.casefold() == '.zip'
                                for name in expected_names))
            if zip_only:
                for receipt in reports:
                    if (receipt.get('tool') != 'automation.inspect'
                            or receipt.get('status') != 'verified'
                            or receipt.get('review_status') not in (
                                {'passed', 'skipped'} if getattr(self.config, '_package_review_enabled', True) is False else {'passed'})):
                        continue
                    inspection_id = receipt.get('inspection_call_id')
                    inspection = self.state.data.get('calls', {}).get(inspection_id, {})
                    request_record = inspection.get('request', {}) if isinstance(inspection, dict) else {}
                    arguments = request_record.get('arguments', {}) if isinstance(request_record, dict) else {}
                    outcome = inspection.get('result', {}) if isinstance(inspection, dict) else {}
                    inspected = outcome.get('result', {}) if isinstance(outcome, dict) else {}
                    review = inspected.get('review', {}) if isinstance(inspected, dict) else {}
                    digest = receipt.get('sha256')
                    if (request_record.get('name') != 'automation.inspect'
                            or not self._review_passed(outcome)
                            or arguments.get('expected_sha256') not in (None, digest)
                            or review.get('archive_sha256') != digest
                            or inspected.get('archive_sha256') != digest):
                        continue
                    try:
                        receipt_path = self.policy.resolve(receipt['path'], True)
                        inspected_path = self.policy.resolve(arguments.get('path', ''), True)
                    except (KeyError, OSError, PolicyError, TypeError, ValueError):
                        continue
                    if receipt_path != inspected_path:
                        continue
                    matched_download = False
                    for download in downloads:
                        if download.get('sha256') != digest:
                            continue
                        try:
                            if self.policy.resolve(download['path'], True) == receipt_path:
                                matched_download = True
                                break
                        except (KeyError, OSError, PolicyError, TypeError, ValueError):
                            continue
                    if not matched_download:
                        continue
                    if expected_names and receipt_path.name.casefold() not in {
                            name.casefold() for name in expected_names}:
                        continue
                    return True
        candidates = []
        for report in reports:
            if report.get('tool') == 'archives.extract' and report.get('status') in {'verified', 'verified_with_limitations'}:
                if any(download['sha256'] == report.get('archive_sha256') and
                       Path(download['path']).resolve() == Path(report.get('archive', '')).resolve() for download in downloads):
                    candidates.extend(report.get('verified_files', []))
            elif requirement.get('mode') == 'direct' and report in downloads:
                if Path(report.get('path', '')).suffix.lower() != '.zip': candidates.append(report)
        actual = set()
        for artifact in candidates:
            try:
                path = self.policy.resolve(artifact['path'], True)
                if not path.is_file() or path.stat().st_size > self.config.max_download_bytes: continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != artifact.get('sha256'): continue
                actual.add(path.name.casefold())
                actual.add(str(artifact.get('relative_path', path.name)).casefold())
            except (KeyError, OSError, PolicyError): continue
        expected = {name.casefold() for name in requirement.get('expected_names', [])}
        if requirement.get('reason', '').startswith('Office outputs '):
            from .delivery import OFFICE_EXTENSIONS
            if not any(Path(artifact.get('path', '')).suffix.lower().lstrip('.') in OFFICE_EXTENSIONS and
                       Path(artifact.get('path', '')).name.casefold() in actual for artifact in candidates):
                return False
        # The named outer archive is delivered alongside its verified contents.
        if actual:
            actual.update(Path(report['path']).name.casefold() for report in downloads)
        return bool(actual) and expected.issubset(actual)

    async def close(self, *, preserve_browser_process=False):
        preparation, self._next_turn_preparation = self._next_turn_preparation, None
        if preparation is not None:
            preparation.cancel()
            await asyncio.gather(preparation, return_exceptions=True)
        self.approvals.revoke_session_grants()
        self.state.data['status'] = 'closed'
        self.state.save()
        cleaned = await asyncio.to_thread(self.process_registry.cleanup_all)
        if cleaned:
            self.feedback.emit('Orchestrator', 'Cleaned up ' + str(sum(1 for item in cleaned if item['stopped'])) +
                               '/' + str(len(cleaned)) + ' managed persistent process(es).')
        if preserve_browser_process:
            await self.browser.close(preserve_browser_process=True)
        else:
            await self.browser.close()
