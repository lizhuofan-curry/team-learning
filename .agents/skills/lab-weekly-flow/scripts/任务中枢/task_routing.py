"""Route only explicit task references; enqueue review, never execute message text."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

import collaboration_flow as collaboration
import learning_flow as flow

MARKER = re.compile(r'(?:任务编号\s*[:：]\s*|\[task:)([a-f0-9]{24})(?![a-f0-9])', re.I)
TIMEZONE = dt.timezone(dt.timedelta(hours=8))


def policy(root):
    path = Path(root) / 'task_center.local.json'
    if not path.exists():
        return dict(enabled=False)
    config = flow.read_json(path)
    if not isinstance(config, dict) or type(config.get('enabled', False)) is not bool:
        raise ValueError('invalid task-center configuration')
    value = config.get('routing', {})
    if not isinstance(value, dict) or type(value.get('enabled', False)) is not bool:
        raise ValueError('invalid routing configuration')
    enabled = config.get('enabled', False) and value.get('enabled', False)
    if enabled:
        flow.date_value(value.get('since'))
    return dict(value, enabled=enabled)


def reference(text):
    values = {value.lower() for value in MARKER.findall(text)}
    if len(values) > 1:
        raise ValueError('ambiguous task reference')
    return next(iter(values)) if values else None


def _observation(code, source, key, path, detail):
    return dict(code=code, severity='warning', source=source, external_id=key,
                evidence=str(path), detail=detail)


def _raw(path):
    if path.is_symlink():
        raise ValueError('symlink not supported')
    with path.open('rb') as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('record too large')
    return raw, json.loads(raw.decode('utf-8'))


def build_wechat_snapshot(root, now=None, include_tests=False):
    root = Path(root).resolve()
    result = dict(tasks=[], events=[], observations=[])
    try:
        options = policy(root)
    except (OSError, ValueError, TypeError, KeyError):
        result['observations'].append(_observation('routing_config_invalid', 'wechat-task', None,
            root / 'task_center.local.json', '任务路由配置无法校验，未扩大读取范围。'))
        return result
    if not options['enabled']:
        return result
    today = (now or dt.datetime.now(TIMEZONE)).astimezone(TIMEZONE).date().isoformat()
    for day in sorted((root / '收件箱').glob('????-??-??')):
        if day.name < options['since'] or day.name > today:
            continue
        for path in sorted(day.glob('*.json')):
            try:
                raw, item = _raw(path)
                item = flow.validate_event(item)
                if (item['kind'] != 'user-original' or item['channel'] != 'wechat'
                        or item['date'] != day.name or path.name != item['id'] + '.json'):
                    continue
                if type(item.get('test_only', False)) is not bool or item.get('test_only', False):
                    continue
                task_ref = reference(item['text'])
                if task_ref is None:
                    continue
                result['events'].append(dict(source='wechat-task', external_id=item['id'],
                    payload=dict(reference=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                                 text_sha256=item['text_sha256'], date=item['date'], test_only=False),
                    task_ref=task_ref, task_ref_type='task_id'))
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                # Corrupt unrelated captures are not promoted to tasks.
                result['observations'].append(_observation('task_capture_unverified', 'wechat-task',
                    None, path, '本次范围内一条原话无法核验或引用多个任务，保留原件待核对。'))
    return result


def route_followups(root, hub, snapshot):
    """Associate explicit IDs and persist evidence-review work; source text grants nothing."""
    from .task_dispatch import Queue
    root = Path(root).resolve()
    result = dict(linked=0, jobs_added=0, observations=[])
    try:
        options = policy(root)
    except (OSError, ValueError, TypeError, KeyError):
        return result
    if not options['enabled']:
        return result
    candidates = [item for item in snapshot['events'] if item['source'] in ('hermes', 'wechat-task')]
    if not candidates:
        return result
    with Queue(root) as queue:
        existing_jobs = {job['id']: job for job in queue.list_jobs(include_tests=True)}
        jobs = set(existing_jobs)
        indexed_events = {(event['source'], event['external_id']): event
                          for event in hub.list_events(include_tests=True)}
        live_items = {(item['source'], item['external_id']): item for item in candidates}
        for item in candidates:
            try:
                if policy(root) != options:
                    break
                event = indexed_events[(item['source'], item['external_id'])]
                if event['payload'] != item['payload']:
                    raise ValueError('indexed source version differs')
                path = Path(item['payload']['reference'])
                raw, record = _raw(path)
                if item['source'] == 'hermes':
                    record = collaboration.validate_message(record)
                    if (record['sender'] != 'hermes' or record['id'] != item['external_id']
                            or collaboration.envelope_hash(record) != item['payload']['message_sha256']):
                        raise ValueError('message version differs')
                    if record['kind'] not in ('request', 'correction'):
                        continue
                    created = dt.datetime.fromisoformat(record['created_at'].replace('Z', '+00:00'))
                    if created.astimezone(TIMEZONE).date().isoformat() < options['since']:
                        continue
                    task_ref = reference(record['text'])
                else:
                    record = flow.validate_event(record)
                    if hashlib.sha256(raw).hexdigest() != item['payload']['sha256']:
                        raise ValueError('capture version differs')
                    task_ref = reference(record['text'])
                if task_ref is None:
                    continue
                task = hub.get_task(task_ref)
                if task is None or task['status'] == 'cancelled' or task['test_only'] != event['test_only']:
                    raise ValueError('unknown, stopped or mismatched task')
                if task['scope'] not in ('read_only', 'local_prepare'):
                    raise ValueError('unsupported scope')
                was_linked = event['task_id'] is not None
                hub.link_event(event['id'], task['id'])
                result['linked'] += int(not was_linked)
                canonical = event
                if item['source'] == 'hermes':
                    captures = set(re.findall(r'capture[-:]([a-f0-9]{24})(?![a-f0-9])', record['source_id']))
                    captures.update(re.findall(r'原素材编号\s*[:：]\s*([a-f0-9]{24})(?![a-f0-9])', record['text']))
                    if len(captures) == 1:
                        capture_id = next(iter(captures))
                        original = live_items.get(('wechat-task', capture_id))
                        if original and original.get('task_ref') == task['id']:
                            canonical = indexed_events[('wechat-task', capture_id)]
                            hub.link_event(canonical['id'], task['id'])
                # Recheck cancellation and the pause switch at the dispatch boundary.
                if policy(root) != options or hub.get_task(task['id'])['status'] == 'cancelled':
                    continue
                job = queue.enqueue(task['id'], canonical['id'], 'review_followup',
                                    dict(source=canonical['source'], external_id=canonical['external_id'],
                                         source_payload=canonical['payload'], task_scope=task['scope'],
                                         test_only=canonical['test_only']), test_only=canonical['test_only'])
                result['jobs_added'] += int(job['id'] not in jobs)
                jobs.add(job['id'])
                for old in existing_jobs.values():
                    if (old['id'] != job['id'] and old['event_id'] == event['id']
                            and canonical['id'] != event['id'] and old['task_id'] == task['id']
                            and old['action'] == 'review_followup' and old['state'] == 'pending'
                            and old['attempts'] == 0 and old['test_only'] == canonical['test_only']):
                        queue.cancel(old['id'])
            except (OSError, ValueError, TypeError, KeyError, StopIteration, RecursionError):
                result['observations'].append(_observation('followup_needs_triage', item['source'],
                    item['external_id'], item['payload'].get('reference'),
                    '后续意见无法自动关联；请核对原件、明确任务编号及任务是否已停止。'))
    return result
