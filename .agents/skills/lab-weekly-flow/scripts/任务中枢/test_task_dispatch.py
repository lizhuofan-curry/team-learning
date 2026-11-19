"""Isolated durable dispatch tests; no worker command or model is launched."""
import datetime as dt
from pathlib import Path
import tempfile
import unittest

try:
    from .task_dispatch import Queue
except ImportError:
    from task_dispatch import Queue


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = [1000.0]
        self.queue = Queue(self.root, now=lambda: self.clock[0])
        self.addCleanup(self.queue.close)

    def enqueue(self, event='b' * 24, **kwargs):
        return self.queue.enqueue('a' * 24, event, 'review_followup',
                                  {'reference': 'original-message.json'}, **kwargs)

    def test_enqueue_is_immutable_and_does_not_execute(self):
        first = self.enqueue()
        self.assertEqual(first['state'], 'pending')
        self.assertEqual(first['attempts'], 0)
        self.assertFalse(first['receipt']['data']['execution_started'])
        self.assertEqual(self.enqueue()['id'], first['id'])
        self.assertEqual(len(self.queue.list_jobs()), 1)
        with self.assertRaises(ValueError):
            self.queue.enqueue('a' * 24, 'b' * 24, 'review_followup', {'reference': 'other'})

    def test_only_allowlisted_actions_and_valid_metadata_enter_queue(self):
        for action in ('bash', 'send_message', 'run_model', 'approve_review'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.queue.enqueue('a' * 24, 'b' * 24, action, {})
        for data in ([], {'number': float('nan')}, {'too_large': 'x' * 130000}):
            with self.subTest(data_type=type(data).__name__), self.assertRaises(ValueError):
                self.queue.enqueue('a' * 24, 'b' * 24, 'inspect_pr', data)
        self.assertEqual(self.queue.list_jobs(), [])

    def test_one_worker_owns_a_job_across_connections(self):
        self.enqueue()
        with Queue(self.root, now=lambda: self.clock[0]) as second:
            claimed = self.queue.claim('worker-one')
            self.assertEqual(claimed['state'], 'running')
            self.assertEqual(claimed['attempts'], 1)
            self.assertIsNone(second.claim('worker-two'))
            self.assertIsNone(second.list_jobs()[0]['lease_token'])
            with self.assertRaises(ValueError):
                second.complete(claimed['id'], '0' * 32, {'checked': True})
            result = second.complete(claimed['id'], claimed['lease_token'], {'checked': True})
            self.assertEqual(result['state'], 'completed')

    def test_completion_receipt_survives_restart_and_is_idempotent(self):
        self.enqueue()
        claimed = self.queue.claim('reader')
        result = self.queue.complete(claimed['id'], claimed['lease_token'], {'source_verified': True})
        with Queue(self.root, now=lambda: self.clock[0]) as reopened:
            replay = reopened.complete(claimed['id'], claimed['lease_token'], {'source_verified': True})
            self.assertEqual(replay['receipt'], result['receipt'])
            self.assertEqual([r['kind'] for r in reopened.list_receipts(claimed['id'])],
                             ['enqueued', 'claimed', 'completed'])
            with self.assertRaises(ValueError):
                reopened.complete(claimed['id'], claimed['lease_token'], {'source_verified': False})
            self.assertIsNone(reopened.claim('again'))

    def test_expired_worker_cannot_commit_before_or_after_reclaim(self):
        self.enqueue()
        old = self.queue.claim('old', lease_seconds=10)
        self.clock[0] += 10
        with self.assertRaises(ValueError):
            self.queue.complete(old['id'], old['lease_token'], {})
        recovered = self.queue.recover_expired()
        self.assertEqual(recovered, {'requeued': 1, 'failed': 0})
        self.assertIsNone(self.queue.claim('too-soon'))
        self.clock[0] += 30
        current = self.queue.claim('new')
        self.assertNotEqual(current['lease_token'], old['lease_token'])
        self.assertEqual(current['attempts'], 2)
        with self.assertRaises(ValueError):
            self.queue.complete(old['id'], old['lease_token'], {})
        self.assertEqual(self.queue.complete(current['id'], current['lease_token'], {})['state'], 'completed')

    def test_expiration_exhaustion_is_persistent_after_three_claims(self):
        item = self.enqueue()
        for index in range(3):
            claimed = self.queue.claim('worker', lease_seconds=1)
            self.assertEqual(claimed['attempts'], index + 1)
            self.clock[0] += 1
            result = self.queue.recover_expired()
            self.clock[0] += 30
        self.assertEqual(result, {'requeued': 0, 'failed': 1})
        with Queue(self.root, now=lambda: self.clock[0]) as reopened:
            self.assertIsNone(reopened.claim('fourth'))
            self.assertEqual(reopened.list_jobs()[0]['state'], 'failed')
            self.assertEqual(reopened.list_jobs()[0]['id'], item['id'])

    def test_failure_retries_are_delayed_deduplicated_and_bounded(self):
        self.enqueue()
        for index in range(3):
            claim = self.queue.claim('worker')
            result = self.queue.fail(claim['id'], claim['lease_token'], 'source_unavailable')
            self.assertEqual(result['state'], 'failed' if index == 2 else 'pending')
            self.assertEqual(self.queue.fail(claim['id'], claim['lease_token'], 'source_unavailable')['receipt'],
                             result['receipt'])
            self.assertIsNone(self.queue.claim('too-soon'))
            self.clock[0] += 30
        self.assertIsNone(self.queue.claim('fourth'))

    def test_cancellation_invalidates_active_worker_and_cannot_be_undone_by_enqueue(self):
        self.enqueue()
        claim = self.queue.claim('worker')
        cancelled = self.queue.cancel(claim['id'])
        self.assertEqual(cancelled['state'], 'cancelled')
        self.assertEqual(self.queue.cancel(claim['id'])['receipt'], cancelled['receipt'])
        with self.assertRaises(ValueError):
            self.queue.complete(claim['id'], claim['lease_token'], {})
        with self.assertRaises(ValueError):
            self.queue.fail(claim['id'], claim['lease_token'], 'late')
        self.assertEqual(self.enqueue()['state'], 'cancelled')
        self.assertIsNone(self.queue.claim('worker'))

    def test_test_lane_cannot_be_claimed_completed_or_cancelled_by_live_worker(self):
        item = self.enqueue(test_only=True)
        self.assertEqual(self.queue.list_jobs(), [])
        self.assertIsNone(self.queue.claim('live'))
        with Queue(self.root, now=lambda: self.clock[0], test_only=True) as testing:
            claim = testing.claim('test')
            self.assertEqual(claim['id'], item['id'])
            with self.assertRaises(ValueError):
                self.queue.complete(claim['id'], claim['lease_token'], {})
            with self.assertRaises(ValueError):
                self.queue.cancel(claim['id'])
            self.assertEqual(testing.complete(claim['id'], claim['lease_token'], {})['state'], 'completed')
        with self.assertRaises(ValueError):
            self.enqueue(test_only=False)
        self.assertEqual(len(self.queue.list_jobs(include_tests=True)), 1)

    def test_expiry_recovery_stays_in_its_own_lane(self):
        self.enqueue(test_only=True)
        with Queue(self.root, now=lambda: self.clock[0], test_only=True) as testing:
            claim = testing.claim('test', lease_seconds=1)
            self.clock[0] += 1
            self.assertEqual(self.queue.recover_expired(), {'requeued': 0, 'failed': 0})
            self.assertEqual(testing.recover_expired(), {'requeued': 1, 'failed': 0})
            self.assertEqual(testing.list_jobs(include_tests=True)[0]['id'], claim['id'])

    def test_explicit_aware_time_and_invalid_clock_are_checked(self):
        self.enqueue()
        claim = self.queue.claim('worker', lease_seconds=1)
        now = dt.datetime.fromtimestamp(1001, dt.timezone.utc)
        self.assertEqual(self.queue.recover_expired(now=now), {'requeued': 1, 'failed': 0})
        with self.assertRaises(ValueError):
            self.queue.recover_expired(now=dt.datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            self.queue.claim('worker', lease_seconds=True)
        self.assertEqual(self.queue.list_jobs()[0]['id'], claim['id'])

    def test_identity_and_test_metadata_conflicts_do_not_create_partial_work(self):
        with self.assertRaises(ValueError):
            self.queue.enqueue('../bad', 'b' * 24, 'inspect_pr', {})
        with self.assertRaises(ValueError):
            self.queue.enqueue('a' * 24, 'b' * 24, 'inspect_pr', {'test_only': True})
        self.assertEqual(self.queue.list_jobs(include_tests=True), [])


if __name__ == '__main__':
    unittest.main()
