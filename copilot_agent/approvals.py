from __future__ import annotations
import asyncio
import json
from pathlib import Path
from .feedback import Feedback
from .persistence import write_json
from .state import canonical_hash


class ApprovalManager:
    """A grant binds the full displayed immutable pending plan; never approve forever."""
    def __init__(self, state, decide=None, feedback=None):
        self.state, self.decide = state, decide
        self.feedback = feedback or Feedback(state=state)

    def _show(self, preview, path):
        prepared = list((preview.get('prepared_pending_plan') or {}).values())
        if preview.get('prepared_code') and not prepared:
            prepared = [preview['prepared_code']]
        current = preview['complete_pending_plan'].get('tool_requests', [])
        current_call = next((item for item in current if item.get('call_id') == preview['current_call_id']), {})
        arguments = current_call.get('arguments', {})
        self.feedback.section('Approval', 'EXPLICIT APPROVAL REQUIRED', [
            ('Scope', 'This exact immutable execution only; every material change requires fresh approval.'),
            ('Purpose', arguments.get('purpose') or current_call.get('name')),
            ('Language', arguments.get('language')),
            ('Interpreter', arguments.get('interpreter') or ('restricted in-process python_subset' if arguments.get('language') == 'python_subset' else None)),
            ('Arguments', arguments.get('arguments')),
            ('Permissions', arguments.get('permissions')),
            ('Read paths', arguments.get('read_paths')),
            ('Create paths', arguments.get('create_paths')),
            ('Modify paths', arguments.get('modify_paths')),
            ('Network', arguments.get('network_destinations')),
            ('Subprocesses', arguments.get('subprocesses')),
            ('Viewer windows', arguments.get('viewer_windows')),
            ('Expected effects', arguments.get('expected_effects')),
            ('Risk', arguments.get('risk_summary') or preview['complete_pending_plan'].get('risk_summary')),
            ('Plan hash', preview['plan_hash']),
            ('Full retained preview', str(path)),
        ])
        seen = set()
        for index, item in enumerate(prepared, 1):
            digest = item.get('script_sha256')
            if not digest or digest in seen:
                continue
            seen.add(digest)
            script = item.get('plan', {}).get('script', '')
            self.feedback.emit('Approval', 'EXACT SCRIPT ' + str(index) + ' | SHA-256 ' + digest +
                               '\n----- BEGIN EXACT SCRIPT -----\n' + script +
                               '\n----- END EXACT SCRIPT -----', preserve_markup=True)

    async def request(self, plan: dict, call: dict, prepared=None, *, prepared_plan=None) -> tuple[bool, str]:
        # Observed artifacts/destinations must be part of the grant, not merely
        # Copilot's proposed arguments. Changed preparation invalidates approval.
        if prepared_plan is not None:
            calls = plan.get('tool_requests', [])
            ids = [item.get('call_id') for item in calls]
            if (not calls or any(item.get('name') != 'code_runner' for item in calls)
                    or not isinstance(prepared_plan, dict) or any(not isinstance(key, str) or not key for key in ids)
                    or len(ids) != len(set(ids)) or set(prepared_plan) != set(ids)
                    or any(not isinstance(item, dict) for item in prepared_plan.values())):
                raise ValueError('A complete prepared plan is supported only for all-code-runner calls with exact unique call identities.')
            current = next((item for item in calls if item['call_id'] == call.get('call_id')), None)
            if (current is None or canonical_hash(current) != canonical_hash(call)
                    or prepared is None or canonical_hash(prepared_plan[call['call_id']]) != canonical_hash(prepared)):
                raise ValueError('The current code proposal differs from the complete prepared plan; prepare the full plan again before approval.')
            plan_hash = canonical_hash({'plan': plan, 'prepared_pending_plan': prepared_plan})
        else:
            plan_hash = canonical_hash({'plan': plan, 'prepared_current_call': prepared}) if prepared is not None else canonical_hash(plan)
        call_hash = canonical_hash({'plan_hash': plan_hash, 'call': call})
        grant = self.state.data['approvals'].get(plan_hash)
        if grant and grant['decision'] == 'plan':
            return True, plan_hash
        preview = {'approval_scope': 'Only this exact plan or execution; material changes require renewed approval.',
                   'plan_hash': plan_hash, 'call_hash': call_hash, 'current_call_id': call['call_id'],
                   'complete_pending_plan': plan, 'prepared_code': prepared,
                   'choices': ['deny', 'once', 'plan']}
        if prepared_plan is not None:
            preview['prepared_pending_plan'] = prepared_plan
        path = self.state.directory / 'approvals' / (call_hash + '.json')
        write_json(path, preview)
        self._show(preview, path)
        if call['name'] == 'local_attachment':
            self.feedback.emit('Approval', 'Files proposed for Copilot: ' + ', '.join(file.get('name', Path(file['path']).name) for file in plan['files']))
        if self.decide:
            decision = self.decide(preview)
            if hasattr(decision, '__await__'):
                decision = await decision
        else:
            prompt = self.feedback.prompt('User', 'Choose 1 = Deny, 2 = Allow this exact execution once, 3 = Allow this exact displayed plan [1/2/3]: ')
            decision = await asyncio.to_thread(input, prompt)
        decision = str(decision).strip().lower()
        decision = {'1': 'deny', '2': 'once', '3': 'plan'}.get(decision, decision)
        if decision not in {'deny', 'once', 'plan'}:
            decision = 'deny'
        self.state.grant(plan_hash if decision == 'plan' else call_hash, decision)
        self.feedback.emit('User', 'Approval decision: ' + decision + '.')
        return decision in {'once', 'plan'}, plan_hash if decision == 'plan' else call_hash
