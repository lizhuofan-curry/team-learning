"""Bounded local workers for experiment and pull request evidence."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import learning_flow
from .task_dispatch import Queue
from .task_hub import Hub, state_file
from .experiment_sources import build_experiment_snapshot
from .pr_sources import build_pr_snapshot

INSPECTIONS = {'inspect_experiment': 'experiment', 'inspect_pr': 'github-pr'}
ACTIONS_BY_SOURCE = {source: action for action, source in INSPECTIONS.items()}


def dispatch_options(root):
    path = Path(root) / 'task_center.local.json'
    if not path.exists():
        return {'enabled': False, 'parallel': False, 'auto_inspect': False}
    config = learning_flow.read_json(path)
    if not isinstance(config, dict) or type(config.get('enabled', False)) is not bool:
        raise ValueError('invalid task center switch')
    options = config.get('dispatch', {})
    switches = ('enabled', 'parallel', 'auto_inspect')
    if not isinstance(options, dict) or any(type(options.get(key, False)) is not bool for key in switches):
        raise ValueError('invalid dispatch switch')
    result = {key: options.get(key, False) for key in switches}
    result['enabled'] = config.get('enabled', False) and result['enabled']
    return result


def dispatch_enabled(root):
    return dispatch_options(root)['enabled']


def enqueue_inspection(queue, task, event):
    return queue.enqueue(task['id'], event['id'], ACTIONS_BY_SOURCE[task['source']],
                         dict(source=event['source'], external_id=event['external_id'],
                              source_payload=event['payload'], task_scope=task['scope'], test_only=False))


def run_once(root, worker_id='local-inspector', *, action=None):
    root = Path(root)
    if action is not None and action not in INSPECTIONS:
        raise ValueError('unsupported inspection action')
    if not dispatch_enabled(root):
        return {'state': 'disabled'}
    if not (state_file(root, 'dispatch.sqlite3')).is_file():
        return {'state': 'idle'}
    with Queue(root) as queue:
        job = queue.claim(worker_id, actions=[action] if action else sorted(INSPECTIONS))
        if job is None:
            return {'state': 'idle'}
        source = INSPECTIONS[job['action']]
        adapter = build_experiment_snapshot if source == 'experiment' else build_pr_snapshot
        snapshot = adapter(root)
        with Hub(root) as hub:
            task = hub.get_task(job['task_id'])
            event = next((item for item in hub.list_events(task_id=job['task_id'])
                          if item['id'] == job['event_id']), None)
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



def run_cycle(root):
    """Run at most one check per lane when parallel operation is enabled."""
    options = dispatch_options(root)
    if not options['enabled']:
        return {'state': 'disabled'}
    if not options['parallel']:
        return run_once(root)

    def run_lane(action):
        try:
            return run_once(root, worker_id=action, action=action)
        except Exception as error:
            # Other lanes still finish. An uncommitted claim can be recovered
            # after its lease expires, with the normal retry cap.
            return {'state': 'error', 'error_type': type(error).__name__}

    with ThreadPoolExecutor(max_workers=len(INSPECTIONS)) as executor:
        results = dict(zip(INSPECTIONS, executor.map(run_lane, INSPECTIONS)))
    states = {result['state'] for result in results.values()}
    if 'error' in states:
        state = 'worker_error'
    else:
        state = 'idle' if states == {'idle'} else 'processed'
    return {'state': state, 'workers': results}
