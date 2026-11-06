#!/usr/bin/env python3
"""Local task index and explicit event links; never launches workers or sends messages."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from 任务中枢.task_hub import EventConflict, Hub, STATUSES, state_file
from 任务中枢.task_sources import build_snapshot


@contextlib.contextmanager
def sync_lock(root):
    path = state_file(root, '.sync.lock')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b'0')
                stream.flush()
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


def sync_sources(root, *, sync_state=None):
    """Refresh projections only. Source files remain the execution authority."""
    root = Path(root)
    with sync_lock(root):
        snapshot = build_snapshot(root, sync_state=sync_state)
        added_tasks = updated_tasks = added_events = 0
        with Hub(root) as hub:
            existing = {t['id']: t for t in hub.list_tasks(include_tests=True)}
            event_ids = {e['id'] for e in hub.list_events(include_tests=True)}
            for projected in snapshot['tasks']:
                task = hub.register(**projected)
                added_tasks += int(task['id'] not in existing)
                revised = hub.set_status(task['id'], projected['status'],
                                         evidence=projected['evidence'],
                                         next_action=projected['next_action'],
                                         expected_revision=task['revision'])
                updated_tasks += int(revised['revision'] != task['revision'])
            for item in snapshot['events']:
                try:
                    event = hub.ingest_event(item['source'], item['external_id'], item['payload'])
                except EventConflict:
                    snapshot['observations'].append(dict(
                        code='immutable_event_conflict', severity='warning', source=item['source'],
                        external_id=item['external_id'], evidence=item['payload']['reference'],
                        detail='同编号事件的原件版本有变化，历史关联保留，已跳过该事件。'))
                    continue
                added_events += int(event['id'] not in event_ids)
                event_ids.add(event['id'])
        return dict(tasks_added=added_tasks, tasks_updated=updated_tasks,
                    events_added=added_events, observations=snapshot['observations'],
                    execution_started=False)


def view(root):
    root = Path(root)
    snapshot = build_snapshot(root)
    path = root / '任务中枢' / 'state.sqlite3'
    if not path.exists():
        return dict(initialized=False, tasks=[], unlinked_events=[],
                    observations=snapshot['observations'], next_action='先运行 sync 建立本地索引')
    with Hub(root) as hub:
        tasks = hub.list_tasks()
        events = hub.list_events()
    # A read view uses current source observations; the stored projection is a cache.
    live = {(t['source'], t['external_id']): t for t in snapshot['tasks']}
    for task in tasks:
        if task['source'] == 'media':
            current = live.get((task['source'], task['external_id']))
            task['indexed_status'] = task['status']
            if current is not None:
                task.update({k: current[k] for k in ('status', 'evidence', 'next_action')})
                task['source_available'] = True
            else:
                task['source_available'] = False
                task['status'] = 'waiting'
                task['next_action'] = '源记录当前不可读取；核对源文件，不能据缓存宣称进展'
                snapshot['observations'].append(dict(
                    code='indexed_source_unavailable', severity='warning', source='media',
                    external_id=task['external_id'], evidence=task['evidence'],
                    detail=task['next_action']))
    live_events = {(e['source'], e['external_id']): e['payload'] for e in snapshot['events']}
    for event in events:
        if event['source'] == 'hermes':
            event['source_available'] = live_events.get((event['source'], event['external_id'])) == event['payload']
            if not event['source_available']:
                snapshot['observations'].append(dict(
                    code='indexed_event_unavailable', severity='warning', source='hermes',
                    external_id=event['external_id'], evidence=event['payload'].get('reference'),
                    detail='已索引事件的原件缺失或版本不一致；历史记录保留，暂不可关联处理。'))
    return dict(initialized=True, tasks=tasks,
                unlinked_events=[e for e in events if e['task_id'] is None],
                observations=snapshot['observations'], execution_started=False)


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='个人学习工作流根目录')
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('preview', 'sync', 'status', 'attention'):
        commands.add_parser(action)
    create = commands.add_parser('create')
    create.add_argument('--key', required=True)
    create.add_argument('--title', required=True)
    create.add_argument('--kind', default='general')
    create.add_argument('--next-action', default='')
    create.add_argument('--scope', choices=('read_only', 'local_prepare'), default='local_prepare')
    link = commands.add_parser('link')
    link.add_argument('--event', required=True)
    link.add_argument('--task', required=True)
    state = commands.add_parser('set-status')
    state.add_argument('--task', required=True)
    state.add_argument('--status', required=True, choices=sorted(STATUSES))
    state.add_argument('--revision', required=True, type=int)
    state.add_argument('--evidence', action='append')
    state.add_argument('--next-action', default='')
    events = commands.add_parser('events')
    events.add_argument('--task')
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    if args.action == 'preview':
        result = build_snapshot(root)
    elif args.action == 'sync':
        result = sync_sources(root)
    elif args.action in ('status', 'attention'):
        result = view(root)
        if args.action == 'attention':
            result['tasks'] = [t for t in result['tasks'] if t['source'] != 'media'
                               and t['status'] in ('blocked', 'awaiting_review')]
            result['observations'] = [o for o in result['observations']
                                      if o.get('severity') != 'info']
    else:
        if args.action != 'create' and not (root / '任务中枢' / 'state.sqlite3').exists():
            raise ValueError('任务索引尚未初始化；先运行 sync 或 create')
        with Hub(root) as hub:
            if args.action == 'create':
                result = hub.register('manual', args.key, args.title, args.kind,
                                      next_action=args.next_action, scope=args.scope)
            elif args.action == 'link':
                event = next((e for e in hub.list_events(include_tests=True) if e['id'] == args.event), None)
                if event and event['source'] == 'hermes':
                    live_events = build_snapshot(root, include_tests=event['test_only'])['events']
                    if not any(e['source'] == event['source'] and e['external_id'] == event['external_id']
                               and e['payload'] == event['payload'] for e in live_events):
                        raise ValueError('事件原件当前无法核实，不能关联；请先核对来源')
                result = hub.link_event(args.event, args.task)
            elif args.action == 'events':
                result = hub.list_events(task_id=args.task)
            else:
                task = hub.get_task(args.task)
                if task is None or task['source'] != 'manual':
                    raise ValueError('仅手工任务可修改状态；媒体执行状态由原队列管理')
                result = hub.set_status(args.task, args.status, evidence=args.evidence,
                                        next_action=args.next_action,
                                        expected_revision=args.revision)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': type(error).__name__,
                          'detail': '操作未完成；请核对参数及本地源记录，未启动执行任务'}, ensure_ascii=False),
              file=sys.stderr)
        sys.exit(2)
