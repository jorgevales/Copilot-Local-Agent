"""Strict JSON envelope parser and validator for the published schema vocabulary."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re

BEGIN = '<<<COPILOT_AGENT_V1_BEGIN>>>'
END = '<<<COPILOT_AGENT_V1_END>>>'
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'schemas' / 'response-v1.schema.json').read_text(encoding='utf-8'))


class ProtocolError(ValueError):
    def __init__(self, code: str, errors: list[str]):
        self.code, self.errors = code, errors
        super().__init__(code + ': ' + '; '.join(errors))


def validate_schema(value, schema: dict, root=None, path='$') -> list[str]:
    """Validate the explicit vocabulary used in our schemas, never silently ignore keywords."""
    root = root or schema
    if '$ref' in schema:
        target = root
        for part in schema['$ref'].removeprefix('#/').split('/'):
            target = target[part.replace('~1', '/').replace('~0', '~')]
        return validate_schema(value, target, root, path)
    supported = {'$schema', '$id', '$defs', 'title', 'description', 'type', 'const', 'enum', 'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'uniqueItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'pattern', 'anyOf', 'oneOf', 'default', 'examples'}
    unknown = set(schema) - supported
    if unknown:
        return [path + ': unsupported schema keywords ' + ', '.join(sorted(unknown))]
    if 'anyOf' in schema and not any(not validate_schema(value, sub, root, path) for sub in schema['anyOf']):
        return [path + ': matches no allowed schema']
    if 'oneOf' in schema and sum(not validate_schema(value, sub, root, path) for sub in schema['oneOf']) != 1:
        return [path + ': must match exactly one schema']
    errors = []
    if 'const' in schema and (value != schema['const'] or type(value) != type(schema['const'])):
        errors.append(path + ': wrong constant')
    if 'enum' in schema and not any(value == option and type(value) == type(option) for option in schema['enum']):
        errors.append(path + ': unsupported value')
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    checks = {'object': lambda v: type(v) is dict, 'array': lambda v: type(v) is list,
              'string': lambda v: type(v) is str, 'boolean': lambda v: type(v) is bool,
              'integer': lambda v: type(v) is int,
              'number': lambda v: type(v) in (int, float) and math.isfinite(v), 'null': lambda v: v is None}
    if types and not any(checks[t](value) for t in types):
        return errors + [path + ': expected ' + '|'.join(types)]
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                errors.append(path + '.' + key + ': required')
        for key, child in value.items():
            if key in props:
                errors.extend(validate_schema(child, props[key], root, path + '.' + key))
            elif schema.get('additionalProperties') is False:
                errors.append(path + '.' + key + ': unknown field')
            elif isinstance(schema.get('additionalProperties'), dict):
                errors.extend(validate_schema(child, schema['additionalProperties'], root, path + '.' + key))
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')):
            errors.append(path + ': invalid item count')
        if schema.get('uniqueItems') and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            errors.append(path + ': duplicate items')
        if 'items' in schema:
            for i, child in enumerate(value):
                errors.extend(validate_schema(child, schema['items'], root, f'{path}[{i}]'))
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', float('inf')):
            errors.append(path + ': invalid string length')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            errors.append(path + ': invalid string pattern')
    if type(value) in (int, float):
        if not math.isfinite(value) or value < schema.get('minimum', -float('inf')) or value > schema.get('maximum', float('inf')):
            errors.append(path + ': number outside allowed range')
    return errors


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError('invalid_json', ['Duplicate JSON key: ' + key])
        result[key] = value
    return result


def parse_response(raw: str, session_id: str, request_id: str, registry=None, seen_response_ids=()) -> dict:
    if len(raw) > 100000:
        raise ProtocolError('truncated_output', ['Response exceeds configured protocol limit'])
    if raw.count(BEGIN) != 1 or raw.count(END) != 1:
        raise ProtocolError('missing_envelope', ['Expected one unique complete marker pair'])
    start, end = raw.index(BEGIN) + len(BEGIN), raw.index(END)
    if end < start:
        raise ProtocolError('missing_envelope', ['Envelope markers are reversed'])
    payload = raw[start:end].strip()
    # A single complete fenced JSON payload can be extracted without changing its meaning.
    if payload.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', payload, flags=re.DOTALL)
        if match:
            payload = match.group(1)
    try:
        obj = json.loads(payload, object_pairs_hook=_object_pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))
    except ProtocolError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ProtocolError('invalid_json', [str(exc)]) from exc
    errors = validate_schema(obj, SCHEMA)
    if errors:
        code = 'wrong_schema_version' if isinstance(obj, dict) and obj.get('protocol_version') != '1.0' else 'missing_required_fields'
        raise ProtocolError(code, errors[:30])
    if obj['session_id'] != session_id or obj['request_id'] != request_id:
        raise ProtocolError('stale_response', ['Response identity does not match current request'])
    if obj['response_id'] in seen_response_ids:
        raise ProtocolError('stale_response', ['Response identifier has already been processed'])
    errors = []
    tools = obj['tool_requests']
    if obj['tools_required'] != bool(tools):
        errors.append('tools_required must match tool_requests')
    ids = [t['call_id'] for t in tools]
    if len(set(ids)) != len(ids):
        errors.append('Tool call IDs must be unique')
    steps = [s['step'] for s in obj['action_plan']]
    if steps != list(range(1, len(steps) + 1)):
        errors.append('Plan steps must be ordered and numbered consecutively from 1')
    kind = obj['response_type']
    if kind == 'final' and (tools or obj['continuation_state'] != 'complete' or obj['completion_status'] != 'complete' or obj['clarification'] is not None):
        errors.append('Final response must be complete and contain no tool calls or clarification')
    if kind == 'tool_request' and (not tools or obj['continuation_state'] != 'continue' or obj['completion_status'] != 'in_progress' or obj['clarification'] is not None):
        errors.append('Tool request must contain calls and remain in progress')
    if kind == 'clarification' and (tools or not obj['clarification'] or obj['continuation_state'] != 'await_user' or obj['completion_status'] != 'in_progress'):
        errors.append('Clarification must await user without executing tools')
    if kind == 'error' and (tools or obj['completion_status'] != 'blocked' or obj['continuation_state'] != 'blocked' or not obj['recoverable_errors']):
        errors.append('Error response must be blocked with error details and no tool calls')
    runner_calls = [t for t in tools if t['name'] == 'code_runner']
    if obj['code_runner_proposal'] is not None and not runner_calls:
        errors.append('Code proposal requires a code_runner tool request')
    if errors:
        raise ProtocolError('contradictory_execution_state', errors)
    if registry:
        catalog = {d['name']: d for d in registry.definitions()}
        for call in tools:
            definition = catalog.get(call['name'])
            if not definition or call['version'] != definition['version']:
                raise ProtocolError('unsupported_tool', ['Unsupported tool/version: ' + call['name']])
            errors = validate_schema(call['arguments'], definition['input_schema'])
            if errors:
                raise ProtocolError('unsafe_tool_arguments', errors[:20])
    return obj


def correction_message(exc: ProtocolError) -> str:
    return json.dumps({'kind': 'protocol_correction', 'failure': exc.code, 'validation_errors': exc.errors,
                       'instruction': 'Reissue the same decision for the CURRENT request_id, without executing or changing scope. Use the attached exact response schema, required fields and one marker pair. Put valid JSON in a fenced json code block BETWEEN the markers; escape backslashes in Windows paths or use forward slashes. Preserve script quotes and exact arguments. Findings may be proposed on any turn.',
                       'required_fields': SCHEMA['required'], 'markers': [BEGIN, END]}, ensure_ascii=False)
