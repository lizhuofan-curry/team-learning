"""Read-only PR projection checks against explicitly watched local snapshots."""
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

WORKFLOW = Path(__file__).resolve().parent.parent
if str(WORKFLOW) not in sys.path:
    sys.path.insert(0, str(WORKFLOW))
try:
    from . import pr_sources as source
except ImportError:
    import pr_sources as source


class PullRequestSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = dt.datetime(2026, 11, 6, 12, 0, tzinfo=source.TIMEZONE)
        self.repository = 'example/research'
        self.number = 27

    def config(self, entries=None):
        if entries is None:
            entries = [dict(repository=self.repository, number=self.number)]
        path = self.root / 'task_center.local.json'
        path.write_text(json.dumps(dict(pull_requests=entries)), encoding='utf-8')
        return path

    def record(self, **changes):
        value = dict(version=1, repository=self.repository, number=self.number,
                     state='open', merged=False, draft=False, head_sha='a' * 40,
                     fetched_at=self.now.isoformat(), updated_at=self.now.isoformat(),
                     checks=[], test_only=False)
        value.update(changes)
        return value

    def check(self, head='a', conclusion='success', status='completed'):
        return dict(name='quality-check', status=status, conclusion=conclusion, head_sha=head * 40)

    def save(self, **changes):
        self.config()
        return source.save_snapshot(self.root, self.record(**changes))

    def snapshot(self, **kwargs):
        return source.build_pr_snapshot(self.root, now=self.now, **kwargs)

    def test_current_head_failed_check_blocks_without_claiming_merge(self):
        self.save(checks=[self.check(conclusion='failure')])
        result = self.snapshot()
        self.assertEqual(result['tasks'][0]['status'], 'blocked')
        self.assertIn('pr_checks_failed', [o['code'] for o in result['observations']])

    def test_old_head_failure_does_not_override_current_head_success(self):
        self.save(checks=[self.check(head='b', conclusion='failure'), self.check()])
        result = self.snapshot()
        self.assertEqual(result['tasks'][0]['status'], 'awaiting_review')
        self.assertNotIn('pr_checks_failed', [o['code'] for o in result['observations']])

    def test_old_head_success_does_not_hide_current_head_failure(self):
        self.save(checks=[self.check(head='b'), self.check(conclusion='timed_out')])
        self.assertEqual(self.snapshot()['tasks'][0]['status'], 'blocked')

    def test_running_current_head_check_waits_for_actual_result(self):
        self.save(checks=[self.check(status='in_progress', conclusion=None)])
        self.assertEqual(self.snapshot()['tasks'][0]['status'], 'waiting')

    def test_merged_closed_and_draft_have_distinct_meanings(self):
        for changes, expected in [(dict(state='closed', merged=True), 'completed'),
                                  (dict(state='closed', merged=False), 'waiting'),
                                  (dict(draft=True), 'awaiting_review')]:
            with self.subTest(changes=changes):
                self.save(**changes)
                task = self.snapshot()['tasks'][0]
                self.assertEqual(task['status'], expected)
                self.assertEqual(task['scope'], 'read_only')
                self.assertTrue(task['evidence'])

    def test_stale_or_future_snapshot_does_not_claim_current_remote_state(self):
        for delta in [-901, 61]:
            with self.subTest(delta=delta):
                fetched = (self.now + dt.timedelta(seconds=delta)).isoformat()
                self.save(state='closed', merged=True, fetched_at=fetched)
                result = self.snapshot()
                self.assertEqual(result['tasks'][0]['status'], 'waiting')
                self.assertIn('pr_snapshot_stale', [o['code'] for o in result['observations']])

    def test_save_requires_explicit_allowlist_and_rejects_bad_identities(self):
        with self.assertRaises(ValueError):
            source.save_snapshot(self.root, self.record())
        self.assertFalse((self.root / '任务中枢').exists())
        self.config([dict(repository='other/repository', number=self.number)])
        with self.assertRaises(ValueError):
            source.save_snapshot(self.root, self.record())
        for repository, number in [('example/research/other', 2), ('example/research', True)]:
            with self.subTest(repository=repository, number=number), self.assertRaises(ValueError):
                source.identity(repository, number)

    def test_snapshot_body_and_comments_are_rejected_instead_of_indexed(self):
        self.config()
        for field in ['body', 'comments', 'raw_response']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                source.save_snapshot(self.root, self.record(**{field: 'PRIVATE_RAW_BODY'}))
        self.assertFalse((self.root / '任务中枢').exists())
        path = self.save(checks=[self.check()])
        result = self.snapshot()
        payload = result['events'][0]['payload']
        self.assertEqual(set(payload), {'reference', 'sha256', 'head_sha', 'test_only'})
        self.assertEqual(payload['reference'], str(path))

    def test_build_preserves_source_bytes_and_unchanged_event_identity(self):
        path = self.save(checks=[self.check()])
        config_path = self.root / 'task_center.local.json'
        before = {p: p.read_bytes() for p in (path, config_path)}
        with patch('subprocess.run', side_effect=AssertionError('read view must not call network or commands')):
            first = self.snapshot()
            second = self.snapshot()
        self.assertEqual(first, second)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse((self.root / '协作消息').exists())

    def test_test_snapshots_are_hidden_by_default(self):
        self.config([dict(repository=self.repository, number=self.number, test_only=True)])
        source.save_snapshot(self.root, self.record(test_only=True))
        self.assertEqual(self.snapshot(), dict(tasks=[], events=[], observations=[]))
        included = self.snapshot(include_tests=True)
        self.assertTrue(included['tasks'][0]['test_only'])
        self.assertTrue(included['events'][0]['payload']['test_only'])

    def test_missing_or_wrong_identity_snapshot_is_unavailable(self):
        self.config()
        result = self.snapshot()
        self.assertEqual(result['tasks'], [])
        self.assertEqual(result['observations'][0]['code'], 'pr_snapshot_unavailable')
        path = source.snapshot_path(self.root, self.repository, self.number)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(self.record(number=99)), encoding='utf-8')
        self.assertEqual(self.snapshot()['tasks'], [])

    def test_non_object_or_duplicate_configuration_is_controlled(self):
        path = self.root / 'task_center.local.json'
        for raw in ['[]', 'null']:
            with self.subTest(raw=raw):
                path.write_text(raw, encoding='utf-8')
                self.assertEqual(self.snapshot()['observations'][0]['code'], 'pr_config_invalid')
                with self.assertRaises(ValueError):
                    source.save_snapshot(self.root, self.record())
        self.config([dict(repository=self.repository, number=self.number)] * 2)
        self.assertEqual(self.snapshot()['observations'][0]['code'], 'pr_config_invalid')

    def test_deeply_nested_snapshot_is_reported_without_escaping(self):
        self.config()
        path = source.snapshot_path(self.root, self.repository, self.number)
        path.parent.mkdir(parents=True)
        path.write_text('{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}', encoding='utf-8')
        result = self.snapshot()
        self.assertEqual(result['tasks'], [])
        self.assertEqual(result['observations'][0]['code'], 'pr_snapshot_unavailable')

    def test_snapshot_directory_link_cannot_cross_workflow(self):
        self.config()
        other = self.root / 'other-workflow'
        other.mkdir()
        folder = self.root / '任务中枢'
        folder.mkdir()
        link = folder / 'pr_snapshots'
        try:
            link.symlink_to(other, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f'symlinks unavailable: {error}')
        with self.assertRaises(ValueError):
            source.save_snapshot(self.root, self.record())
        self.assertEqual(list(other.iterdir()), [])
        result = self.snapshot()
        self.assertEqual(result['tasks'], [])
        self.assertEqual(result['observations'][0]['code'], 'pr_snapshot_unavailable')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO unavailable')
    def test_named_pipe_snapshot_is_rejected_before_open(self):
        self.config()
        path = source.snapshot_path(self.root, self.repository, self.number)
        path.parent.mkdir(parents=True)
        os.mkfifo(path)
        with patch.object(Path, 'open', side_effect=AssertionError('must reject FIFO before opening')):
            with self.assertRaises(ValueError):
                source.read_json(path)

    def test_oversized_snapshot_is_read_with_a_bounded_budget(self):
        class BoundedReader(io.BytesIO):
            def read(inner_self, size=-1):
                if not 0 <= size <= 1_000_001:
                    raise AssertionError('snapshot reader requested an unbounded read')
                return super().read(size)
        (self.root / 'large.json').touch()
        with patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'open', return_value=BoundedReader(b' ' * 1_000_001)):
            with self.assertRaises(ValueError):
                source.read_json(self.root / 'large.json')


if __name__ == '__main__':
    unittest.main()
