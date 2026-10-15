"""Immutable, verified Discoveries artifacts independent of site schemas."""
import hashlib
import json
import os
import re
import uuid
from .site_knowledge import knowledge_directory
from .policy import PolicyError
from .knowledge_views import reusable_value, site_folder


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode('utf-8')


def execute_note(name, args, context):
    context['knowledge_note_started'] = False
    root = knowledge_directory(context)
    folder = root / 'notes'
    try:
        from .site_knowledge import _current_origin, _scope, _hash
        selected_origin = _current_origin(context)
        folder = site_folder(context, selected_origin)
        try:
            scope = _scope('site_knowledge.retrieve', {'origin': selected_origin}, context)
            folder = folder / 'namespaces' / _hash(scope)
        except PolicyError:
            # A generic note can precede an explicit app/tenant binding. Keep
            # it inside the website's central folder instead of a global file.
            folder = folder / 'unbound'
        folder = folder / 'notes'
    except PolicyError:
        pass  # Non-website operational knowledge retains its existing folder.
    if name == 'knowledge.lookup':
        identifier = args.get('note_id')
        if not identifier:
            from itertools import islice
            paths = list(islice(folder.glob('*.json'), 101)) if folder.exists() else []
            return {'status': 'available', 'note_ids': [p.stem for p in paths[:100]],
                    'truncated': len(paths) > 100, 'instruction': 'Use knowledge.lookup with a note_id to read verified knowledge.'}
        if not re.fullmatch('[a-f0-9]{64}', identifier):
            raise ValueError('Use a returned note identifier')
        target = folder / (identifier + '.json')
        if not target.is_file():
            target = root / 'notes' / (identifier + '.json')  # Existing operational notes.
        data = target.read_bytes()
        if len(data) > 65536 or hashlib.sha256(data).hexdigest() != identifier:
            raise ValueError('Knowledge artifact integrity failure')
        return {'status': 'verified', 'note_id': identifier, 'knowledge': json.loads(data)}
    if context.get('approved') is not True:
        raise PolicyError('Local knowledge saving requires run confirmation')
    config = context.get('config')
    capability = getattr(config, '_knowledge_capability', None)
    if capability and not capability.get('artifact_writable', capability.get('writable', False)):
        from .site_knowledge import KnowledgeStorageError
        raise KnowledgeStorageError('write_unavailable')
    value = reusable_value({'schema_version': 1, 'title': args['title'], 'content': args['content']})
    if not value['title'] or not value['content']:
        return {'status': 'skipped_empty', 'verified': False, 'knowledge_saved': False}
    data = _bytes(value)
    if len(data) > 65536:
        raise ValueError('Knowledge note exceeds the bounded artifact size')
    identifier = hashlib.sha256(data).hexdigest()
    duplicate = False
    # A changed title or whitespace alone must not create another note for the
    # same reusable instruction. Bound legacy scanning; immutable artifacts are
    # still checked by their exact byte hash before reuse.
    signature = re.sub(r'\s+', ' ', value['content']).strip().casefold()
    signature_namespace = hashlib.sha256(('note-content:' + str(folder.relative_to(root)) + ':' + signature).encode()).hexdigest()
    indexed_candidate = None
    try:
        from .discovery_store import Store
        store = Store(context, persistent=True, readonly=True, allow_missing=True)
        try:
            pointer = store.site_knowledge(signature_namespace)
        finally:
            store.close()
        if pointer and re.fullmatch('[a-f0-9]{64}', pointer.get('note_id', '')):
            indexed_candidate = folder / (pointer['note_id'] + '.json')
    except Exception:
        pass  # Preserve legacy verified artifact recovery if its index is unavailable.
    from itertools import islice
    from itertools import chain
    candidates = chain([indexed_candidate] if indexed_candidate is not None else (),
                       islice(folder.glob('*.json'), 200) if folder.exists() else ())
    for candidate in candidates:
        try:
            retained_data = candidate.read_bytes()
            if len(retained_data) > 65536 or hashlib.sha256(retained_data).hexdigest() != candidate.stem:
                continue
            retained = json.loads(retained_data)
            if re.sub(r'\s+', ' ', retained.get('content', '')).strip().casefold() == signature:
                value, data, identifier, duplicate = retained, retained_data, candidate.stem, True
                break
        except (OSError, ValueError, TypeError):
            continue
    target = folder / (identifier + '.json')
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError('Existing knowledge artifact integrity failure; preserve evidence and use a different note')
    else:
        last_error = None
        for attempt in range(1, 4):
            callback = context.get('storage_attempt_notice')
            if callable(callback):
                callback(attempt, 3, folder)
            temporary = folder / ('.note-' + uuid.uuid4().hex + '.tmp')
            try:
                folder.mkdir(parents=True, exist_ok=True)
                with temporary.open('xb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                context['knowledge_note_started'] = True
                break
            except OSError as error:
                last_error = error
                # A share can report a late error after committing the atomic
                # rename. Read back before retrying to avoid duplicate effects.
                if target.is_file():
                    if target.read_bytes() == data:
                        context['knowledge_note_started'] = True
                        break
                    raise ValueError('Knowledge artifact target changed during a failed write; preserve evidence') from error
                if attempt == 3:
                    raise
            finally:
                temporary.unlink(missing_ok=True)
        if not target.is_file() and last_error is not None:
            raise last_error
    if target.read_bytes() != data:
        raise ValueError('Knowledge artifact readback integrity failure')
    # The immutable artifact remains discoverable if an incompatible/locked
    # central ledger cannot index it. Never pretend that indexing succeeded.
    indexed = False
    diagnostic = None
    try:
        from .discovery_store import Store
        store = Store(context, persistent=True)
        try:
            namespace = hashlib.sha256(('note:' + identifier).encode()).hexdigest()
            record = dict(value, revision=1, note_id=identifier)
            current = store.site_knowledge(namespace)
            if current is None:
                store.save_site_knowledge(namespace, 0, record)
            indexed = store.site_knowledge(namespace) == record
            if store.site_knowledge(signature_namespace) is None:
                store.save_site_knowledge(signature_namespace, 0, {'revision': 1, 'note_id': identifier})
        finally:
            store.close()
    except Exception as error:
        diagnostic = getattr(error, 'code', 'index_unavailable')
    return {'status': 'unchanged' if duplicate else 'saved', 'verified': True, 'note_id': identifier,
            'storage': 'configured_discoveries', 'indexed': indexed,
            'index_diagnostic': diagnostic, 'readback_tool': 'knowledge.lookup', 'directory': str(folder)}
