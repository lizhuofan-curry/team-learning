#!/usr/bin/env python3
"""Durable evidence-inspection work items, without executing their contents.

The caller must check the owning task's scope and the current source before
enqueueing or executing work. A queue entry is context, never an authorization.
``review_followup`` waits for an agent to claim it; this module does not read a
message as an instruction, invoke a model, launch commands, or send messages.
Cancellation invalidates a lease; it does not terminate a worker's process.
"""
import contextlib
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import time

from 任务中枢.task_hub import state_file


ACTIONS = frozenset({'review_followup', 'inspect_experiment', 'inspect_pr'})
MAX_ATTEMPTS = 3
IDENTIFIER = re.compile(r'[a-f0-9]{24}')
TOKEN = re.compile(r'[a-f0-9]{32}')
MAX_JSON_BYTES = 128_000


def _json(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > MAX_JSON_BYTES:
        raise ValueError('work metadata exceeds size limit')
    return encoded


def _metadata(value, name):
    if not isinstance(value, dict):
        raise ValueError(name + ' must be a JSON object')
    return _json(value)


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('invalid task, event or work identifier')
    return value


def _epoch(value):
    if isinstance(value, dt.datetime):
        if value.utcoffset() is None:
            raise ValueError('timezone required')
        value = value.timestamp()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('invalid time')
    return float(value)


def _token_digest(token):
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError('invalid lease token')
    return hashlib.sha256(token.encode('ascii')).hexdigest()


class Queue:
    """A bounded-attempt queue under a private workflow root.

    ``now`` may be an aware datetime, epoch seconds, or a callable clock.
    Live workers claim only live work. Tests use ``test_only=True`` as an
    explicit separate claim lane; neither lane can consume the other's work.
    """

    def __init__(self, root, now=None, test_only=False, retry_delay_seconds=30):
        if not isinstance(test_only, bool):
            raise ValueError('test_only must be boolean')
        if (isinstance(retry_delay_seconds, bool)
                or not isinstance(retry_delay_seconds, (int, float))
                or not math.isfinite(retry_delay_seconds) or retry_delay_seconds < 0):
            raise ValueError('invalid retry delay')
        self._clock = now
        self.test_only = test_only
        self.retry_delay_seconds = retry_delay_seconds
        self._now()
        self.path = state_file(root, 'dispatch.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA busy_timeout=15000')
        self.connection.execute('PRAGMA foreign_keys=ON')
        try:
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    action TEXT NOT NULL, payload TEXT NOT NULL, test_only INTEGER NOT NULL,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL,
                    worker_id TEXT, lease_token TEXT, lease_until REAL,
                    next_attempt_at REAL NOT NULL, result TEXT, last_error TEXT,
                    report_token_digest TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(task_id,event_id,action)
                );
                CREATE INDEX IF NOT EXISTS jobs_due ON jobs(test_only,state,next_attempt_at);
                CREATE TABLE IF NOT EXISTS receipts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id), attempt INTEGER NOT NULL,
                    kind TEXT NOT NULL, worker_id TEXT, data TEXT NOT NULL, created_at REAL NOT NULL
                );
            ''')
            self.path.chmod(0o600)
        except BaseException:
            self.connection.close()
            raise

    def _now(self, override=None):
        value = override if override is not None else self._clock
        if callable(value):
            value = value()
        return _epoch(time.time() if value is None else value)

    @contextlib.contextmanager
    def _write(self):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _row(self, job_id):
        _identifier(job_id)
        row = self.connection.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise ValueError('unknown work item')
        return dict(row)

    def _public(self, row, expose_token=False):
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        result['result'] = json.loads(result['result']) if result['result'] is not None else None
        result['test_only'] = bool(result['test_only'])
        result.pop('report_token_digest', None)
        if not expose_token:
            result['lease_token'] = None
        receipt = self.connection.execute(
            'SELECT sequence,attempt,kind,worker_id,data,created_at FROM receipts '
            'WHERE job_id=? ORDER BY sequence DESC LIMIT 1', (row['id'],)).fetchone()
        result['receipt'] = None
        if receipt is not None:
            result['receipt'] = dict(receipt)
            result['receipt']['data'] = json.loads(result['receipt']['data'])
        return result

    def _receipt(self, row, kind, data, now):
        self.connection.execute(
            'INSERT INTO receipts(job_id,attempt,kind,worker_id,data,created_at) VALUES(?,?,?,?,?,?)',
            (row['id'], row['attempts'], kind, row['worker_id'], _json(data), now))

    def enqueue(self, task_id, event_id, action, payload, test_only=False):
        _identifier(task_id)
        _identifier(event_id)
        if action not in ACTIONS or not isinstance(test_only, bool):
            raise ValueError('unsupported action or test marker')
        encoded = _metadata(payload, 'payload')
        if 'test_only' in payload and payload['test_only'] is not test_only:
            raise ValueError('payload test marker differs from work lane')
        identifier = hashlib.sha256(_json([task_id, event_id, action]).encode('utf-8')).hexdigest()[:24]
        with self._write():
            old = self.connection.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            if old is not None:
                old = dict(old)
                if ((old['task_id'], old['event_id'], old['action'], old['payload'], bool(old['test_only']))
                        != (task_id, event_id, action, encoded, test_only)):
                    raise ValueError('immutable work item conflict')
                return self._public(old)
            stamp = self._now()
            self.connection.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                    (identifier, task_id, event_id, action, encoded, int(test_only),
                                     'pending', 0, None, None, None, stamp, None, None, None, stamp, stamp))
            row = self._row(identifier)
            self._receipt(row, 'enqueued', {'execution_started': False}, stamp)
            return self._public(row)

    def _recover(self, now):
        rows = self.connection.execute(
            'SELECT * FROM jobs WHERE state=? AND lease_until<=? AND test_only=? ORDER BY id',
            ('running', now, int(self.test_only))).fetchall()
        requeued = failed = 0
        for item in rows:
            row = dict(item)
            terminal = row['attempts'] >= MAX_ATTEMPTS
            self.connection.execute(
                'UPDATE jobs SET state=?,worker_id=NULL,lease_token=NULL,lease_until=NULL,'
                'next_attempt_at=?,last_error=?,report_token_digest=NULL,updated_at=? WHERE id=?',
                ('failed' if terminal else 'pending', now + self.retry_delay_seconds,
                 'worker lease expired; prior claim cannot commit', now, row['id']))
            self._receipt(row, 'lease_expired', {'terminal': terminal}, now)
            failed += int(terminal)
            requeued += int(not terminal)
        return {'requeued': requeued, 'failed': failed}

    def recover_expired(self, now=None):
        with self._write():
            return self._recover(self._now(now))

    def claim(self, worker_id, lease_seconds=120, actions=None):
        if (not isinstance(worker_id, str) or not worker_id.strip()
                or len(worker_id.encode('utf-8')) > 200):
            raise ValueError('invalid worker identity')
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError('lease_seconds must be an integer from 1 to 3600')
        selected = sorted(ACTIONS) if actions is None else actions
        if (not isinstance(selected, (list, tuple)) or not selected
                or any(action not in ACTIONS for action in selected)):
            raise ValueError('invalid worker action filter')
        with self._write():
            now = self._now()
            self._recover(now)
            item = self.connection.execute(
                'SELECT * FROM jobs WHERE state=? AND test_only=? AND next_attempt_at<=? '
                'AND attempts<? AND action IN (' + ','.join('?' for _ in selected) + ') '
                'ORDER BY created_at,id LIMIT 1',
                ('pending', int(self.test_only), now, MAX_ATTEMPTS, *selected)).fetchone()
            if item is None:
                return None
            row = dict(item)
            self.connection.execute(
                'UPDATE jobs SET state=?,attempts=attempts+1,worker_id=?,lease_token=?,lease_until=?, '
                'report_token_digest=NULL,updated_at=? WHERE id=?',
                ('running', worker_id, secrets.token_hex(16), now + lease_seconds, now, row['id']))
            row = self._row(row['id'])
            self._receipt(row, 'claimed', {'lease_until': row['lease_until']}, now)
            return self._public(row, expose_token=True)

    def _owned(self, row, token, now):
        self._lane(row)
        _token_digest(token)
        if (row['state'] != 'running' or row['lease_token'] is None
                or not secrets.compare_digest(row['lease_token'], token)
                or row['lease_until'] <= now):
            raise ValueError('work lease lost, expired or cancelled')

    def _lane(self, row):
        if bool(row['test_only']) != self.test_only:
            raise ValueError('work item belongs to a different work lane')

    def complete(self, job_id, token, result):
        encoded = _metadata(result, 'result')
        digest = _token_digest(token)
        with self._write():
            row = self._row(job_id)
            self._lane(row)
            if row['state'] == 'completed' and row['report_token_digest'] == digest:
                if row['result'] != encoded:
                    raise ValueError('completion receipt conflict')
                return self._public(row)
            now = self._now()
            self._owned(row, token, now)
            self.connection.execute(
                'UPDATE jobs SET state=?,result=?,last_error=NULL,lease_token=NULL,lease_until=NULL,'
                'report_token_digest=?,updated_at=? WHERE id=?',
                ('completed', encoded, digest, now, job_id))
            self._receipt(row, 'completed', {'result': result}, now)
            return self._public(self._row(job_id))

    def fail(self, job_id, token, reason):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError('invalid failure reason; use a short non-private diagnostic')
        digest = _token_digest(token)
        with self._write():
            row = self._row(job_id)
            self._lane(row)
            if row['state'] in ('pending', 'failed') and row['report_token_digest'] == digest:
                if row['last_error'] != reason:
                    raise ValueError('failure receipt conflict')
                return self._public(row)
            now = self._now()
            self._owned(row, token, now)
            terminal = row['attempts'] >= MAX_ATTEMPTS
            self.connection.execute(
                'UPDATE jobs SET state=?,last_error=?,lease_token=NULL,lease_until=NULL,'
                'next_attempt_at=?,report_token_digest=?,updated_at=? WHERE id=?',
                ('failed' if terminal else 'pending', reason, now + self.retry_delay_seconds,
                 digest, now, job_id))
            self._receipt(row, 'failed', {'terminal': terminal, 'reason': reason}, now)
            return self._public(self._row(job_id))

    def cancel(self, job_id):
        with self._write():
            row = self._row(job_id)
            self._lane(row)
            if row['state'] == 'cancelled':
                return self._public(row)
            if row['state'] == 'completed':
                raise ValueError('completed work cannot be cancelled')
            stamp = self._now()
            self.connection.execute(
                'UPDATE jobs SET state=?,lease_token=NULL,lease_until=NULL,report_token_digest=NULL,'
                'updated_at=? WHERE id=?', ('cancelled', stamp, job_id))
            self._receipt(row, 'cancelled', {}, stamp)
            return self._public(self._row(job_id))

    def list_jobs(self, include_tests=False):
        if not isinstance(include_tests, bool):
            raise ValueError('include_tests must be boolean')
        query = 'SELECT * FROM jobs' + ('' if include_tests else ' WHERE test_only=0') + ' ORDER BY created_at,id'
        return [self._public(dict(row)) for row in self.connection.execute(query)]

    def list_receipts(self, job_id):
        row = self._row(job_id)
        if bool(row['test_only']) != self.test_only:
            raise ValueError('receipt belongs to a different work lane')
        result = []
        for receipt in self.connection.execute('SELECT * FROM receipts WHERE job_id=? ORDER BY sequence', (job_id,)):
            item = dict(receipt)
            item['data'] = json.loads(item['data'])
            result.append(item)
        return result

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
