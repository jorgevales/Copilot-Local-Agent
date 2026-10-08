"""Versioned local SQLite ledger; no synced session/customer data or auth state."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .discovery_contracts import DiscoveryError, canonical
from .policy import PathPolicy, reject_path_redirection
from .site_knowledge import knowledge_directory

TERMINAL = frozenset({'SUCCEEDED', 'PARTIALLY_SUCCEEDED', 'FAILED', 'SKIPPED', 'CANCELLED'})
TRANSITIONS = {
    'PENDING': {'READY', 'SKIPPED', 'CANCELLED'},
    'READY': {'RUNNING', 'SKIPPED', 'CANCELLED'},
    'RUNNING': {'SUCCEEDED', 'PARTIALLY_SUCCEEDED', 'FAILED', 'RETRY_DELAY', 'CANCELLED'},
    'RETRY_DELAY': {'READY', 'FAILED', 'CANCELLED'},
}
MAX_DATABASE_BYTES = 32 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def alias(value):
    return 't' + digest(value)[:32]


def directory(context):
    selected = knowledge_directory(context) / 'discovery-v1'
    reject_path_redirection(selected)
    for key in ('storage_dir', 'root'):
        config = context.get('config', {})
        value = config.get(key) if type(config) is dict else getattr(config, key, None)
        if value and selected.is_relative_to(Path(value).expanduser().absolute()):
            raise DiscoveryError('synced_store_unavailable', '$', 'Discovery transactional storage must remain outside project and selected OneDrive storage')
    for key in ('OneDrive', 'OneDriveCommercial', 'OneDriveConsumer'):
        if os.environ.get(key) and selected.is_relative_to(Path(os.environ[key]).expanduser().absolute()):
            raise DiscoveryError('synced_store_unavailable')
    return selected


class Store:
    def __init__(self, context, persistent=False, readonly=False):
        try:
            import sqlite3
        except ImportError as error:
            raise DiscoveryError('store_unavailable', '$', 'The existing Python lacks its optional stdlib SQLite support; new-path storage is unavailable') from error
        self.lock = threading.RLock()
        self.folder = directory(context) if persistent else None
        self.context = context
        if self.folder:
            if not readonly:
                self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = PathPolicy([self.folder]).resolve('ledger.sqlite3')
            if readonly and not path.is_file():
                raise DiscoveryError('persistent_evidence_required')
            for suffix in ('', '-wal', '-shm', '-journal'):
                reject_path_redirection(Path(str(path) + suffix))
            if path.exists() and path.stat().st_size > MAX_DATABASE_BYTES:
                raise DiscoveryError('resource_limit')
            target = path.as_uri() + '?mode=ro' if readonly else str(path)
            self.db = sqlite3.connect(target, timeout=2, isolation_level=None, check_same_thread=False, uri=readonly)
        else:
            self.db = sqlite3.connect(':memory:', isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if readonly:
            if self.db.execute('PRAGMA user_version').fetchone()[0] != 1:
                self.db.close()
                raise DiscoveryError('store_version')
            return
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA trusted_schema=OFF')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA max_page_count=8192')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise DiscoveryError('store_version')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(
          id TEXT PRIMARY KEY, partition TEXT NOT NULL, digest TEXT NOT NULL,
          request TEXT NOT NULL, started REAL NOT NULL, deadline REAL NOT NULL,
          last_clock REAL NOT NULL, state TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
          counters TEXT NOT NULL, result TEXT, revision INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS tasks(
          run TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL, branch TEXT NOT NULL,
          state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, fence INTEGER NOT NULL DEFAULT 0,
          revision INTEGER NOT NULL DEFAULT 1, first_lease REAL, deadline REAL, owner TEXT,
          lease_until REAL, reason TEXT NOT NULL DEFAULT 'pending', output TEXT,
          PRIMARY KEY(run,id));
        CREATE TABLE IF NOT EXISTS evidence(
          run TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL, task TEXT NOT NULL,
          metadata TEXT NOT NULL, artifact TEXT NOT NULL, hash TEXT NOT NULL,
          expires REAL NOT NULL, PRIMARY KEY(run,id));
        CREATE TABLE IF NOT EXISTS urls(
          run TEXT NOT NULL REFERENCES runs(id), key TEXT NOT NULL, url TEXT NOT NULL,
          state TEXT NOT NULL, depth INTEGER NOT NULL, provenance TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0, first_lease REAL, deadline REAL,
          PRIMARY KEY(run,key));
        CREATE TABLE IF NOT EXISTS origins(
          run TEXT NOT NULL REFERENCES runs(id), origin TEXT NOT NULL, next_request REAL NOT NULL DEFAULT 0,
          cooldown REAL NOT NULL DEFAULT 0, rate REAL NOT NULL, cap INTEGER NOT NULL,
          PRIMARY KEY(run,origin));
        CREATE TABLE IF NOT EXISTS knowledge_heads(partition TEXT PRIMARY KEY, revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS knowledge(
          partition TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
          hash TEXT NOT NULL, consent TEXT NOT NULL, created REAL NOT NULL, invalidated INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(partition,revision));
        PRAGMA user_version=1;
        ''')
        self.purge_expired()

    def purge_expired(self):
        now = time.time()
        with self.transaction() as db:
            expired = {row[0] for row in db.execute('SELECT id FROM evidence WHERE expires<=?', (now,))}
            for row in db.execute('SELECT partition,revision,payload,created FROM knowledge').fetchall():
                try:
                    value = json.loads(row['payload'])
                    last = datetime.fromisoformat(value['last_verified'].replace('Z', '+00:00')).timestamp()
                    ttl = min(30 * 86400, value['revalidation']['ttl_seconds'])
                    refs = {e['id'] for e in value['evidence']}
                except (ValueError, KeyError, TypeError):
                    db.execute('UPDATE knowledge SET invalidated=1 WHERE partition=?', (row['partition'],))
                    continue
                if now >= min(last + ttl, row['created'] + 30 * 86400):
                    db.execute('UPDATE knowledge SET invalidated=1 WHERE partition=?', (row['partition'],))
                    db.execute('DELETE FROM knowledge WHERE partition=? AND revision=?', (row['partition'], row['revision']))
                elif refs & expired:
                    db.execute('UPDATE knowledge SET invalidated=1 WHERE partition=?', (row['partition'],))
            db.execute('DELETE FROM evidence WHERE expires<=?', (now,))
            old = [row[0] for row in db.execute('SELECT id FROM runs WHERE started<? AND deadline<?', (now - 14 * 86400, now))]
            for run in old:
                for table in ('evidence', 'tasks', 'urls', 'origins'):
                    db.execute('DELETE FROM ' + table + ' WHERE run=?', (run,))
                db.execute('DELETE FROM runs WHERE id=?', (run,))

    def _check(self):
        if self.folder:
            reject_path_redirection(self.folder)
            path = PathPolicy([self.folder]).resolve('ledger.sqlite3', True)
            for suffix in ('-journal', '-wal', '-shm'):
                reject_path_redirection(Path(str(path) + suffix))
            if path.stat().st_size > MAX_DATABASE_BYTES:
                raise DiscoveryError('resource_limit')

    @contextmanager
    def transaction(self):
        with self.lock:
            self._check()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def create_run(self, run, graph, partition, owner, now=None):
        now = time.time() if now is None else now
        m = graph.manifest
        counters = dict(requests=0, bytes=0, bytes_reserved=0, pages=0, attempts=0, retries=0, backoff_seconds=0,
                        duplicates_avoided=0, suppressed=0, tasks=len(m['tasks']))
        with self.transaction() as db:
            db.execute('INSERT INTO runs(id,partition,digest,request,started,deadline,last_clock,state,counters) VALUES(?,?,?,?,?,?,?,?,?)',
                       (run, partition, graph.digest, m['request_id'], now, now + m['budgets']['run_seconds'], now, 'EXECUTING', canonical(counters)))
            for t in m['tasks']:
                db.execute('INSERT INTO tasks(run,id,branch,state,owner) VALUES(?,?,?,?,?)',
                           (run, alias(t['id']), alias(t['branch']), 'PENDING', owner))
            for o in m['scope']['origins']:
                from .discovery_scope import origin
                db.execute('INSERT INTO origins(run,origin,rate,cap) VALUES(?,?,?,?)',
                           (run, origin(o), m['budgets']['per_origin_rps'], m['budgets']['per_origin_concurrency']))
        return counters

    def counters(self, run):
        with self.lock:
            return json.loads(self.db.execute('SELECT counters FROM runs WHERE id=?', (run,)).fetchone()[0])

    def run(self, run):
        with self.lock:
            row = self.db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
            if row is None:
                raise DiscoveryError('run_unavailable')
            return dict(row)

    def reserve(self, run, key, amount, ceiling, generation=0):
        now = time.time()
        with self.transaction() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
            if row['state'] != 'EXECUTING' or row['generation'] != generation:
                raise DiscoveryError('cancelled')
            if now < row['last_clock'] - 1 or now >= row['deadline'] - 1:
                raise DiscoveryError('runtime_limit')
            values = json.loads(row['counters'])
            if values[key] + amount > ceiling:
                raise DiscoveryError('page_limit' if key == 'pages' else 'resource_limit')
            values[key] += amount
            db.execute('UPDATE runs SET counters=?,last_clock=? WHERE id=?', (canonical(values), max(now, row['last_clock']), run))
            return values[key]

    def reserve_bytes(self, run, requested, ceiling):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
            if row['state'] != 'EXECUTING' or row['generation']:
                raise DiscoveryError('cancelled')
            values = json.loads(row['counters'])
            available = ceiling - values['bytes'] - values['bytes_reserved']
            if available <= 0:
                raise DiscoveryError('resource_limit')
            granted = min(requested, available)
            values['bytes_reserved'] += granted
            db.execute('UPDATE runs SET counters=? WHERE id=?', (canonical(values), run))
            return granted

    def settle_bytes(self, run, granted, received):
        with self.transaction() as db:
            row = db.execute('SELECT counters FROM runs WHERE id=?', (run,)).fetchone()
            values = json.loads(row[0])
            if not 0 <= received <= granted or values['bytes_reserved'] < granted:
                raise DiscoveryError('resource_limit')
            values['bytes_reserved'] -= granted
            values['bytes'] += received
            db.execute('UPDATE runs SET counters=? WHERE id=?', (canonical(values), run))

    def task(self, run, task):
        with self.lock:
            return dict(self.db.execute('SELECT * FROM tasks WHERE run=? AND id=?', (run, alias(task))).fetchone())

    def transition(self, run, task, state, reason, expected=None):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM tasks WHERE run=? AND id=?', (run, alias(task))).fetchone()
            if row['state'] in TERMINAL or expected is not None and row['revision'] != expected:
                raise DiscoveryError('stale_task_revision')
            if state not in TRANSITIONS.get(row['state'], set()):
                raise DiscoveryError('invalid_transition')
            db.execute('UPDATE tasks SET state=?,reason=?,revision=revision+1 WHERE run=? AND id=?',
                       (state, reason, run, alias(task)))

    def lease(self, run, task, owner, timeout, branch_timeout):
        now = time.time()
        with self.transaction() as db:
            r = db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
            row = db.execute('SELECT * FROM tasks WHERE run=? AND id=?', (run, alias(task))).fetchone()
            if r['state'] != 'EXECUTING' or r['generation'] or row['state'] != 'READY':
                raise DiscoveryError('stale_lease')
            if now < r['last_clock'] - 1:
                raise DiscoveryError('clock_anomaly')
            first = row['first_lease'] or now
            branch = db.execute('SELECT MIN(first_lease) FROM tasks WHERE run=? AND branch=?', (run, row['branch'])).fetchone()[0] or now
            deadline = min(first + timeout, branch + branch_timeout, r['deadline'] - 1)
            if now >= deadline:
                raise DiscoveryError('runtime_limit')
            fence = row['fence'] + 1
            db.execute('UPDATE tasks SET state=?,owner=?,fence=?,attempts=attempts+1,first_lease=?,deadline=?,lease_until=?,revision=revision+1 WHERE run=? AND id=?',
                       ('RUNNING', owner, fence, first, deadline, deadline, run, alias(task)))
            counters = json.loads(r['counters'])
            counters['attempts'] += 1
            db.execute('UPDATE runs SET counters=?,last_clock=? WHERE id=?', (canonical(counters), max(now, r['last_clock']), run))
            return fence, deadline

    def commit(self, run, task, owner, fence, state, reason, output, artifacts=()):
        now = time.time()
        with self.transaction() as db:
            r = db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
            row = db.execute('SELECT * FROM tasks WHERE run=? AND id=?', (run, alias(task))).fetchone()
            if (r['state'] != 'EXECUTING' or r['generation'] or row['state'] != 'RUNNING'
                    or row['owner'] != owner or row['fence'] != fence
                    or now >= row['deadline'] or now < r['last_clock'] - 1):
                raise DiscoveryError('stale_commit')
            if state not in TRANSITIONS['RUNNING']:
                raise DiscoveryError('invalid_transition')
            for metadata, artifact in artifacts:
                encoded = canonical(artifact)
                if len(encoded.encode()) > MAX_ARTIFACT_BYTES or digest(artifact) != metadata['content_hash']:
                    raise DiscoveryError('evidence_integrity')
                existing = db.execute('SELECT hash,metadata FROM evidence WHERE run=? AND id=?', (run, metadata['id'])).fetchone()
                if existing:
                    if existing['hash'] != metadata['content_hash'] or existing['metadata'] != canonical(metadata):
                        raise DiscoveryError('evidence_integrity')
                else:
                    db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',
                               (run, metadata['id'], alias(task), canonical(metadata), encoded,
                                metadata['content_hash'], now + 7 * 86400))
            db.execute('UPDATE tasks SET state=?,reason=?,output=?,owner=NULL,lease_until=NULL,revision=revision+1 WHERE run=? AND id=?',
                       (state, reason, canonical(output), run, alias(task)))
            db.execute('UPDATE runs SET last_clock=? WHERE id=?', (max(now, r['last_clock']), run))

    def checkpoint(self, run, task, owner, fence, output, artifacts):
        now = time.time()
        with self.transaction() as db:
            r = db.execute('SELECT * FROM runs WHERE id=?', (run,)).fetchone()
            row = db.execute('SELECT * FROM tasks WHERE run=? AND id=?', (run, alias(task))).fetchone()
            if (r['state'] != 'EXECUTING' or r['generation'] or row['state'] != 'RUNNING'
                    or row['owner'] != owner or row['fence'] != fence or now >= row['deadline']
                    or now < r['last_clock'] - 1):
                raise DiscoveryError('stale_commit')
            for metadata, artifact in artifacts:
                encoded = canonical(artifact)
                if len(encoded.encode()) > MAX_ARTIFACT_BYTES or digest(artifact) != metadata['content_hash']:
                    raise DiscoveryError('evidence_integrity')
                existing = db.execute('SELECT hash FROM evidence WHERE run=? AND id=?', (run, metadata['id'])).fetchone()
                if existing:
                    if existing[0] != metadata['content_hash']:
                        raise DiscoveryError('evidence_integrity')
                else:
                    db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',
                               (run, metadata['id'], alias(task), canonical(metadata), encoded,
                                metadata['content_hash'], now + 7 * 86400))
            db.execute('UPDATE tasks SET output=?,revision=revision+1 WHERE run=? AND id=?', (canonical(output), run, alias(task)))
            db.execute('UPDATE runs SET last_clock=? WHERE id=?', (max(now, r['last_clock']), run))

    def evidence(self, run):
        with self.lock:
            rows = self.db.execute('SELECT * FROM evidence WHERE run=? ORDER BY id', (run,)).fetchall()
        result = []
        for row in rows:
            artifact, metadata = json.loads(row['artifact']), json.loads(row['metadata'])
            if digest(artifact) != row['hash'] or metadata['content_hash'] != row['hash'] or row['expires'] <= time.time():
                raise DiscoveryError('evidence_integrity')
            result.append((metadata, artifact))
        return result

    def enqueue(self, run, url, depth, source, task):
        key = digest(url)
        provenance = {'task': alias(task), 'source': source}
        with self.transaction() as db:
            existing = db.execute('SELECT provenance FROM urls WHERE run=? AND key=?', (run, key)).fetchone()
            if existing:
                values = json.loads(existing[0])
                if provenance not in values and len(values) < 100:
                    values.append(provenance)
                    db.execute('UPDATE urls SET provenance=? WHERE run=? AND key=?', (canonical(values), run, key))
                return False
            db.execute('INSERT INTO urls(run,key,url,state,depth,provenance) VALUES(?,?,?,?,?,?)', (run, key, url, 'PENDING', depth, canonical([provenance])))
            return True

    def url_attempt(self, run, url, deadline, maximum):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM urls WHERE run=? AND key=?', (run, digest(url))).fetchone()
            if row is None or row['attempts'] >= maximum or time.time() >= deadline:
                raise DiscoveryError('attempt_limit')
            db.execute("UPDATE urls SET attempts=attempts+1,state='RUNNING',first_lease=COALESCE(first_lease,?),deadline=COALESCE(deadline,?) WHERE run=? AND key=?",
                       (time.time(), deadline, run, digest(url)))
            return row['attempts'] + 1

    def url_finish(self, run, url, state):
        with self.transaction() as db:
            db.execute('UPDATE urls SET state=? WHERE run=? AND key=?', (state, run, digest(url)))

    def origin(self, run, origin):
        with self.lock:
            return dict(self.db.execute('SELECT * FROM origins WHERE run=? AND origin=?', (run, origin)).fetchone())

    def request_slot(self, run, origin):
        now = time.time()
        with self.transaction() as db:
            row = db.execute('SELECT * FROM origins WHERE run=? AND origin=?', (run, origin)).fetchone()
            ready = max(row['cooldown'], row['next_request'])
            if now < ready:
                return ready - now
            db.execute('UPDATE origins SET next_request=? WHERE run=? AND origin=?', (now + 1 / row['rate'], run, origin))
            return 0

    def cooldown(self, run, origin, delay):
        with self.transaction() as db:
            db.execute('UPDATE origins SET cooldown=MAX(cooldown,?),rate=MAX(0.05,rate/2),cap=MAX(1,cap/2) WHERE run=? AND origin=?',
                       (time.time() + delay, run, origin))

    def cancel(self, run):
        with self.transaction() as db:
            db.execute("UPDATE runs SET generation=generation+1,state='FINALISING' WHERE id=? AND state='EXECUTING'", (run,))
            db.execute("UPDATE tasks SET state='CANCELLED',reason='cancelled',fence=fence+1,revision=revision+1 WHERE run=? AND state NOT IN ('SUCCEEDED','PARTIALLY_SUCCEEDED','FAILED','SKIPPED','CANCELLED')", (run,))

    def finish(self, run, result):
        with self.transaction() as db:
            db.execute("UPDATE runs SET state='TERMINAL',result=? WHERE id=? AND state!='TERMINAL'", (canonical(result), run))

    def fail_run(self, run):
        """Fence unfinished work and retain an explicit terminal failure on abort."""
        with self.transaction() as db:
            failure = canonical({'kind': 'discovery_failure', 'outcome': 'failed',
                                 'terminal_reason': 'internal_failure', 'run_id': run})
            db.execute("UPDATE runs SET state='TERMINAL',generation=generation+1,result=? "
                       "WHERE id=? AND state!='TERMINAL'", (failure, run))
            db.execute("UPDATE tasks SET state=CASE WHEN state='RUNNING' THEN 'FAILED' ELSE 'SKIPPED' END, "
                       "reason='run aborted after an internal failure',fence=fence+1,revision=revision+1,"
                       "owner=NULL,lease_until=NULL WHERE run=? AND state NOT IN "
                       "('SUCCEEDED','PARTIALLY_SUCCEEDED','FAILED','SKIPPED','CANCELLED')", (run,))

    def knowledge_revision(self, partition):
        with self.lock:
            row = self.db.execute('SELECT revision FROM knowledge_heads WHERE partition=?', (partition,)).fetchone()
            return row[0] if row else 0

    def knowledge(self, partition):
        with self.lock:
            row = self.db.execute('SELECT * FROM knowledge WHERE partition=? ORDER BY revision DESC LIMIT 1', (partition,)).fetchone()
        if not row:
            return None
        value = json.loads(row['payload'])
        if digest(value) != row['hash']:
            raise DiscoveryError('knowledge_integrity')
        return dict(row, value=value)

    def save_knowledge(self, partition, expected, payload, consent):
        with self.transaction() as db:
            row = db.execute('SELECT revision FROM knowledge_heads WHERE partition=?', (partition,)).fetchone()
            current = row[0] if row else 0
            if current != expected or payload['revision'] != expected + 1:
                raise DiscoveryError('stale_knowledge_revision')
            encoded = canonical(payload)
            if len(encoded.encode()) > MAX_ARTIFACT_BYTES:
                raise DiscoveryError('resource_limit')
            db.execute('INSERT INTO knowledge VALUES(?,?,?,?,?,?,0)',
                       (partition, current + 1, encoded, digest(payload), canonical(consent), time.time()))
            db.execute('INSERT INTO knowledge_heads VALUES(?,?) ON CONFLICT(partition) DO UPDATE SET revision=excluded.revision', (partition, current + 1))

    def invalidate(self, partition, expected):
        with self.transaction() as db:
            row = db.execute('SELECT revision FROM knowledge_heads WHERE partition=?', (partition,)).fetchone()
            if (row[0] if row else 0) != expected:
                raise DiscoveryError('stale_knowledge_revision')
            db.execute('UPDATE knowledge SET invalidated=1 WHERE partition=?', (partition,))

    def close(self):
        with self.lock:
            self.db.close()
