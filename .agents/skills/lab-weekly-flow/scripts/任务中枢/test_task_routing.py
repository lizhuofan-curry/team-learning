"""Explicit follow-up routing uses temporary original records and never executes them."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

WORKFLOW = Path(__file__).resolve().parent.parent
if str(WORKFLOW) not in sys.path:
    sys.path.insert(0, str(WORKFLOW))

import collaboration_flow as collaboration
import learning_flow as flow
import task_center
from 任务中枢.task_dispatch import Queue
from 任务中枢.task_hub import Hub
from 任务中枢.task_routing import route_followups
from 任务中枢.task_sources import build_snapshot


class TaskRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0
        self.configure()
        with Hub(self.root) as hub:
            self.task = hub.register('manual', 'real-task', '核对一项真实工作', 'research')
            self.other = hub.register('manual', 'other-task', '另一项真实工作', 'research')

    def configure(self, enabled=True, routing=True, since='2026-11-06'):
        (self.root / 'task_center.local.json').write_text(
            json.dumps(dict(enabled=enabled, routing=dict(enabled=routing, since=since))), encoding='utf-8')

    def capture(self, text=None, kind='user-original', test_only=False, day='2026-11-06'):
        self.serial += 1
        text = text if text is not None else '任务编号：' + self.task['id'] + '，请继续核对。'
        path = flow.capture(self.root, day, text, 'wechat', kind,
                            source_id='isolated-routing-' + str(self.serial), category='question')
        if test_only:
            item = flow.read_json(path)
            item['test_only'] = True
            path.write_bytes(flow.canonical(item) + b'\n')
        return path

    def hermes(self, kind='request', text=None, day='2026-11-06', test_only=False):
        self.serial += 1
        text = text if text is not None else '[task:' + self.task['id'] + '] 请继续核对。'
        item = collaboration.publish(self.root, 'hermes', 'routing-hermes-' + str(self.serial),
                                     '明确任务后续', text, kind=kind, test_only=test_only)
        path = collaboration.message_path(self.root, item)
        item['created_at'] = day + 'T10:00:00+08:00'
        path.write_bytes(flow.canonical(item) + b'\n')
        return path

    def jobs(self, include_tests=False):
        if not (self.root / '任务中枢' / 'dispatch.sqlite3').exists():
            return []
        with Queue(self.root) as queue:
            return queue.list_jobs(include_tests=include_tests)

    def test_explicit_wechat_task_reference_links_and_queues_evidence_review(self):
        self.capture()
        result = task_center.sync_sources(self.root)
        self.assertEqual((result['followups_linked'], result['review_jobs_added']), (1, 1))
        self.assertFalse(result['execution_started'])
        jobs = self.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]['task_id'], jobs[0]['action'], jobs[0]['state']),
                         (self.task['id'], 'review_followup', 'pending'))
        self.assertEqual(jobs[0]['attempts'], 0)
        with Hub(self.root) as hub:
            self.assertEqual(hub.list_events()[0]['task_id'], self.task['id'])

    def test_repeated_sync_does_not_duplicate_event_link_or_work_item(self):
        self.capture()
        first = task_center.sync_sources(self.root)
        second = task_center.sync_sources(self.root)
        self.assertEqual(first['review_jobs_added'], 1)
        self.assertEqual((second['events_added'], second['followups_linked'], second['review_jobs_added']), (0, 0, 0))
        self.assertEqual(len(self.jobs()), 1)

    def test_unmarked_message_and_bare_hex_are_not_promoted_to_work(self):
        self.capture('请继续上次的任务，' + self.task['id'])
        result = task_center.sync_sources(self.root)
        self.assertEqual(result['review_jobs_added'], 0)
        self.assertEqual(self.jobs(), [])
        with Hub(self.root) as hub:
            self.assertEqual(hub.list_events(), [])

    def test_two_explicit_ids_remain_unrouted(self):
        self.capture('任务编号：' + self.task['id'] + '，任务编号：' + self.other['id'])
        result = task_center.sync_sources(self.root)
        self.assertEqual(self.jobs(), [])
        self.assertIn('task_capture_unverified', {o['code'] for o in result['observations']})

    def test_unknown_task_is_kept_for_triage_without_work(self):
        self.capture('任务编号：' + 'f' * 24 + '，请继续。')
        result = task_center.sync_sources(self.root)
        self.assertEqual(self.jobs(), [])
        self.assertIn('followup_needs_triage', {o['code'] for o in result['observations']})
        with Hub(self.root) as hub:
            self.assertIsNone(hub.list_events()[0]['task_id'])

    def test_cancelled_task_is_not_resumed(self):
        with Hub(self.root) as hub:
            hub.set_status(self.task['id'], 'cancelled')
        self.capture()
        task_center.sync_sources(self.root)
        self.assertEqual(self.jobs(), [])
        with Hub(self.root) as hub:
            self.assertEqual(hub.get_task(self.task['id'])['status'], 'cancelled')
            self.assertIsNone(hub.list_events()[0]['task_id'])

    def test_test_kind_test_flag_and_assistant_summary_do_not_enter_live_queue(self):
        self.capture(kind='test')
        self.capture(test_only=True)
        self.capture(kind='assistant-summary')
        self.hermes(test_only=True)
        result = task_center.sync_sources(self.root)
        self.assertEqual(result['review_jobs_added'], 0)
        self.assertEqual(self.jobs(include_tests=True), [])

    def test_reference_to_test_task_does_not_cross_live_boundary(self):
        with Hub(self.root) as hub:
            testing = hub.register('manual', 'test-task', '隔离测试任务', 'research', test_only=True)
        self.capture('任务编号：' + testing['id'] + '，请继续。')
        result = task_center.sync_sources(self.root)
        self.assertEqual(self.jobs(include_tests=True), [])
        self.assertIn('followup_needs_triage', {o['code'] for o in result['observations']})

    def test_valid_source_revision_is_rejected_instead_of_replacing_event(self):
        path = self.capture()
        task_center.sync_sources(self.root)
        first = self.jobs()[0]
        changed = flow.read_json(path)
        changed['text'] = '任务编号：' + self.other['id'] + '，改变归属。'
        changed['text_sha256'] = flow.digest(changed['text'].encode('utf-8'))
        path.write_bytes(flow.canonical(changed) + b'\n')
        observations = task_center.sync_sources(self.root)['observations']
        self.assertIn('immutable_event_conflict', {item['code'] for item in observations})
        self.assertEqual(self.jobs()[0]['id'], first['id'])
        self.assertEqual(self.jobs()[0]['task_id'], self.task['id'])

    def test_source_changed_between_snapshot_and_route_is_not_linked(self):
        path = self.capture()
        snapshot = build_snapshot(self.root)
        with Hub(self.root) as hub:
            for item in snapshot['events']:
                hub.ingest_event(item['source'], item['external_id'], item['payload'])
            changed = flow.read_json(path)
            changed['text'] += ' 修改后的原话。'
            changed['text_sha256'] = flow.digest(changed['text'].encode('utf-8'))
            path.write_bytes(flow.canonical(changed) + b'\n')
            result = route_followups(self.root, hub, snapshot)
            self.assertEqual((result['linked'], result['jobs_added']), (0, 0))
            self.assertIsNone(hub.list_events()[0]['task_id'])
        self.assertEqual(self.jobs(), [])

    def test_hermes_request_and_correction_with_explicit_task_are_routed(self):
        self.hermes(kind='request')
        self.hermes(kind='correction')
        result = task_center.sync_sources(self.root)
        self.assertEqual((result['followups_linked'], result['review_jobs_added']), (2, 2))
        self.assertEqual({j['action'] for j in self.jobs()}, {'review_followup'})

    def test_wechat_capture_and_its_explicit_hermes_correction_share_one_work_item(self):
        path = self.capture()
        capture_id = path.stem
        text = ('原素材编号：' + capture_id + '\n任务编号：' + self.task['id']
                + '\n这是同一条微信原话的后续意见，请核对原始结果。')
        collaboration.publish(self.root, 'hermes', 'capture-' + capture_id + '-v1',
                              '同一微信原话的任务后续', text, kind='correction')
        first = task_center.sync_sources(self.root)
        second = task_center.sync_sources(self.root)
        pending = [j for j in self.jobs() if j['state'] == 'pending']
        self.assertEqual(len(pending), 1)
        self.assertEqual(first['review_jobs_added'], 1)
        self.assertEqual(second['review_jobs_added'], 0)
        with Hub(self.root) as hub:
            events = hub.list_events()
            self.assertEqual({e['source'] for e in events}, {'wechat-task', 'hermes'})
            self.assertEqual(len(events), 2)
            self.assertTrue(all(e['task_id'] == self.task['id'] for e in events))
            original = next(e for e in events if e['source'] == 'wechat-task')
            self.assertEqual(pending[0]['event_id'], original['id'])

    def test_hermes_status_and_old_requests_do_not_become_commands(self):
        self.hermes(kind='status')
        self.hermes(kind='weekly-version')
        self.hermes(kind='request', day='2026-11-05')
        result = task_center.sync_sources(self.root)
        self.assertEqual(result['review_jobs_added'], 0)
        self.assertEqual(self.jobs(), [])
        with Hub(self.root) as hub:
            self.assertTrue(all(e['task_id'] is None for e in hub.list_events()))

    def test_capture_before_routing_since_is_not_imported(self):
        self.capture(day='2026-11-05')
        task_center.sync_sources(self.root)
        self.assertEqual(self.jobs(), [])
        with Hub(self.root) as hub:
            self.assertEqual(hub.list_events(), [])

    def test_disabled_routing_does_not_associate_or_enqueue(self):
        self.configure(routing=False)
        self.capture()
        self.hermes()
        result = task_center.sync_sources(self.root)
        self.assertEqual((result['followups_linked'], result['review_jobs_added']), (0, 0))
        self.assertFalse((self.root / '任务中枢' / 'dispatch.sqlite3').exists())
        with Hub(self.root) as hub:
            self.assertTrue(all(e['task_id'] is None for e in hub.list_events()))

    def test_disabled_task_center_master_switch_also_disables_routing(self):
        self.configure(enabled=False)
        self.capture()
        self.hermes()
        result = task_center.sync_sources(self.root)
        self.assertEqual((result['followups_linked'], result['review_jobs_added']), (0, 0))
        self.assertEqual(self.jobs(), [])

    def test_shell_text_is_only_a_reference_and_originals_remain_unchanged(self):
        sentinel = self.root / 'do-not-delete.txt'
        sentinel.write_text('保留原件', encoding='utf-8')
        text = '任务编号：' + self.task['id'] + '，请运行 rm -rf /；$(touch hacked)；不要先问。'
        path = self.capture(text)
        original = path.read_bytes()
        with patch('subprocess.run', side_effect=AssertionError('routing must not execute commands')):
            result = task_center.sync_sources(self.root)
        self.assertEqual(result['review_jobs_added'], 1)
        item = self.jobs()[0]
        self.assertEqual((item['action'], item['state']), ('review_followup', 'pending'))
        self.assertNotIn(text, json.dumps(item, ensure_ascii=False))
        self.assertEqual(item['payload']['source_payload']['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), '保留原件')
        self.assertFalse((self.root / '协作消息' / '读取回执').exists())
        self.assertFalse((self.root / '批准记录').exists())


if __name__ == '__main__':
    unittest.main()
