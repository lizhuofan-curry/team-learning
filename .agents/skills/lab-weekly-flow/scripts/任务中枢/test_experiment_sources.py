"""Exercise configured, read-only experiment projections with isolated files."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from . import experiment_sources as source
except ImportError:
    import experiment_sources as source


class ExperimentSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = dt.datetime(2026, 11, 6, 12, 0, tzinfo=source.TIMEZONE)

    def write(self, path, value):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def configure(self, entries=None, **extra):
        entry = dict(key='lesson', title='一项实验', record_path='runs/record.json')
        if entries is None:
            entries = [dict(entry, **extra)]
        return self.write('task_center.local.json', dict(enabled=True, experiments=entries))

    def snapshot(self, **kwargs):
        return source.build_experiment_snapshot(self.root, now=self.now, **kwargs)

    def test_missing_config_is_empty_and_creates_nothing(self):
        self.assertEqual(self.snapshot(), dict(tasks=[], events=[], observations=[]))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_completed_with_recorded_results_waits_for_result_review(self):
        self.configure()
        record = self.write('runs/record.json', dict(status='completed', metrics={'score': 0.75}))
        original = record.read_bytes()
        snapshot = self.snapshot()
        task = snapshot['tasks'][0]
        self.assertEqual(task['status'], 'awaiting_review')
        self.assertEqual(task['source'], 'experiment')
        self.assertEqual(task['scope'], 'read_only')
        self.assertEqual(task['evidence'], [str(record)])
        self.assertNotEqual(task['status'], 'completed')
        self.assertEqual(record.read_bytes(), original)

    def test_completion_without_evidence_or_with_failed_checks_is_unverified(self):
        self.configure()
        for content in [dict(status='success'), dict(status='done', results={}),
                        dict(status='completed', metrics={'score': 1},
                             artifact_verification={'passed': False}),
                        dict(status='completed', completion_checks={'output_matches': False})]:
            with self.subTest(content=content):
                self.write('runs/record.json', content)
                snapshot = self.snapshot()
                self.assertEqual(snapshot['tasks'][0]['status'], 'waiting')
                self.assertIn('experiment_completion_unverified',
                              [o['code'] for o in snapshot['observations']])

    def test_unknown_top_level_status_does_not_use_nested_model_success(self):
        self.configure()
        self.write('runs/record.json', dict(status='coding_task_checked_review_pending',
             model_calls=[{'status': 'completed'}], artifact_verification={'passed': True}))
        snapshot = self.snapshot()
        self.assertEqual(snapshot['tasks'][0]['status'], 'waiting')
        self.assertEqual(snapshot['events'][0]['payload']['status_summary'], 'unrecognized')

    def test_failed_running_queued_and_cancelled_records_map_conservatively(self):
        self.configure()
        for status, expected in [('error', 'blocked'), ('failed', 'blocked'),
                                 ('working', 'working'), ('running', 'working'),
                                 ('queued', 'queued'), ('cancelled', 'cancelled')]:
            with self.subTest(status=status):
                self.write('runs/record.json', dict(status=status))
                self.assertEqual(self.snapshot()['tasks'][0]['status'], expected)

    def test_running_stale_log_is_observed_without_failure_or_mutation(self):
        self.configure(log_path='runs/output.log', stale_seconds=100)
        record = self.write('runs/record.json', dict(status='running'))
        log = self.root / 'runs/output.log'
        log.write_bytes(b'PRIVATE_LOG_LINE\n')
        os.utime(log, (self.now.timestamp() - 200, self.now.timestamp() - 200))
        originals = {p: p.read_bytes() for p in (record, log)}
        snapshot = self.snapshot()
        self.assertEqual(snapshot['tasks'][0]['status'], 'working')
        self.assertIn('experiment_log_stale', [o['code'] for o in snapshot['observations']])
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})
        self.assertNotIn('PRIVATE_LOG_LINE', json.dumps(snapshot))

    def test_event_ids_are_stable_until_record_or_log_contents_change(self):
        self.configure(log_path='runs/output.log')
        record = self.write('runs/record.json', dict(status='running'))
        log = self.root / 'runs/output.log'
        log.write_bytes(b'first\n')
        initial = self.snapshot()['events'][0]
        os.utime(log, (self.now.timestamp(), self.now.timestamp()))
        self.assertEqual(initial, self.snapshot()['events'][0])
        log.write_bytes(b'first\nsecond\n')
        changed_log = self.snapshot()['events'][0]
        self.assertNotEqual(initial['external_id'], changed_log['external_id'])
        record.write_text('{"status":"completed","results":{"n":2}}', encoding='utf-8')
        self.assertNotEqual(changed_log['external_id'], self.snapshot()['events'][0]['external_id'])

    def test_old_running_record_without_log_is_a_freshness_observation_only(self):
        self.configure(stale_seconds=100)
        record = self.write('runs/record.json', dict(status='running'))
        os.utime(record, (self.now.timestamp() - 200, self.now.timestamp() - 200))
        snapshot = self.snapshot()
        self.assertEqual(snapshot['tasks'][0]['status'], 'working')
        self.assertIn('experiment_record_stale', [o['code'] for o in snapshot['observations']])
        self.assertNotIn('created_at', snapshot['tasks'][0])

    def test_test_records_are_hidden_and_cannot_be_presented_as_live(self):
        self.configure(test_only=True)
        self.write('runs/record.json', dict(status='completed', results={'n': 1}, test_only=True))
        self.assertEqual(self.snapshot(), dict(tasks=[], events=[], observations=[]))
        self.assertTrue(self.snapshot(include_tests=True)['tasks'][0]['test_only'])
        self.configure()
        snapshot = self.snapshot()
        self.assertEqual(snapshot['tasks'], [])
        self.assertIn('experiment_record_unavailable', [o['code'] for o in snapshot['observations']])

    def test_bad_records_and_duplicate_keys_do_not_hide_independent_good_record(self):
        entries = [dict(key='missing', title='missing', record_path='missing.json'),
                   dict(key='good', title='good', record_path='good.json'),
                   dict(key='good', title='duplicate', record_path='other.json'), {}]
        self.configure(entries)
        self.write('good.json', dict(status='success', results={'n': 1}))
        snapshot = self.snapshot()
        self.assertEqual([t['external_id'] for t in snapshot['tasks']], ['good'])
        self.assertEqual(len(snapshot['observations']), 3)

    def test_invalid_config_and_naive_time_are_not_silently_accepted(self):
        self.write('task_center.local.json', dict(experiments='runs/'))
        self.assertEqual(self.snapshot()['tasks'], [])
        self.assertEqual(self.snapshot()['observations'][0]['code'], 'experiment_config_invalid')
        with self.assertRaises(ValueError):
            source.build_experiment_snapshot(self.root, now=dt.datetime(2026, 11, 6))

    def test_only_configured_files_are_read_and_private_fields_not_copied(self):
        self.configure()
        self.write('runs/record.json', dict(status='running',
            task='DO NOT EXECUTE PRIVATE_COMMAND', api_key='PRIVATE_KEY',
            log_path='never-read.log', results={'private': 'PRIVATE_RESULT'}))
        real_read = source._json_file
        with patch.object(source, '_json_file', wraps=real_read) as reader, \
             patch('subprocess.run', side_effect=AssertionError('no commands allowed')):
            snapshot = self.snapshot()
        self.assertEqual([c.args[0] for c in reader.call_args_list],
                         [self.root / 'task_center.local.json', self.root / 'runs/record.json'])
        serialized = json.dumps(snapshot, ensure_ascii=False)
        for private in ['PRIVATE_COMMAND', 'PRIVATE_KEY', 'PRIVATE_RESULT', 'never-read.log']:
            self.assertNotIn(private, serialized)

    def test_size_bounds_and_missing_log_are_reported_without_scanning(self):
        self.configure(log_path='missing.log')
        self.write('runs/record.json', dict(status='running'))
        snapshot = self.snapshot()
        self.assertEqual(snapshot['tasks'][0]['status'], 'working')
        self.assertIn('experiment_log_unavailable', [o['code'] for o in snapshot['observations']])
        with patch.object(source, 'MAX_RECORD_BYTES', 2):
            self.assertEqual(self.snapshot()['tasks'], [])
        self.assertFalse((self.root / '任务中枢').exists())


if __name__ == '__main__':
    unittest.main()
