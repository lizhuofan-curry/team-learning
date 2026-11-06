"""Bounded retries of frozen media delivery; planning never changes source state.

Expired worker leases are reported for the original queue's operator because
``media_queue.pending`` reclaims a whole batch. This module does not duplicate
that transition or silently exceed its per-pass limit.
"""
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

_WORKFLOW = str(Path(__file__).resolve().parent.parent)
if _WORKFLOW not in sys.path:
    sys.path.insert(0, _WORKFLOW)
import media_queue as media
from 任务中枢.task_hub import state_file

_ACTIONS = frozenset({'reclaim_expired', 'retry_delivery'})
_DEFAULT = dict(enabled=False, max_per_tick=1, max_automatic_attempts=2,
                cooldown_seconds=900, allowed_actions=sorted(_ACTIONS))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _epoch(value):
    if value is None:
        return time.time()
    if isinstance(value, dt.datetime):
        if value.utcoffset() is None:
            raise ValueError('recovery time needs a timezone')
        return value.timestamp()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('invalid recovery time')
    return float(value)


def _read(path, limit=1_000_000):
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('unsupported recovery record')
    raw = path.read_bytes()
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('record must be an object')
    return value, _hash(raw)


def _policy(root):
    path = root / 'task_center.local.json'
    config = _read(path)[0] if path.exists() else {}
    center_enabled = config.get('enabled', False)
    if not isinstance(center_enabled, bool):
        raise ValueError('task center enabled must be boolean')
    supplied = config.get('recovery', {})
    if not isinstance(supplied, dict) or set(supplied) - set(_DEFAULT):
        raise ValueError('invalid recovery settings')
    policy = dict(_DEFAULT, **supplied)
    if not isinstance(policy['enabled'], bool):
        raise ValueError('recovery enabled must be boolean')
    for key, low, high in (('max_per_tick', 1, 8), ('max_automatic_attempts', 1, 10),
                           ('cooldown_seconds', 0, 86400)):
        if type(policy[key]) is not int or not low <= policy[key] <= high:
            raise ValueError('invalid recovery budget')
    allowed = policy['allowed_actions']
    if not isinstance(allowed, list) or any(not isinstance(a, str) or a not in _ACTIONS for a in allowed):
        raise ValueError('invalid recovery action list')
    policy['allowed_actions'] = sorted(set(allowed))
    policy['task_center_enabled'] = center_enabled
    policy['recovery_enabled'] = policy['enabled']
    policy['enabled'] = center_enabled and policy['enabled']
    return policy, _hash(_json(policy).encode('utf-8'))


def _observation(code, identifier=None, severity='warning'):
    # Do not copy source failure messages, URL queries or subprocess stderr.
    return dict(code=code, source='recovery', external_id=identifier, severity=severity)


def _record(root, identifier):
    path = media.path_for(root, identifier)
    record, digest = _read(path)
    if (record.get('id') != identifier or record.get('version') != 1
            or not isinstance(record.get('test_only'), bool)
            or identifier != media.job_id(record['url'])):
        raise ValueError('invalid recovery source identity')
    return record, digest


def _delivery_packet(root, record):
    packet_path = media.safe_file(media.queue(root), record['packet_path'])
    bundle, _ = _read(packet_path, media.MAX_WIRE)
    manifest, files = media.verify_bundle(bundle)
    if (manifest['test_only'] or record['test_only']
            or media.flow.digest(files['result.json']) != record['packet_sha256']):
        raise ValueError('invalid live frozen packet')
    if media.normalize_url(manifest['canonical_url']) != record['url']:
        if media.normalize_url(manifest.get('source_url', manifest['canonical_url'])) != record['url']:
            raise ValueError('packet does not belong to source job')
    return record['packet_sha256']


def _ledger_path(root):
    return state_file(root, 'recovery.sqlite3')


def _queue_enabled(root):
    value = media.config(root).get('enabled', False)
    if not isinstance(value, bool):
        raise ValueError('media enabled must be boolean')
    return value


def _read_ledger(root):
    path = _ledger_path(root)
    if not path.exists():
        return []
    if path.is_symlink():
        raise ValueError('unsupported recovery ledger')
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute('SELECT * FROM attempts')]
    finally:
        connection.close()


def _budget(rows, identifier, action_id, policy, current):
    relevant = [row for row in rows if row['job_id'] == identifier]
    if any(row['id'] == action_id for row in relevant):
        return 'recovery_already_attempted'
    if len(relevant) >= policy['max_automatic_attempts']:
        return 'recovery_attempt_limit'
    if relevant and current - max(row['started_epoch'] for row in relevant) < policy['cooldown_seconds']:
        return 'recovery_cooldown'
    return None


def _action(identifier, digest, packet_sha):
    action_id = _hash(_json(['retry_delivery', identifier, digest]).encode('utf-8'))
    return dict(id=action_id, action='retry_delivery', job_id=identifier,
                source_sha256=digest, packet_sha256=packet_sha)


def plan_recovery(root, now=None):
    """Return a bounded read-only plan; a disabled policy can still be previewed."""
    root = Path(root).resolve()
    current = _epoch(now)
    policy, policy_sha = _policy(root)
    result = dict(version=1, root_sha256=_hash(str(root).encode('utf-8')),
                  policy_sha256=policy_sha, enabled=policy['enabled'],
                  generated_epoch=current, actions=[], observations=[])
    if not _queue_enabled(root):
        result['observations'].append(_observation('media_queue_disabled', severity='info'))
        return result
    try:
        rows = _read_ledger(root)
    except (sqlite3.Error, OSError, ValueError):
        result['observations'].append(_observation('recovery_ledger_unavailable'))
        return result
    for path in sorted((root / '媒体队列' / '任务').glob('*.json')):
        identifier = path.stem
        try:
            record, digest = _record(root, identifier)
            if record['test_only']:
                continue
            state = record.get('state')
            if state == 'processing' and 'reclaim_expired' in policy['allowed_actions']:
                lease = record.get('lease_until')
                if isinstance(lease, bool) or not isinstance(lease, (int, float)) or not math.isfinite(lease):
                    raise ValueError('invalid worker lease')
                if lease <= current:
                    result['observations'].append(_observation('expired_lease_manual_required', identifier))
            if state != 'delivery_pending' or 'retry_delivery' not in policy['allowed_actions']:
                continue
            packet_sha = _delivery_packet(root, record)
            action = _action(identifier, digest, packet_sha)
            blocked = _budget(rows, identifier, action['id'], policy, current)
            if blocked:
                result['observations'].append(_observation(blocked, identifier,
                                                          'info' if blocked == 'recovery_cooldown' else 'warning'))
            elif len(result['actions']) < policy['max_per_tick']:
                result['actions'].append(action)
            else:
                result['observations'].append(_observation('recovery_pass_limit', identifier, 'info'))
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            result['observations'].append(_observation('recovery_source_or_packet_invalid', identifier))
    return result


@contextlib.contextmanager
def _locked(root):
    path = state_file(root, '.recovery.lock')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if not path.stat().st_size:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _connect(root):
    path = _ledger_path(root)
    if path.is_symlink():
        raise ValueError('unsupported recovery ledger')
    connection = sqlite3.connect(str(path), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('''CREATE TABLE IF NOT EXISTS attempts (
        id TEXT PRIMARY KEY, job_id TEXT NOT NULL, action TEXT NOT NULL,
        source_sha256 TEXT NOT NULL, started_epoch REAL NOT NULL,
        finished_epoch REAL, outcome TEXT NOT NULL, error_type TEXT,
        observed_state TEXT)''')
    connection.commit()
    path.chmod(0o600)
    return connection


def _live_policy(root, expected_sha):
    """Revalidate switches after waiting and immediately before outside work."""
    try:
        policy, digest = _policy(root)
        if not policy['enabled']:
            return None, 'recovery_disabled'
        if digest != expected_sha:
            return None, 'recovery_policy_changed'
        if not _queue_enabled(root):
            return None, 'media_queue_disabled'
        return policy, None
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None, 'recovery_policy_invalid'


def apply_recovery(root, plan, now=None):
    """Apply only explicitly enabled frozen-delivery retries and retain receipts.

    Each source snapshot is attempted at most once. A crash after reserving an
    attempt is treated as uncertain and requires a person, not an automatic
    replay. The recovery lock serializes this module; the original push still
    owns media locking and atomically checks the planned source hash before
    reading its current state and frozen packet. Closing a policy switch stops
    work that has not started; a transfer already in flight may still finish.
    """
    root = Path(root).resolve()
    current = _epoch(now)
    policy, policy_sha = _policy(root)
    result = dict(enabled=policy['enabled'], attempted=0, outcomes=[], observations=[])
    if not policy['enabled']:
        result['observations'].append(_observation('recovery_disabled', severity='info'))
        return result
    if not _queue_enabled(root):
        result['observations'].append(_observation('media_queue_disabled', severity='info'))
        return result
    if (not isinstance(plan, dict) or plan.get('version') != 1
            or plan.get('root_sha256') != _hash(str(root).encode('utf-8'))
            or plan.get('policy_sha256') != policy_sha or not isinstance(plan.get('actions'), list)):
        raise ValueError('recovery plan no longer matches this root or policy')
    if len(plan['actions']) > policy['max_per_tick']:
        raise ValueError('recovery plan exceeds pass limit')
    if not plan['actions']:
        return result
    with _locked(root):
        policy, stop = _live_policy(root, plan['policy_sha256'])
        if stop:
            result['observations'].append(_observation(stop))
            if stop == 'recovery_disabled':
                result['enabled'] = False
            return result
        connection = _connect(root)
        try:
            for action in plan['actions']:
                policy, stop = _live_policy(root, plan['policy_sha256'])
                if stop:
                    result['observations'].append(_observation(stop))
                    if stop == 'recovery_disabled':
                        result['enabled'] = False
                    break
                identifier = action.get('job_id') if isinstance(action, dict) else None
                if (not isinstance(action, dict) or action.get('action') != 'retry_delivery'
                        or 'retry_delivery' not in policy['allowed_actions']):
                    raise ValueError('only frozen delivery retry can be executed')
                try:
                    # Release this lock before push, which owns its own media
                    # locks and atomically compares the planned source digest.
                    with media.locked(root):
                        record, digest = _record(root, identifier)
                        if record['test_only'] or record.get('state') != 'delivery_pending':
                            raise ValueError('recovery source is no longer pending')
                        packet_sha = _delivery_packet(root, record)
                        if action != _action(identifier, digest, packet_sha):
                            raise ValueError('recovery source changed after planning')
                except (OSError, ValueError, TypeError, KeyError, RecursionError):
                    result['observations'].append(_observation('recovery_plan_stale_or_invalid', identifier))
                    continue
                rows = [dict(row) for row in connection.execute('SELECT * FROM attempts')]
                blocked = _budget(rows, identifier, action['id'], policy, current)
                if blocked:
                    result['observations'].append(_observation(blocked, identifier))
                    continue
                connection.execute('INSERT INTO attempts VALUES(?,?,?,?,?,NULL,?,NULL,NULL)',
                                   (action['id'], identifier, 'retry_delivery', digest, current, 'started'))
                connection.commit()  # Persist before outside effects, including uncertain failures.
                policy, stop = _live_policy(root, plan['policy_sha256'])
                if stop:
                    # No outside effect has started, so this reservation can be
                    # removed; future explicit re-enablement may plan it again.
                    connection.execute('DELETE FROM attempts WHERE id=? AND outcome=?', (action['id'], 'started'))
                    connection.commit()
                    result['observations'].append(_observation(stop, identifier))
                    if stop == 'recovery_disabled':
                        result['enabled'] = False
                    break
                result['attempted'] += 1
                outcome, error_type = 'failed', None
                try:
                    receipt = media.push(root, identifier, expected_job_sha256=action['source_sha256'])
                    if not isinstance(receipt, dict) or receipt.get('status') != 'delivered':
                        raise ValueError('unexpected queue push receipt')
                    outcome = 'delivered'
                except Exception as error:
                    error_type = type(error).__name__
                try:
                    observed = _record(root, identifier)[0].get('state')
                except (OSError, ValueError, TypeError, KeyError):
                    observed = None
                connection.execute('UPDATE attempts SET finished_epoch=?,outcome=?,error_type=?,observed_state=? WHERE id=?',
                                   (current, outcome, error_type, observed, action['id']))
                connection.commit()
                result['outcomes'].append(dict(action_id=action['id'], job_id=identifier,
                                               outcome=outcome, error_type=error_type,
                                               observed_state=observed,
                                               personal_learning_completed=False))
        finally:
            connection.close()
    return result
