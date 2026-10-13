from __future__ import annotations
import asyncio
import json
import time
from pathlib import Path
from .feedback import Feedback
from .persistence import write_json
from .state import canonical_hash
from .presentation import call_summary, readable


class ApprovalManager:
    """A grant binds the full displayed immutable pending plan; never approve forever."""
    def __init__(self, state, decide=None, feedback=None):
        self.state, self.decide = state, decide
        self.feedback = feedback or Feedback(state=state)
        # This grant intentionally lives only as long as this ApprovalManager
        # (one local agent session). It is never written to SessionState, so a
        # resumed conversation or new agent process must obtain fresh consent.
        self._package_session_grant = False

    def revoke_session_grants(self):
        """Drop ephemeral package authority when the owning agent session ends."""
        self._package_session_grant = False

    def _show(self, preview, path):
        prepared = list((preview.get('prepared_pending_plan') or {}).values())
        if preview.get('prepared_code') and not prepared:
            prepared = [preview['prepared_code']]
        current = preview['complete_pending_plan'].get('tool_requests', [])
        current_call = next((item for item in current if item.get('call_id') == preview['current_call_id']), {})
        arguments = current_call.get('arguments', {})
        scope = preview.get('prepared_code') or {}
        storage_mode = scope.get('storage_mode')
        storage_label = ('Discoveries C: local test folder' if storage_mode == 'local_c_test'
                         else 'Discoveries S: folder' if storage_mode == 'shared_s'
                         else 'Configured Discoveries folder')
        storage_path = (scope.get('storage_path_s') or scope.get('storage_folder_s_path')
                        or scope.get('directory') or scope.get('storage_folder'))
        resolved_storage_path = (scope.get('storage_path_unc') or scope.get('storage_folder')
                                 or scope.get('directory'))
        if scope.get('approval_scope_type') == 'automation_package':
            package_fresh = bool(scope.get('requires_fresh_run_confirmation'))
            self.feedback.section('Package execution scope',
                                  'FRESH CONFIRMATION REQUIRED FOR THIS PACKAGE RUN' if package_fresh
                                  else 'SESSION GRANT MAY COVER FUTURE INSPECTED RUNS', [
                ('Package', scope.get('package_id')),
                ('Task', scope.get('task_id')),
                ('ZIP SHA-256', scope.get('archive_sha256')),
                ('Manifest SHA-256', scope.get('manifest_sha256')),
                ('Workspace', scope.get('workspace')),
                ('Resume run', scope.get('resume_run_id')),
                ('Patch source run', scope.get('prior_run_id')),
                ('Python stages', scope.get('python_stages')),
                ('Python source review', ('Complete stage source and SHA-256 are shown below; this run needs fresh approval.'
                                          if scope.get('python_stage_reviews') else 'No executable Python stages.')),
                ('Registered tool stages', scope.get('tool_stages')),
                ('Declared capabilities', scope.get('capabilities')),
                ('Configured resource ceilings', scope.get('resource_limits')),
                ('Expected outputs', scope.get('expected_outputs')),
                ('Grant lifetime', ('This run requires fresh approval; session grants cannot authorize executable Python stages.'
                                    if scope.get('python_stage_reviews') else
                                    'This run requires fresh approval; session grants cannot authorize consequential stages.'
                                    if package_fresh else
                                    'This local agent session; fresh automatic inspection remains required for every ZIP run')),
            ])
        if current_call.get('name') == 'files.grant_path':
            extension = scope
            self.feedback.section('Requested file access extension', 'ONE EXACT SESSION PATH GRANT', [
                ('Selected path', extension.get('path') or arguments.get('path')),
                ('Path kind', extension.get('scope') or arguments.get('scope')),
                ('Grant scope', extension.get('extension_scope')),
                ('Operations', extension.get('approved_operations')),
                ('Reason', extension.get('reason') or arguments.get('reason')),
                ('Session', extension.get('session_id')),
                ('Grant lifetime', 'This local agent session; the exact file or selected directory and descendants only'),
            ])
        if scope.get('approval_scope_type') == 'automation_package':
            if scope.get('requires_fresh_run_confirmation'):
                reason = ('its executable Python stages.' if scope.get('python_stage_reviews')
                          else 'its consequential or unbounded stages.')
                approval_scope = ('This exact package run requires fresh approval; session or reusable plan grants cannot authorize '
                                  + reason)
            else:
                approval_scope = 'This session grant covers later packages only after their fresh automatic inspection passes.'
        else:
            approval_scope = 'This exact immutable execution only; every material change requires fresh approval.'
        self.feedback.section('Approval', 'EXPLICIT APPROVAL REQUIRED', [
            ('Scope', approval_scope),
            ('Purpose', arguments.get('purpose') or current_call.get('name')),
            ('Language', arguments.get('language')),
            ('Interpreter', arguments.get('interpreter') or ('restricted in-process python_subset' if arguments.get('language') == 'python_subset' else None)),
            ('Arguments', arguments.get('arguments')),
            ('File path', arguments.get('path')),
            ('Source path', arguments.get('source')),
            ('Destination path', arguments.get('destination')),
            ('Resolved S: destination', (preview.get('prepared_code') or {}).get('mapped_s_drive_destination')),
            ('Storage mode', storage_mode),
            (storage_label, storage_path),
            ('Resolved Discoveries filesystem path', resolved_storage_path),
            ('Recovery call ID', arguments.get('call_id')),
            ('Recovery target', (preview.get('prepared_code') or {}).get('uncertain_operation')),
            ('Permissions', arguments.get('permissions')),
            ('Read paths', arguments.get('read_paths')),
            ('Create paths', arguments.get('create_paths')),
            ('Modify paths', arguments.get('modify_paths')),
            ('Network', arguments.get('network_destinations')),
            ('Subprocesses', arguments.get('subprocesses')),
            ('Viewer windows', arguments.get('viewer_windows')),
            ('Expected effects', arguments.get('expected_effects')),
            ('Website scope', ((preview.get('prepared_code') or {}).get('website_domain') + ' and its subdomains')
             if (preview.get('prepared_code') or {}).get('website_domain') else None),
            ('Browser access', 'Uses an owned tab in the verified Copilot Edge profile; existing site sign-ins are shared'
             if (preview.get('prepared_code') or {}).get('shared_verified_profile') else None),
            ('Additional hosts', (preview.get('prepared_code') or {}).get('dependency_domains')),
            ('Continued navigation', (preview.get('prepared_code') or {}).get('navigation_scope')),
            ('Risk', arguments.get('risk_summary') or preview['complete_pending_plan'].get('risk_summary')),
        ])
        self.feedback.record('Approval', 'Full immutable approval record retained.',
                             plan_hash=preview['plan_hash'], path=str(path))
        consent = preview.get('prepared_code') or {}
        if str(current_call.get('name', '')).startswith('site_knowledge.'):
            self.feedback.emit('Approval', 'WEBSITE KNOWLEDGE CONSENT\n' +
                               readable(consent) +
                               '\nChoose Deny to continue the current task without saving knowledge.',
                               preserve_markup=True)
        if str(current_call.get('name', '')).startswith(('discovery.', 'navigation.')):
            self.feedback.emit('Approval', 'EXACT DISCOVERY / NAVIGATION GRANT\n' +
                               call_summary(current_call)+'\n'+readable(consent), preserve_markup=True)
        if current and all(str(item.get('name', '')).startswith('browser.') for item in current):
            self.feedback.emit('Approval', 'EXACT ORDERED BROWSER PLAN\n' +
                               '\n\n'.join(call_summary(item) for item in current), preserve_markup=True)
        if str(current_call.get('name','')).startswith('permissions.'):
            self.feedback.emit('Approval','DURABLE RESEARCH CONSENT\n'+readable(consent),preserve_markup=True)
        seen = set()
        for index, item in enumerate(prepared, 1):
            digest = item.get('script_sha256')
            if not digest or digest in seen:
                continue
            seen.add(digest)
            script = item.get('plan', {}).get('script', '')
            self.feedback.emit('Approval', 'EXACT SCRIPT ' + str(index) +
                               '\n----- BEGIN EXACT SCRIPT -----\n' + script +
                               '\n----- END EXACT SCRIPT -----', preserve_markup=True)
        for item in scope.get('python_stage_reviews', []):
            if not isinstance(item, dict):
                continue
            self.feedback.emit('Approval',
                               'EXACT PACKAGE PYTHON STAGE ' + str(item.get('stage', '?')) +
                               '\nSource path: ' + str(item.get('path', '?')) +
                               '\nSource SHA-256: ' + str(item.get('sha256', '?')) +
                               '\n----- BEGIN EXACT SCRIPT -----\n' + str(item.get('script', '')) +
                               '\n----- END EXACT SCRIPT -----', preserve_markup=True)

    async def request(self, plan: dict, call: dict, prepared=None, *, prepared_plan=None) -> tuple[bool, str]:
        # Observed artifacts/destinations must be part of the grant, not merely
        # Copilot's proposed arguments. Changed preparation invalidates approval.
        if prepared_plan is not None:
            calls = plan.get('tool_requests', [])
            ids = [item.get('call_id') for item in calls]
            supported_batch = (all(item.get('name') == 'code_runner' for item in calls)
                               or all(str(item.get('name', '')).startswith('browser.') for item in calls))
            if (not calls or not supported_batch
                    or not isinstance(prepared_plan, dict) or any(not isinstance(key, str) or not key for key in ids)
                    or len(ids) != len(set(ids)) or set(prepared_plan) != set(ids)
                    or any(not isinstance(item, dict) for item in prepared_plan.values())):
                raise ValueError('A complete prepared plan requires all-code-runner or all-browser calls with exact unique call identities.')
            current = next((item for item in calls if item['call_id'] == call.get('call_id')), None)
            if (current is None or canonical_hash(current) != canonical_hash(call)
                    or prepared is None or canonical_hash(prepared_plan[call['call_id']]) != canonical_hash(prepared)):
                raise ValueError('The current code proposal differs from the complete prepared plan; prepare the full plan again before approval.')
            plan_hash = canonical_hash({'plan': plan, 'prepared_pending_plan': prepared_plan})
        else:
            plan_hash = canonical_hash({'plan': plan, 'prepared_current_call': prepared}) if prepared is not None else canonical_hash(plan)
        call_hash = canonical_hash({'plan_hash': plan_hash, 'call': call})
        grant = self.state.data['approvals'].get(plan_hash)
        package_scope = bool((prepared or {}).get('approval_scope_type') == 'automation_package')
        package_fresh = package_scope and bool((prepared or {}).get('requires_fresh_run_confirmation'))
        if package_scope and not package_fresh and self._package_session_grant:
            return True, plan_hash
        if grant and grant.get('decision') == 'plan' and package_scope:
            try:
                expires_at = float(grant.get('expires_at', 0))
            except (TypeError, ValueError):
                expires_at = 0
            if expires_at <= time.time():
                grant = None
        if grant and grant['decision'] == 'plan' and not package_fresh:
            return True, plan_hash
        preview = {'approval_scope': 'Only this exact plan or execution; material changes require renewed approval.',
                   'plan_hash': plan_hash, 'call_hash': call_hash, 'current_call_id': call['call_id'],
                   'complete_pending_plan': plan, 'prepared_code': prepared,
                   'choices': ['deny', 'once', 'plan']}
        if package_scope:
            preview['approval_scope'] = (
                'Fresh confirmation for this exact package run is required because its stages include consequential or '
                'unbounded actions; session and reusable plan grants cannot authorize it.' if package_fresh else
                'One local session grant covers future packages only after each fresh automatic inspection passes; the current '
                'package hashes, tools, effects, paths, and resource scope are shown for transparency. Protected-path and '
                'platform handoffs remain active.')
            preview['approval_scope_type'] = 'automation_package'
            preview['choices'] = ['deny', 'once'] if package_fresh else ['deny', 'once', 'plan', 'session']
        if prepared_plan is not None:
            preview['prepared_pending_plan'] = prepared_plan
        path = self.state.directory / 'approvals' / (call_hash + '.json')
        from .web_privacy import PRIVATE_TOOLS, audit_evidence
        if self.state.data.get('website_private') or any(item.get('name') in PRIVATE_TOOLS for item in plan.get('tool_requests', [])):
            # Show exact content for review; retain hashes rather than customer data.
            stored = {key: preview[key] for key in ('approval_scope', 'plan_hash', 'call_hash', 'current_call_id', 'choices')}
            stored['exact_plan_evidence'] = audit_evidence(plan)
            write_json(path, stored)
        else:
            write_json(path, preview)
        self._show(preview, path)
        if call['name'] == 'local_attachment':
            self.feedback.emit('Approval', 'Files proposed for Copilot: ' + ', '.join(file.get('name', Path(file['path']).name) for file in plan['files']))
        if self.decide:
            decision = self.decide(preview)
            if hasattr(decision, '__await__'):
                decision = await decision
        else:
            prompt_text = ('Choose 1 = Deny, 2 = Allow this exact package run once [1/2]: '
                           if package_fresh else
                           'Choose 1 = Deny, 2 = Allow this exact execution once, '
                           '3 = Allow this exact displayed plan, 4 = Allow inspected packages for this agent session [1/2/3/4]: '
                           if package_scope else
                           'Choose 1 = Deny, 2 = Allow this exact execution once, 3 = Allow this exact displayed plan [1/2/3]: ')
            prompt = self.feedback.prompt('User', prompt_text)
            decision = await asyncio.to_thread(input, prompt)
        decision = str(decision).strip().lower()
        decision = {'1': 'deny', '2': 'once', '3': 'plan', '4': 'session'}.get(decision, decision)
        allowed_decisions = ({'deny', 'once'} if package_fresh else
                             {'deny', 'once', 'plan'} | ({'session'} if package_scope else set()))
        if decision not in allowed_decisions:
            decision = 'deny'
        if decision == 'session':
            self._package_session_grant = True
        else:
            self.state.grant(plan_hash if decision == 'plan' else call_hash, decision)
        if decision == 'plan' and package_scope:
            self.state.data['approvals'][plan_hash]['expires_at'] = time.time() + 1800
            self.state.save()
        self.feedback.emit('User', 'Approval decision: ' + decision + '.')
        return decision in {'once', 'plan', 'session'}, plan_hash if decision in {'plan', 'session'} else call_hash
