"""Single-pass worker for the two local evidence inspection actions."""
from pathlib import Path

import learning_flow
from .task_dispatch import Queue
from .task_hub import Hub, state_file
from .task_sources import build_snapshot

INSPECTIONS = {'inspect_experiment': 'experiment', 'inspect_pr': 'github-pr'}


def dispatch_enabled(root):
    path = Path(root) / 'task_center.local.json'
    if not path.exists():
        return False
    config = learning_flow.read_json(path)
    if not isinstance(config, dict) or type(config.get('enabled', False)) is not bool:
        raise ValueError('invalid task center switch')
    options = config.get('dispatch', {})
    if not isinstance(options, dict) or type(options.get('enabled', False)) is not bool:
        raise ValueError('invalid dispatch switch')
    return config.get('enabled', False) and options.get('enabled', False)


def run_once(root, worker_id='local-inspector'):
    root = Path(root)
    if not dispatch_enabled(root):
        return {'state': 'disabled'}
    if not (state_file(root, 'dispatch.sqlite3')).is_file():
        return {'state': 'idle'}
    with Queue(root) as queue:
        job = queue.claim(worker_id, actions=sorted(INSPECTIONS))
        if job is None:
            return {'state': 'idle'}
        snapshot = build_snapshot(root)
        with Hub(root) as hub:
            task = hub.get_task(job['task_id'])
            event = next((item for item in hub.list_events(task_id=job['task_id'])
                          if item['id'] == job['event_id']), None)
        source = INSPECTIONS[job['action']]
        projected = next((item for item in snapshot['tasks'] if task
                          and item['source'] == source and item['external_id'] == task['external_id']), None)
        current = next((item for item in snapshot['events'] if event
                        and item['source'] == source and item['external_id'] == event['external_id']), None)
        context_matches = (
            task and task['scope'] == 'read_only' and task['source'] == source
            and task['status'] != 'cancelled' and not task['test_only']
            and event and event['source'] == source and projected and current
            and current.get('task_ref') == task['external_id']
            and current['payload'] == event['payload']
            and job['payload'] == dict(source=event['source'], external_id=event['external_id'],
                                       source_payload=event['payload'], task_scope=task['scope'],
                                       test_only=False)
        )
        if not context_matches:
            queue.cancel(job['id'])
            return {'state': 'cancelled', 'job_id': job['id'], 'reason': 'source_context_changed'}
        if not dispatch_enabled(root):
            queue.fail(job['id'], job['lease_token'], 'dispatch_paused')
            return {'state': 'paused', 'job_id': job['id']}
        result = dict(source=source, evidence=projected['evidence'],
                      observed_status=projected['status'], scope='metadata_inspection')
        receipt = queue.complete(job['id'], job['lease_token'], result)
        return {'state': receipt['state'], 'job_id': job['id'], 'result': result}
