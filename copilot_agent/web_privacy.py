"""Keep website task content in memory; persist only operational audit evidence."""
from __future__ import annotations

import hashlib
import json
import re

PRIVATE_TOOLS = {
    'browser.recon', 'browser.plan', 'browser.tabs', 'browser.customer_summary',
    'browser.route', 'browser.documents', 'browser.download_batch',
    'files.transfer_to_copilot',
    'documents.catalogue', 'documents.find', 'documents.retrieve',
}
ERROR_CODES = frozenset({
    'invalid_arguments', 'policy_denied', 'approval_denied', 'unavailable', 'operation_failed',
    'timeout', 'tool_error', 'cancelled', 'interrupted', 'blocked', 'uncertain', 'partial',
    'invalid_json', 'authentication_required', 'human_verification', 'access_denied',
    'rate_limited', 'server_error', 'verification_failed', 'locator_unavailable',
    'control_disabled', 'confirmation_required', 'explicit_tab_required', 'time_limit',
    'action_limit', 'loop_limit', 'unsafe_filename', 'stale_source', 'unsupported_link',
    'link_unavailable', 'settings_unavailable', 'ticket_limit', 'download_failed',
    'hash_mismatch', 'size_limit', 'delivery_unverified',
})


def private_id(value):
    """Stable opaque alias for untrusted LLM correlation labels, safe on re-save."""
    if type(value) is str and re.fullmatch(r'id-sha256:[a-f0-9]{64}', value):
        return value
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
    return 'id-sha256:' + hashlib.sha256(encoded).hexdigest()


def audit_evidence(value):
    """Hash exact evidence without copying customer text, URLs or identifiers."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
    result = {'content_sha256': hashlib.sha256(encoded).hexdigest(), 'content_bytes': len(encoded),
              'website_content_omitted': True}
    if isinstance(value, dict):
        for key in ('ok', 'side_effects_uncertain', 'truncated'):
            if type(value.get(key)) is bool:
                result[key] = value[key]
        if type(value.get('tool')) is str and value['tool'] in PRIVATE_TOOLS:
            result['tool'] = value['tool']
        error = value.get('error')
        if isinstance(error, dict):
            # Categories come from local execution, never retain free-form messages.
            code = error.get('code')
            result['error'] = {'code': code if type(code) is str and code in ERROR_CODES else 'operation_failed'}
    return result


def _snapshot_evidence(value):
    """Preserve only strict existing audit records when a private session resumes."""
    required = {'content_sha256', 'content_bytes', 'website_content_omitted'}
    allowed = required | {'ok', 'side_effects_uncertain', 'truncated', 'tool', 'error'}
    if (type(value) is dict and required <= set(value) <= allowed
            and type(value['content_sha256']) is str
            and re.fullmatch(r'[a-f0-9]{64}', value['content_sha256'])
            and type(value['content_bytes']) is int and 0 <= value['content_bytes'] <= 2**63 - 1
            and value['website_content_omitted'] is True
            and all(type(value[key]) is bool for key in ('ok', 'side_effects_uncertain', 'truncated') if key in value)
            and ('tool' not in value or type(value['tool']) is str and value['tool'] in PRIVATE_TOOLS)
            and ('error' not in value or type(value['error']) is dict and set(value['error']) == {'code'}
                 and type(value['error']['code']) is str and value['error']['code'] in ERROR_CODES)):
        result = dict(value)
        if 'error' in result:
            result['error'] = dict(result['error'])
        return result
    return audit_evidence(value)


def private_session_snapshot(data):
    snapshot = dict(data)
    snapshot['messages'] = [dict(item, content=_snapshot_evidence(item.get('content')))
                            for item in data.get('messages', [])]
    snapshot['calls'] = {}
    for key, call in data.get('calls', {}).items():
        record = dict(call)
        request = call.get('request', {})
        record['request'] = {field: request.get(field) for field in ('name', 'version')}
        record['request']['call_id'] = private_id(key)
        record['request']['arguments'] = _snapshot_evidence(request.get('arguments'))
        if 'result' in call:
            record['result'] = _snapshot_evidence(call['result'])
        snapshot['calls'][private_id(key)] = record
    snapshot['response_ids'] = [private_id(value) for value in data.get('response_ids', [])]
    for key in ('current_plan', 'summary', 'requirements', 'decisions', 'constraints',
                'unresolved_questions'):
        snapshot[key] = '' if key == 'summary' else []
    for key in ('attachments', 'findings_sync', 'retry_records'):
        snapshot[key] = [_snapshot_evidence(item) for item in data.get(key, [])]
    return snapshot
