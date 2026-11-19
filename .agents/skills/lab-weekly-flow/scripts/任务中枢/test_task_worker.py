"""Integration tests for versioned, independent inspection lanes."""
import datetime as dt
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import task_center
import collaboration_flow as collaboration
from 任务中枢 import task_worker
from 任务中枢.pr_sources import save_snapshot
from 任务中枢.task_dispatch import Queue
from 任务中枢.task_hub import Hub


class WorkerCycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.record = self.root / 'record.json'
        self.record.write_text('{"status": "running"}', encoding='utf-8')
        self.config = {
            'enabled': True,
            'dispatch': {'enabled': True, 'parallel': True, 'auto_inspect': True},
            'experiments': [{'key': 'run-a', 'title': 'Experiment A', 'record_path': 'record.json'}],
            'pull_requests': [{'repository': 'example/project-b', 'number': 7}],
        }
        self.write_config()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.pr = dict(version=1, repository='example/project-b', number=7,
                       state='open', merged=False, draft=True, head_sha='a' * 40,
                       updated_at=now, fetched_at=now, checks=[])
        save_snapshot(self.root, self.pr)

    def write_config(self):
        (self.root / 'task_center.local.json').write_text(json.dumps(self.config), encoding='utf-8')

    def test_manual_inspection_uses_own_source_after_newer_linked_hermes_event(self):
        self.config['dispatch']['auto_inspect'] = False
        self.write_config()
        task_center.sync_sources(self.root)
        with Hub(self.root) as hub:
            tasks = hub.list_tasks()
        for task in tasks:
            with self.subTest(source=task['source']):
                message = collaboration.publish(self.root, 'hermes', 'status-' + task['source'],
                                                '隔离状态', '只读关联更新', kind='status')
                task_center.sync_sources(self.root)
                with Hub(self.root) as hub:
                    event = next(e for e in hub.list_events() if e['external_id'] == message['id'])
                    hub.link_event(event['id'], task['id'])
                with Queue(self.root) as queue:
                    with self.assertRaisesRegex(ValueError, 'must match'):
                        task_worker.enqueue_inspection(queue, task, event)
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    task_center.main(['--root', str(self.root), 'queue-inspection', '--task', task['id']])
                queued = json.loads(stream.getvalue())
                self.assertEqual(queued['payload']['source'], task['source'])
                result = task_worker.run_once(self.root, action=queued['action'])
                self.assertEqual(result['state'], 'completed')

    def test_two_lanes_overlap_and_each_version_gets_one_receipt(self):
        self.assertEqual(task_center.sync_sources(self.root)['inspection_jobs_added'], 2)
        self.assertEqual(task_center.sync_sources(self.root)['inspection_jobs_added'], 0)
        barrier = threading.Barrier(2)

        def concurrently(adapter):
            def inspect(root):
                barrier.wait(timeout=5)
                return adapter(root)
            return inspect

        with patch.object(task_worker, 'build_experiment_snapshot',
                          concurrently(task_worker.build_experiment_snapshot)), patch.object(
            task_worker, 'build_pr_snapshot', concurrently(task_worker.build_pr_snapshot)
        ):
            result = task_worker.run_cycle(self.root)
        self.assertEqual({k: v['state'] for k, v in result['workers'].items()},
                         {'inspect_experiment': 'completed', 'inspect_pr': 'completed'})
        with Queue(self.root) as queue:
            jobs = queue.list_jobs()
            self.assertEqual(len(jobs), 2)
            self.assertEqual({job['action']: job['worker_id'] for job in jobs},
                             {action: action for action in task_worker.INSPECTIONS})
        self.assertEqual(task_worker.run_cycle(self.root)['state'], 'idle')

    def test_lane_recovers_abandoned_claim_without_touching_other_lane(self):
        task_center.sync_sources(self.root)
        past = time.time() - 200
        with Queue(self.root, now=past) as queue:
            # Place the fixture's due timestamps before a simulated crash.
            queue.connection.execute('UPDATE jobs SET next_attempt_at=?', (past,))
            abandoned = queue.claim('crashed-worker', lease_seconds=1, actions=['inspect_experiment'])
        with Queue(self.root, now=past + 2, retry_delay_seconds=0) as queue:
            self.assertEqual(queue.recover_expired()['requeued'], 1)
        result = task_worker.run_cycle(self.root)
        self.assertEqual(result['workers']['inspect_experiment']['job_id'], abandoned['id'])
        with Queue(self.root) as queue:
            receipts = queue.list_receipts(abandoned['id'])
            self.assertEqual([item['kind'] for item in receipts],
                             ['enqueued', 'claimed', 'lease_expired', 'claimed', 'completed'])
            with self.assertRaises(ValueError):
                queue.complete(abandoned['id'], abandoned['lease_token'], {})

    def test_stale_pr_is_not_auto_queued_and_failure_leaves_other_lane_usable(self):
        self.pr['fetched_at'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
        save_snapshot(self.root, self.pr)
        self.assertEqual(task_center.sync_sources(self.root)['inspection_jobs_added'], 1)
        with patch.object(task_worker, 'build_experiment_snapshot', side_effect=OSError('read failed')):
            result = task_worker.run_cycle(self.root)
        self.assertEqual(result['workers']['inspect_pr']['state'], 'idle')
        self.assertEqual(result['workers']['inspect_experiment'], {'state': 'error', 'error_type': 'OSError'})
