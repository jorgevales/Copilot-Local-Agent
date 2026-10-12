"""Bounded startup storage probe. Returned diagnostics never contain paths/data."""
from __future__ import annotations
import errno
import hashlib
import os
from pathlib import Path
import sqlite3
import uuid
from .site_knowledge import knowledge_directory
from .discovery_store import Store


def check_knowledge_health(context):
    result = dict(status='write_unavailable', readable=False, writable=False,
                  schema_compatible=False, artifact_writable=False, probe_cleanup=True, diagnostic='not_checked')
    probe = None
    stage = 'root'
    try:
        root = knowledge_directory(context).resolve()
        # Missing mapped/UNC anchors must never be mistaken for creatable roots.
        if root.anchor and not Path(root.anchor).exists():
            raise FileNotFoundError('storage anchor unavailable')
        root.mkdir(parents=True, exist_ok=True)
        with os.scandir(root) as entries:
            next(entries, None)
        result['readable'] = True
        stage = 'write'
        probe = root / ('.knowledge-health-' + uuid.uuid4().hex + '.tmp')
        payload = ('knowledge-health-v1:' + uuid.uuid4().hex).encode('ascii')
        with probe.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        stage = 'readback'
        if hashlib.sha256(probe.read_bytes()).digest() != hashlib.sha256(payload).digest():
            result.update(status='integrity_failure', diagnostic='probe_hash_mismatch')
        else:
            result['writable'] = True
            result['artifact_writable'] = True
            stage = 'schema'
            store = Store(context, persistent=True)
            try:
                if store.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise sqlite3.DatabaseError('integrity')
            finally:
                store.close()
            result.update(status='healthy', schema_compatible=True, diagnostic='verified')
    except Exception as exc:
        code = getattr(exc, 'code', '')
        if code in {'store_version', 'schema_incompatible'}:
            result.update(status='incompatible_store_version', diagnostic='store_version')
        elif isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, sqlite3.OperationalError):
            result.update(status='integrity_failure', diagnostic='database_integrity')
        elif isinstance(exc, (FileNotFoundError, NotADirectoryError)) or getattr(exc, 'winerror', None) in {53, 67, 64, 1231}:
            result.update(status='mapped_shared_unavailable', diagnostic='storage_unavailable')
        elif isinstance(exc, PermissionError) or getattr(exc, 'errno', None) in {errno.EACCES, errno.EROFS}:
            result.update(status='read_only' if result['readable'] else 'write_unavailable', diagnostic='permission_denied')
        elif isinstance(exc, sqlite3.OperationalError):
            result.update(status='write_unavailable', diagnostic='database_locked' if 'lock' in str(exc).lower() else 'database_unavailable')
        else:
            result.update(status='write_unavailable', diagnostic=stage + '_failed')
    finally:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
                if probe.exists():
                    raise OSError('cleanup incomplete')
            except OSError:
                result.update(status='write_unavailable', writable=False, artifact_writable=False,
                              probe_cleanup=False, diagnostic='probe_cleanup_failed')
    if result['status'] != 'healthy':
        result['writable'] = False
    result['fallback'] = ('verified_shared_store' if result['writable'] else
                          'verified_notes' if result['artifact_writable'] else 'session_findings')
    result['statement'] = ('Local knowledge storage: ' + result['status'].replace('_', '-') +
                           '. Local filesystem navigation: available under current user permissions and safety controls. ' +
                           ('Use the configured shared store for durable findings.' if result['writable'] else
                            'Use knowledge.note and knowledge.lookup for verified Discoveries artifacts; the central index is unavailable.' if result['artifact_writable'] else
                            'Retain findings in session evidence; avoid repeated storage attempts until repaired.'))
    return result
