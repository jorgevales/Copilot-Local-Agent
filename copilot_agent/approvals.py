from __future__ import annotations
import asyncio
import json
from pathlib import Path
from .persistence import write_json
from .state import canonical_hash


class ApprovalManager:
    """A grant binds the full displayed immutable pending plan; never approve forever."""
    def __init__(self, state, decide=None):
        self.state, self.decide = state, decide

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
        print('\n[Orchestrator] Approval required. Full immutable preview: ' + str(path))
        if call['name'] == 'local_attachment':
            print('[Orchestrator] Send these files to Copilot for this request: ' + ', '.join(file.get('name', Path(file['path']).name) for file in plan['files']))
        print('[Orchestrator] Requested operation and exact scope; approval is pending:')
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        if self.decide:
            decision = self.decide(preview)
            if hasattr(decision, '__await__'):
                decision = await decision
        else:
            decision = await asyncio.to_thread(input, '\n[User] Choose 1 = Deny, 2 = Allow once, 3 = Allow this complete plan [1/2/3 or deny/once/plan]: ')
        decision = str(decision).strip().lower()
        decision = {'1': 'deny', '2': 'once', '3': 'plan'}.get(decision, decision)
        if decision not in {'deny', 'once', 'plan'}:
            decision = 'deny'
        self.state.grant(plan_hash if decision == 'plan' else call_hash, decision)
        return decision in {'once', 'plan'}, plan_hash if decision == 'plan' else call_hash
