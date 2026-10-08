from __future__ import annotations
import hashlib
import json
from pathlib import Path
import uuid
from .logging_utils import EventLog, now, redact
from .persistence import write_json


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


class SessionState:
    def __init__(self, directory: Path, resume: bool = False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'session.json'
        self.log = EventLog(self.directory / 'events.jsonl')
        if self.path.exists():
            if not resume:
                raise ValueError('Session exists; use explicit resume')
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('schema_version') != '1.0':
                raise ValueError('Unsupported session schema version')
            if self.data.get('pending_submission'):
                self.data['status'] = 'submission_uncertain'
            for call in self.data['calls'].values():
                if call['status'] == 'executing':
                    call['status'] = 'uncertain'
            self.data['approvals'] = {}  # Resume never silently inherits execution grants.
            self.save()
        else:
            self.data = {'schema_version': '1.0', 'session_id': uuid.uuid4().hex, 'status': 'created',
                         'created_at': now(), 'updated_at': now(), 'message_count': 0, 'messages': [],
                         'calls': {}, 'approvals': {}, 'attachments': [], 'guidance_manifest': [],
                         'current_plan': [], 'pending_submission': None, 'retry_records': [],
                         'approved_domains': [],
                         'response_ids': [], 'summary': '', 'requirements': [], 'decisions': [],
                         'constraints': [], 'unresolved_questions': [], 'findings_sync': []}
            self.save()

    @property
    def session_id(self):
        return self.data['session_id']

    @property
    def message_count(self):
        return self.data['message_count']

    def save(self):
        self.data['updated_at'] = now()
        data = self.data
        if data.get('website_private'):
            from .web_privacy import private_session_snapshot
            data = private_session_snapshot(data)
        write_json(self.path, redact(data))

    def event(self, event_type: str, **details):
        if self.data.get('website_private'):
            from .web_privacy import audit_evidence, private_id
            # Correlation IDs and outcomes suffice for ordinary diagnostics.
            metadata = {key: details[key] for key in ('call_id', 'request_id', 'ordinal', 'attempt')
                        if key in details}
            if 'call_id' in metadata:
                metadata['call_id'] = private_id(metadata['call_id'])
            details = dict(metadata, evidence=audit_evidence(details))
        self.log.write(event_type, **details)

    def message(self, role: str, content, **metadata):
        self.data['messages'].append(redact({'role': role, 'content': content, 'timestamp': now(), **metadata}))
        self.save()

    def begin_submission(self, request_id: str, text: str):
        if self.data['pending_submission']:
            raise RuntimeError('Previous submission has uncertain delivery; reconcile first')
        self.data['pending_submission'] = {'request_id': request_id, 'ordinal': self.message_count + 1, 'text_hash': hashlib.sha256(text.encode()).hexdigest()}
        self.save()

    def confirm_submission(self, request_id: str):
        pending = self.data['pending_submission']
        if not pending or pending['request_id'] != request_id:
            raise RuntimeError('Submission identity does not match persisted intent')
        self.data['message_count'] = pending['ordinal']
        self.data['pending_submission'] = None
        self.event('message_submitted', request_id=request_id, ordinal=self.message_count)
        self.save()

    def reconcile_submission(self, submitted: bool):
        pending = self.data['pending_submission']
        if not pending:
            return
        if submitted:
            self.confirm_submission(pending['request_id'])
        else:
            self.event('submission_reconciled_not_sent', request_id=pending['request_id'])
            self.data['pending_submission'] = None
            self.save()

    def begin_call(self, request: dict, state_changing: bool = True):
        call_id = request['call_id']
        from .web_privacy import private_id
        if call_id in self.data['calls'] or private_id(call_id) in self.data['calls']:
            raise RuntimeError('Duplicate call ID cannot execute again')
        if state_changing and any(c['status'] == 'uncertain' and c.get('state_changing', True) for c in self.data['calls'].values()):
            raise RuntimeError('A previous state-changing operation remains uncertain; inspect and reconcile before another change')
        action_hash = canonical_hash({k: request[k] for k in ('name', 'version', 'arguments')})
        if any(c.get('action_hash') == action_hash and c['status'] == 'uncertain' for c in self.data['calls'].values()):
            raise RuntimeError('An identical action has uncertain effects; reconcile before requesting it again')
        self.data['calls'][call_id] = {'status': 'executing', 'request_hash': canonical_hash(request), 'action_hash': action_hash, 'state_changing': state_changing, 'request': request, 'started_at': now()}
        self.event('tool_intent', call_id=call_id, name=request['name'], request_hash=canonical_hash(request))
        self.save()

    def finish_call(self, call_id: str, result: dict):
        call = self.data['calls'][call_id]
        code = result.get('error', {}).get('code')
        evidence = result.get('result', {}) if isinstance(result.get('result'), dict) else {}
        explicitly_certain = evidence.get('side_effects_uncertain') is False
        uncertain = (call.get('state_changing', True) and not result.get('ok')
                     and code not in {'approval_denied', 'invalid_arguments'} and not explicitly_certain)
        if call['request']['name'] == 'copilot.download' and result.get('result', {}).get('status') == 'not_started' and result['result'].get('side_effects_uncertain') is False:
            uncertain = False
        call.update(status='uncertain' if uncertain else 'completed', result=redact(result), finished_at=now())
        self.event('tool_outcome', call_id=call_id, result=result)
        self.save()

    def fail_active_turn(self, reason: str = 'unexpected_error'):
        """Close interrupted call intents without asserting that effects did not occur."""
        interrupted = []
        for call_id, call in self.data['calls'].items():
            if call['status'] != 'executing':
                continue
            uncertain = call.get('state_changing', True)
            call.update(
                status='uncertain' if uncertain else 'completed',
                result={'ok': False, 'error': {'code': 'interrupted',
                                                'message': 'The turn stopped before a verified tool outcome was recorded.'},
                        'result': {'side_effects_uncertain': uncertain}},
                finished_at=now(),
            )
            interrupted.append((call_id, uncertain))
        self.data['status'] = 'submission_uncertain' if self.data.get('pending_submission') else 'blocked'
        self.data['last_turn_outcome'] = {'status': 'failed', 'reason': reason, 'at': now()}
        self.save()
        for call_id, uncertain in interrupted:
            try:
                self.event('tool_interrupted', call_id=call_id, uncertain=uncertain)
            except OSError:
                pass
        try:
            self.event('turn_failed', reason=reason)
        except OSError:
            pass

    def approve_domain(self, domain: str):
        domain = str(domain).lower().rstrip('.')
        domains = self.data.setdefault('approved_domains', [])
        if domain not in domains:
            domains.append(domain)
            self.event('browser_domain_approved', domain=domain)
            self.save()

    def reconcile_call(self, call_id: str, outcome: str):
        if outcome not in {'completed', 'not_executed'} or self.data['calls'][call_id]['status'] != 'uncertain':
            raise ValueError('Only an uncertain call may be reconciled with completed/not_executed')
        self.data['calls'][call_id]['status'] = outcome
        self.event('call_reconciled_by_user', call_id=call_id, outcome=outcome)
        self.save()

    def grant(self, plan_hash: str, decision: str):
        self.data['approvals'][plan_hash] = {'decision': decision, 'timestamp': now()}
        self.event('approval', plan_hash=plan_hash, decision=decision)
        self.save()

    def context(self, max_chars: int = 16000) -> dict:
        recent = []
        consumed = 0
        for item in reversed(self.data['messages']):
            if item['role'] not in {'user', 'copilot'}:
                continue  # Transport envelopes/raw diagnostics are retained, not recursively resent.
            size = len(json.dumps(item, ensure_ascii=False))
            if consumed + size > max_chars:
                break
            recent.append(item)
            consumed += size
        pending = {k: v for k, v in self.data['calls'].items() if v['status'] in {'executing', 'uncertain'}}
        return {k: self.data[k] for k in ('session_id', 'summary', 'requirements', 'decisions', 'constraints', 'unresolved_questions', 'current_plan')} | {
            'recent_messages': list(reversed(recent)), 'pending_operations': pending,
            'approval_state': self.data['approvals'], 'message_count': self.message_count,
            'attachments': self.data['attachments'], 'history_messages_retained_locally': len(self.data['messages'])}
