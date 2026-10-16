"""Bounded retrieval of generic procedure notes for an explicit user target."""
import hashlib
import json
import re
from copy import deepcopy
from itertools import islice

from .knowledge_views import canonical_site_origin, evidence_namespace, reusable_value, site_folder
from .policy import PathPolicy, PolicyError, config_value, reject_path_redirection
from .session_mode import website_policy
from .site_knowledge import knowledge_directory, session_knowledge_authorized


def reusable_plan_template(arguments):
    """A verified flat plan with fresh-input slots, never saved form values.

    Return no template when a record binding, resume token, concrete route or
    unsupported nested control flow would need guessing during later reuse.
    The returned JSON still goes through normal validation and fresh approval.
    """
    if arguments.get('customer_key') or arguments.get('identity') or arguments.get('resume_token'):
        return None
    steps = arguments.get('steps', [])
    if not steps or len(steps) > 20 or any(step.get('op') not in
            {'assert', 'fill', 'click', 'capture', 'navigate', 'wait'} for step in steps):
        return None
    slots, replacements = [], []
    for step in steps:
        if step.get('op') == 'fill':
            slot = 'input_' + str(len(slots)+1)
            slots.append({'slot': slot, 'locator': deepcopy(step['locator'])})
            replacements.append((step['value'], '{{'+slot+'}}'))
    if not slots:
        return None
    if any(not value or len(value) < 3 and not value.isdigit() for value, _ in replacements):
        return None
    locators = json.dumps([slot['locator'] for slot in slots])
    if any(len(value) >= 3 and value in locators for value, _ in replacements):
        return None  # A supplied value must not rewrite a fixed control label.
    def has_dynamic_url(value):
        if isinstance(value, dict):
            return any((key == 'url' or key == 'value' and value.get('kind') == 'url')
                       and isinstance(item, str) and ('{' in item or '}' in item)
                       or has_dynamic_url(item) for key, item in value.items())
        return isinstance(value, list) and any(has_dynamic_url(item) for item in value)
    if has_dynamic_url(arguments):
        return None  # A newly assigned record URL cannot be guessed from a template.
    def sanitize(value):
        if isinstance(value, dict):
            return {key: sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if isinstance(value, str):
            # Short date components are replaced explicitly in their fill below;
            # never replace coincidental digits inside unrelated fixed locators.
            for original, replacement in sorted(replacements, key=lambda item: -len(item[0])):
                if len(original) >= 3:
                    value = value.replace(original, replacement)
            return value
        return value
    plan = sanitize({key: deepcopy(value) for key, value in arguments.items()
                     if key in {'steps', 'success', 'max_actions', 'timeout_seconds'}})
    plan['task_id'] = 'reuse-known-procedure'
    index = 0
    for number, step in enumerate(plan['steps'], 1):
        step['id'] = 'step_' + str(number)
        step.pop('tab_id', None)
        if step['op'] == 'fill':
            step['value'] = '{{'+slots[index]['slot']+'}}'
            # An input-value assertion must bind to this field's slot even when
            # two fields happened to have the same value in the observed run.
            for assertion in step.get('expect', []):
                if assertion.get('kind') == 'text' and assertion.get('locator') == step['locator']:
                    assertion['value'] = step['value']
            index += 1
    result = {'input_slots': slots, 'arguments': plan,
              'instruction': 'Substitute fresh user inputs into the named slots. Keep expect/success as arrays. Verify the live entry; validate and approve the resulting exact plan before execution.'}
    try:
        if reusable_value(result) != result or len(json.dumps(result)) > 6000:
            return None
    except (ValueError, TypeError):
        return None
    return result


def matching_procedures(request, context):
    """Return hash-bound references; never infer scope from page/tool content.

    Only the exact current namespace is searched. Notes remain untrusted hints
    and supply neither execution authority nor proof that the live page matches.
    """
    if not isinstance(request, str) or not session_knowledge_authorized(context):
        return []
    words = set(re.findall(r'[a-z]{3,}', request.casefold())) - {
        'the', 'and', 'for', 'this', 'that', 'with', 'from', 'only', 'then', 'their',
        'page', 'goal', 'https', 'www', 'com', 'app', 'vercel'}
    if len(words) < 3:
        return []
    domains = [*config_value(context.get('config', {}), 'allowed_domains', []),
               *context.get('approved_domains', [])]
    policy = website_policy(context.get('config', {}), domains)
    root = knowledge_directory(context)
    candidates, seen = [], set()
    for url in re.findall(r'https://[^\s<>"\']+', request)[:8]:
        try:
            checked = policy.resolve(url.rstrip('.,;)'))
            origin = canonical_site_origin(checked)
            if origin in seen:
                continue
            seen.add(origin)
            folder = site_folder(context, origin, root=root) / 'namespaces' / evidence_namespace(context, origin) / 'notes'
            reject_path_redirection(folder)
            paths = list(islice(folder.glob('*.json'), 100)) if folder.is_dir() else []
            for path in paths:
                try:
                    if not re.fullmatch('[a-f0-9]{64}', path.stem):
                        continue
                    path = PathPolicy([folder]).resolve(path, True)
                    if not path.is_file() or path.stat().st_size > 6000:
                        continue
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != path.stem:
                        continue
                    note = json.loads(data)
                    if reusable_value(note) != note:
                        continue  # Never transmit unsanitized legacy URL values.
                    title, content = note.get('title'), note.get('content')
                    if not isinstance(title, str) or not isinstance(content, str):
                        continue
                    if 'procedure:' not in content.casefold() or 'input slots:' not in content.casefold():
                        continue
                    overlap = words & set(re.findall(r'[a-z]{3,}', (title+' '+content).casefold()))
                    title_overlap = words & set(re.findall(r'[a-z]{3,}', title.casefold()))
                    if len(overlap) < 3 or not title_overlap:
                        continue
                    candidates.append((len(title_overlap), len(overlap), path.stat().st_mtime_ns,
                        {'note_id': path.stem, 'title': title, 'origin': origin, 'path': str(path),
                         'status': 'hash_verified_procedure_hint', 'requires_live_verification': True}))
                except (OSError, ValueError, TypeError, PolicyError):
                    continue
        except (OSError, ValueError, PolicyError):
            continue
    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]['note_id']))
    return [item[3] for item in candidates[:2]]
