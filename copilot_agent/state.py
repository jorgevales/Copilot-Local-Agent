from __future__ import annotations
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
import uuid
from .logging_utils import EventLog, now, redact
from .persistence import write_json


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def browser_inventory(request):
    """Listing owned tabs observes local registration, even before any page exists."""
    return request.get('name') == 'browser.tabs' and request.get('arguments', {}).get('operation') == 'list'


def operation_domains(name: str) -> frozenset[str]:
    """Conservative effect domains; unknown tools retain the global gate."""
    if name.startswith(('site_knowledge.', 'discovery.knowledge_', 'knowledge.')):
        return frozenset({'knowledge'})
    if name in {'files.transfer_to_copilot', 'copilot.download'}:
        return frozenset({'browser', 'filesystem'})
    if name.startswith(('files.', 'archives.')):
        return frozenset({'filesystem'})
    if name.startswith(('browser.', 'documents.', 'research.', 'navigation.')):
        return frozenset({'browser'})
    if name.startswith('discovery.'):
        return frozenset({'browser', 'knowledge'})
    return frozenset({'global'})


def latest_committed_request_id(state) -> str | None:
    """Return the most recent outbound request confirmed in the session ledger."""
    outbound = [message for message in state.data.get('messages', [])
                if message.get('role') == 'copilot_outbound' and message.get('request_id')]
    committed_count = state.data.get('message_count', 0)
    if type(committed_count) is not int or committed_count < 1:
        return None
    committed = outbound[:committed_count]
    return committed[-1]['request_id'] if committed else None


def recoverable_capture_request_id(state) -> str | None:
    """Return a confirmed, unanswered request that can be recaptured without resending."""
    if state.data.get('status') not in {'capture_failed', 'closed', 'running', 'submitting'} or state.data.get('pending_submission'):
        return None
    outbound = [message for message in state.data.get('messages', [])
                if message.get('role') == 'copilot_outbound' and message.get('request_id')]
    committed_count = state.data.get('message_count')
    if type(committed_count) is not int or committed_count < 1 or len(outbound) != committed_count:
        return None
    request_id = outbound[-1]['request_id']
    if any(message.get('role') == 'copilot' and message.get('request_id') == request_id
           for message in state.data.get('messages', [])):
        return None
    # A raw reply may already be saved without its validated response after a
    # crash. Recapture that committed turn; raw evidence is recorded idempotently.
    # The outbound record and count are saved in one atomic session snapshot.
    # The event log is secondary evidence and may lag that snapshot after a crash.
    return request_id


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

        self.repair_browser_observations()

    def repair_browser_observations(self):
        """Correct provably read-only/preflight legacy entries, never unknown effects."""
        repaired, previous = [], {}
        prior_status = self.data['status']
        for call_id, call in self.data['calls'].items():
            if call.get('status') != 'uncertain':
                continue
            request, outcome = call.get('request', {}), call.get('result', {})
            inventory = browser_inventory(request) or call.get('browser_observation_only') is True
            refusal = (request.get('name') == 'browser.recover_uncertain'
                       and outcome.get('error', {}).get('code') == 'policy_denied'
                       and outcome.get('error', {}).get('message') == 'Recovery checkpoint must remain on the uncertain action website')
            if not inventory and not refusal:
                continue
            previous[call_id] = deepcopy(call)
            call.update(status='completed', completion_credited=False,
                        ledger_repair={'kind': 'read_only_inventory' if inventory else 'recovery_preflight_refusal',
                                       'repaired_at': now()})
            if inventory:
                call.update(state_changing=False, browser_observation_only=True)
            call.setdefault('result', {}).setdefault('result', {}).update(
                status='not_started' if not outcome.get('ok') else 'observed', side_effects_uncertain=False)
            repaired.append(call_id)
        if repaired:
            if not self.data.get('pending_submission') and not any(call.get('status') == 'uncertain' for call in self.data['calls'].values()):
                self.data['status'] = 'ready'
            try:
                self.save()
            except Exception:
                self.data['calls'].update(previous)
                self.data['status'] = prior_status
                raise
            try:
                self.event('browser_observation_ledger_repaired', count=len(repaired))
            except OSError:
                pass
        return repaired

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
            pending = data.get('pending_submission')
            if isinstance(pending, dict):
                # Customer content can exceed credential patterns; a private
                # session retains only send identity and hashes on disk.
                data['pending_submission'] = {key: value for key, value in pending.items()
                                              if key != 'text'}
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
        last_unsent = self.data.get('last_reconciled_unsent')
        if last_unsent and last_unsent.get('request_id') != request_id:
            self.data['last_reconciled_unsent'] = None
        safe_text = redact(text)
        self.data['pending_submission'] = {'request_id': request_id, 'ordinal': self.message_count + 1,
                                           'text_hash': hashlib.sha256(text.encode()).hexdigest(),
                                           'redacted_text_hash': hashlib.sha256(safe_text.encode()).hexdigest(),
                                           'text_bytes': len(text.encode()), 'text': safe_text}
        self.save()

    def confirm_submission(self, request_id: str, *, attachments=(), findings_path=None):
        pending = self.data['pending_submission']
        if not pending or pending['request_id'] != request_id:
            raise RuntimeError('Submission identity does not match persisted intent')
        ordinal = pending['ordinal']
        outbound = [message for message in self.data['messages']
                    if message.get('role') == 'copilot_outbound' and message.get('request_id') == request_id]
        if len(outbound) > 1:
            raise RuntimeError('Submission has duplicate outbound records')
        if not outbound:
            text = pending.get('text')
            if isinstance(text, str):
                expected = pending.get('redacted_text_hash', pending['text_hash'])
                if hashlib.sha256(text.encode()).hexdigest() != expected:
                    raise RuntimeError('Confirmed submission has no matching saved text')
            elif self.data.get('website_private') and isinstance(pending.get('text_bytes'), int):
                text = {'content_sha256': pending['text_hash'],
                        'content_bytes': pending['text_bytes'], 'website_content_omitted': True}
            else:
                raise RuntimeError('Confirmed submission has no matching saved text')
            self.data['messages'].append(redact({'role': 'copilot_outbound', 'content': text,
                                                  'timestamp': now(), 'request_id': request_id,
                                                  'ordinal': ordinal}))
        for entry in attachments:
            record = dict(entry, ordinal=ordinal)
            self.data['attachments'].append(record)
            if findings_path is not None and entry.get('path') == str(findings_path):
                self.data['findings_sync'].append(record)
        self.data['message_count'] = ordinal
        self.data['pending_submission'] = None
        self.data['last_reconciled_unsent'] = None
        self.save()
        self.event('message_submitted', request_id=request_id, ordinal=ordinal)

    def reconcile_submission(self, submitted: bool):
        pending = self.data['pending_submission']
        if not pending:
            return
        if submitted:
            # Persist the recapture state in the same snapshot as the newly
            # confirmed outbound record. A crash cannot strand it as ready.
            self.data['status'] = 'capture_failed'
            self.confirm_submission(pending['request_id'])
        else:
            receipt = {'request_id': pending['request_id'], 'ordinal': pending['ordinal'],
                       'text_hash': pending['text_hash']}
            self.data['last_reconciled_unsent'] = receipt
            self.event('submission_reconciled_not_sent', **receipt)
            self.data['pending_submission'] = None
            self.save()

    def begin_call(self, request: dict, state_changing: bool = True, reconciliation_baseline=None,
                   uncertainty_recovery: bool = False):
        call_id = request['call_id']
        if browser_inventory(request):
            state_changing = False
        from .web_privacy import private_id
        if uncertainty_recovery and request.get('name') not in {'browser.recover_uncertain', 'operation.quarantine'}:
            raise RuntimeError('Only the uncertainty recovery tool may bypass the pending-effect gate')
        if call_id in self.data['calls'] or private_id(call_id) in self.data['calls']:
            raise RuntimeError('Duplicate call ID cannot execute again')
        domains = operation_domains(request['name'])
        if (not browser_inventory(request) and any(
                c.get('status') == 'uncertain' and c.get('request', {}).get('name', '').startswith('rea.')
                for c in self.data['calls'].values())):
            raise RuntimeError('REA owned-process termination or cleanup remains uncertain; confirm cleanup before another operation')
        if (state_changing and not uncertainty_recovery
                and any(c['status'] == 'uncertain' and c.get('state_changing', True)
                        and ('global' in domains or 'global' in operation_domains(c['request']['name'])
                             or bool(domains & operation_domains(c['request']['name'])))
                        for c in self.data['calls'].values())):
            raise RuntimeError('A previous state-changing operation remains uncertain; inspect and reconcile before another change')
        action_hash = canonical_hash({k: request[k] for k in ('name', 'version', 'arguments')})
        if not browser_inventory(request) and any(c.get('action_hash') == action_hash and c['status'] in {'uncertain', 'abandoned_unverifiable'} for c in self.data['calls'].values()):
            raise RuntimeError('An identical action has uncertain effects; reconcile before requesting it again')
        self.data['calls'][call_id] = {'status': 'executing', 'request_hash': canonical_hash(request), 'action_hash': action_hash, 'state_changing': state_changing, 'request': request, 'started_at': now()}
        if browser_inventory(request):
            self.data['calls'][call_id]['browser_observation_only'] = True
        if reconciliation_baseline is not None:
            self.data['calls'][call_id]['reconciliation_baseline'] = deepcopy(reconciliation_baseline)
        self.event('tool_intent', call_id=call_id, name=request['name'], request_hash=canonical_hash(request))
        self.save()

    def quarantine_call(self, call_id: str):
        """Keep the unknown outcome in the audit while releasing its domain."""
        call = self.data['calls'].get(call_id)
        if call is None:
            from .web_privacy import private_id
            call_id = private_id(call_id)
            call = self.data['calls'].get(call_id)
        if call is None or call.get('status') != 'uncertain':
            raise ValueError('Choose one uncertain operation')
        domains = operation_domains(call.get('request', {}).get('name', ''))
        if not domains <= {'knowledge', 'filesystem'}:
            raise ValueError('This effect needs subsystem-specific verified recovery')
        previous, prior_status = deepcopy(call), self.data['status']
        call.update(status='abandoned_unverifiable', completion_credited=False,
                    outcome_determined=False, quarantined_at=now())
        if not any(item.get('status') == 'uncertain' for item in self.data['calls'].values()):
            self.data['status'] = 'ready'
        try:
            self.save()
        except Exception:
            self.data['calls'][call_id], self.data['status'] = previous, prior_status
            raise
        try:
            self.event('operation_quarantined', call_id=call_id, completion_credited=False,
                       outcome_determined=False)
        except OSError:
            pass  # The durable state is authoritative; event logging is secondary.
        return True

    def abandon_browser_uncertainty(self, call_id: str, proof: dict):
        """Quarantine an unknowable browser effect after a fresh approved checkpoint."""
        call = self.data['calls'].get(call_id)
        if call is None or call.get('status') != 'uncertain':
            raise ValueError('Only an uncertain browser operation may be abandoned')
        request = call.get('request', {})
        if (not str(request.get('name', '')).startswith('browser.')
                or (call.get('reconciliation_baseline') or {}).get('kind') == 'navigation_only'):
            raise ValueError('This recovery is only for uncertain non-navigation browser operations')
        if (type(proof) is not dict or proof.get('kind') != 'fresh_browser_checkpoint'
                or proof.get('session_id') != self.session_id
                or proof.get('call_id_sha256') != hashlib.sha256(call_id.encode()).hexdigest()
                or any(not isinstance(proof.get(key), str)
                       or not re.fullmatch(r'[a-f0-9]{64}', proof[key])
                       for key in ('checkpoint_url_sha256', 'checkpoint_title_sha256',
                                   'browser_binding_sha256'))):
            raise ValueError('A fresh verified browser checkpoint is required')
        previous, prior_status = deepcopy(call), self.data['status']
        call.update(status='abandoned_unverifiable', completion_credited=False,
                    outcome_determined=False, recovery=deepcopy(proof), quarantined_at=now())
        if not any(item.get('status') == 'uncertain' for item in self.data['calls'].values()):
            self.data['status'] = 'ready'
        try:
            self.save()
        except Exception:
            self.data['calls'][call_id] = previous
            self.data['status'] = prior_status
            raise
        self.event('browser_uncertainty_abandoned', call_id=call_id,
                   completion_credited=False, outcome_determined=False)
        return True

    def finish_call(self, call_id: str, result: dict):
        call = self.data['calls'][call_id]
        code = result.get('error', {}).get('code')
        evidence = result.get('result', {}) if isinstance(result.get('result'), dict) else {}
        explicitly_certain = evidence.get('side_effects_uncertain') is False
        uncertain = (call.get('state_changing', True) and not result.get('ok')
                     and code not in {'approval_denied', 'invalid_arguments'} and not explicitly_certain)
        if (call['request']['name'].startswith('rea.') and
                evidence.get('side_effects_uncertain') is True):
            uncertain = True  # Read-only targets can still leave an uncertain owned process.
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
            uncertain = call.get('state_changing', True) or call.get('request', {}).get('name', '').startswith('rea.')
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

    def quarantine_missing_navigation(self, call_id: str):
        call = self.data['calls'][call_id]
        if call.get('status') == 'unverifiable_original_tab_missing':
            return False
        if call.get('status') != 'uncertain' or (call.get('reconciliation_baseline') or {}).get('kind') != 'navigation_only':
            raise ValueError('Only retained navigation-only uncertainty can be quarantined')
        previous = deepcopy(call)
        call.update(status='unverifiable_original_tab_missing', completion_credited=False,
                    reconciliation_reason='original_owned_tab_missing', quarantined_at=now())
        try:
            self.save()
        except Exception:
            self.data['calls'][call_id] = previous
            raise
        self.event('navigation_quarantined', call_id=call_id, reason='original_owned_tab_missing', completion_credited=False)
        return True

    def reconcile_call(self, call_id: str, outcome: str, *, proof=None):
        call = self.data['calls'].get(call_id)
        if call is None or outcome not in {'completed', 'not_executed'}:
            raise ValueError('An uncertain call ID and completed/not_executed outcome are required')
        if call.get('reconciliation'):
            if call['reconciliation']['outcome'] == outcome:
                return False
            raise ValueError('The call was already reconciled with a different outcome')
        if call['status'] != 'uncertain':
            raise ValueError('Only an uncertain call may be reconciled')
        baseline = call.get('reconciliation_baseline') or {}
        if (type(proof) is dict and proof.get('kind') == 'fresh_knowledge_readback'
                and baseline.get('kind') == 'knowledge_save'):
            if (proof.get('outcome') != outcome or proof.get('session_id') != self.session_id
                    or proof.get('call_id_sha256') != hashlib.sha256(call_id.encode()).hexdigest()
                    or proof.get('namespace_id') != baseline.get('namespace_id')
                    or proof.get('record_sha256') != (baseline.get('before_sha256') if outcome == 'not_executed'
                                                       else proof.get('record_sha256'))
                    or (outcome == 'completed' and (
                        not re.fullmatch(r'[a-f0-9]{64}', proof.get('record_sha256', ''))
                        or any(proof.get(key) != baseline.get(key) for key in
                               ('payload_sha256', 'revision', 'approval_sha256',
                                'review_sha256', 'request_sha256'))))):
                raise ValueError('Fresh matching knowledge readback evidence is required')
        elif (type(proof) is not dict or proof.get('kind') != 'fresh_browser_observation'
                or proof.get('outcome') != outcome or proof.get('session_id') != self.session_id
                or proof.get('call_id_sha256') != hashlib.sha256(call_id.encode()).hexdigest()
                or (call.get('reconciliation_baseline') or {}).get('kind') != 'navigation_only'
                or any(not isinstance(proof.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', proof[key])
                       for key in ('observed_url_sha256', 'proposed_url_sha256', 'baseline_url_sha256'))
                or not (proof.get('observed_url_sha256') == proof.get('proposed_url_sha256')
                        or proof.get('proposal_query_free') is True and proof.get('proposed_url_sha256') == proof.get('observed_query_free_url_sha256'))
                or proof.get('baseline_url_sha256') != call.get('reconciliation_baseline', {}).get('url_sha256')):
            raise ValueError('Fresh matching reconciliation evidence is required')
        previous, prior_status = deepcopy(call), self.data['status']
        call.update(status=outcome, reconciliation=deepcopy(proof), reconciled_at=now())
        if not any(item['status'] == 'uncertain' for item in self.data['calls'].values()):
            self.data['status'] = 'ready'
        try:
            self.save()  # Atomic state replacement precedes the informational event.
        except Exception:
            self.data['calls'][call_id] = previous
            self.data['status'] = prior_status
            raise
        self.event('call_reconciled_from_fresh_evidence', call_id=call_id, outcome=outcome,
                   evidence_kind=proof['kind'])
        return True

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
            'unverified_lost_navigation': [{'operation_id_sha256': hashlib.sha256(key.encode()).hexdigest(),
                                           'state': 'unverifiable_original_tab_missing', 'completion_credited': False,
                                           'instruction': 'Open a fresh approved page and observe live before using facts from the lost tab.'}
                                          for key, call in self.data['calls'].items() if call['status'] == 'unverifiable_original_tab_missing'],
            'abandoned_browser_operations': [{'operation_id_sha256': hashlib.sha256(key.encode()).hexdigest(),
                                              'state': 'abandoned_unverifiable',
                                              'completion_credited': False, 'outcome_determined': False}
                                             for key, call in self.data['calls'].items()
                                             if call['status'] == 'abandoned_unverifiable'],
            'recent_messages': list(reversed(recent)), 'pending_operations': pending,
            'approval_state': self.data['approvals'], 'message_count': self.message_count,
            'attachments': self.data['attachments'], 'history_messages_retained_locally': len(self.data['messages'])}
