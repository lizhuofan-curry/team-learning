"""Recovery tests use frozen synthetic packets and never contact a network."""
import base64
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

WORKFLOW = Path(__file__).resolve().parent.parent
if str(WORKFLOW) not in sys.path:
    sys.path.insert(0, str(WORKFLOW))
try:
    from . import task_recovery as recovery
except ImportError:
    import task_recovery as recovery
media = recovery.media


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('media.local.json', dict(enabled=True, since='2026-11-06', grace_seconds=0,
                                           lease_seconds=100, max_attempts=2))
        self.write('collaboration.local.json', dict(mode='local', role='codex'))
        self.configure()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def configure(self, **options):
        values = dict(enabled=True, max_per_tick=1, max_automatic_attempts=2,
                      cooldown_seconds=900, allowed_actions=['reclaim_expired', 'retry_delivery'])
        values.update(options)
        self.write('task_center.local.json', dict(enabled=True, recovery=values))

    def job(self, name='article', test_only=False):
        url = 'https://example.com/' + name
        record = media.request(self.root, url, 'isolated-test', test_only=test_only)
        claimed = media.claim(self.root, record['id'])
        directory = self.root / '媒体结果' / 'web' / name
        directory.mkdir(parents=True)
        text = '只用于隔离验证的正文。'.encode('utf-8')
        (directory / 'content.md').write_bytes(text)
        self.write(str((directory / 'result.json').relative_to(self.root)), dict(
            schema_version=1, platform='web', resource_id=name, canonical_url=url,
            source_url=url, status='article_ready', content_source=['isolated-fixture'],
            text_file=dict(path='content.md', sha256=hashlib.sha256(text).hexdigest()),
            test_only=test_only, visual_verified=False))
        return media.finish(self.root, record['id'], claimed['lease_token'], directory=directory)

    def source_bytes(self):
        return {str(p): p.read_bytes() for p in (self.root / '媒体队列').rglob('*') if p.is_file()}

    def codes(self, result):
        return {o['code'] for o in result['observations']}

    def test_plan_only_reads_and_uses_fixed_packet(self):
        self.job()
        before = self.source_bytes()
        with patch.object(media, 'push', side_effect=AssertionError('no execution in plan')):
            plan = recovery.plan_recovery(self.root, now=1000)
        self.assertEqual(len(plan['actions']), 1)
        self.assertEqual(before, self.source_bytes())
        self.assertFalse((self.root / '任务中枢').exists())

    def test_legacy_adapter_does_not_consume_recovery_attempt(self):
        self.job()
        plan = recovery.plan_recovery(self.root)
        original = media.push

        def legacy_push(root, identifier):
            raise AssertionError('legacy push must not run')

        with patch.object(media, 'push', legacy_push):
            result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('recovery_adapter_incompatible', self.codes(result))
        self.assertEqual(recovery._read_ledger(self.root), [])
        self.assertEqual(len(recovery.plan_recovery(self.root)['actions']), 1)
        with patch.object(media, 'push', wraps=original):
            delivered = recovery.apply_recovery(self.root, plan)
        self.assertEqual(delivered['outcomes'][0]['outcome'], 'delivered')

    def test_external_record_directory_is_not_read_for_recovery(self):
        job = self.job()
        folder = self.root / '媒体队列' / '任务'
        with tempfile.TemporaryDirectory() as other:
            external = Path(other) / '任务'
            folder.rename(external)
            try:
                folder.symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                external.rename(folder)
                self.skipTest(f'symlinks unavailable: {error}')
            plan = recovery.plan_recovery(self.root)
            self.assertEqual(plan['actions'], [])
            self.assertIn('recovery_source_or_packet_invalid', self.codes(plan))
            self.assertTrue((external / (job['id'] + '.json')).exists())
            if os.name == 'nt':
                folder.rmdir()
            else:
                folder.unlink()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO unavailable')
    def test_nonregular_record_does_not_block_recovery_plan(self):
        job = self.job()
        path = media.path_for(self.root, job['id'])
        path.unlink()
        os.mkfifo(path)
        result = subprocess.run(
            [sys.executable, str(WORKFLOW / 'task_center.py'), '--root', str(self.root), 'recovery-plan'],
            capture_output=True, check=True, timeout=10)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['actions'], [])
        self.assertIn('recovery_source_or_packet_invalid', self.codes(plan))

    def test_disabled_apply_does_not_create_ledger_or_call_push(self):
        self.job()
        self.configure(enabled=False)
        plan = recovery.plan_recovery(self.root)
        self.assertEqual(len(plan['actions']), 1)
        with patch.object(media, 'push', side_effect=AssertionError('disabled recovery')):
            result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertFalse((self.root / '任务中枢').exists())

    def test_paused_original_media_queue_is_not_restarted(self):
        self.job()
        plan = recovery.plan_recovery(self.root)
        self.write('media.local.json', dict(enabled=False))
        with patch.object(media, 'push', side_effect=AssertionError('paused queue')):
            result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('media_queue_disabled', self.codes(result))
        self.assertEqual(recovery.plan_recovery(self.root)['actions'], [])
        self.assertFalse((self.root / '任务中枢').exists())

    def test_task_center_master_switch_cannot_be_bypassed_by_direct_apply(self):
        self.job()
        plan = recovery.plan_recovery(self.root)
        config = json.loads((self.root / 'task_center.local.json').read_text(encoding='utf-8'))
        config['enabled'] = False
        self.write('task_center.local.json', config)
        with patch.object(media, 'push', side_effect=AssertionError('master switch off')):
            result = recovery.apply_recovery(self.root, plan)
        self.assertFalse(result['enabled'])
        self.assertEqual(result['attempted'], 0)
        self.assertFalse((self.root / '任务中枢').exists())

    def test_switch_closed_while_waiting_for_recovery_lock_stops_before_database(self):
        self.job()
        plan = recovery.plan_recovery(self.root)

        @contextlib.contextmanager
        def paused_lock(root):
            self.configure(enabled=False)
            yield

        with patch.object(recovery, '_locked', paused_lock):
            with patch.object(media, 'push', side_effect=AssertionError('disabled while waiting')):
                result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('recovery_disabled', self.codes(result))
        self.assertFalse((self.root / '任务中枢').exists())

    def test_changed_policy_while_waiting_for_lock_stops_without_outside_effect(self):
        self.job()
        plan = recovery.plan_recovery(self.root)

        @contextlib.contextmanager
        def changed_lock(root):
            self.configure(cooldown_seconds=30)
            yield

        with patch.object(recovery, '_locked', changed_lock):
            with patch.object(media, 'push', side_effect=AssertionError('policy changed')):
                result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('recovery_policy_changed', self.codes(result))

    def test_switch_closed_after_source_check_stops_before_push(self):
        self.job()
        plan = recovery.plan_recovery(self.root)
        verify_packet = recovery._delivery_packet

        def pause_after_check(root, record):
            value = verify_packet(root, record)
            self.configure(enabled=False)
            return value

        with patch.object(recovery, '_delivery_packet', pause_after_check):
            with patch.object(media, 'push', side_effect=AssertionError('disabled after source check')):
                result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('recovery_disabled', self.codes(result))
        self.assertEqual(recovery._read_ledger(self.root), [])

    def test_switch_closed_during_first_delivery_prevents_second_delivery(self):
        self.job('one'); self.job('two')
        self.configure(max_per_tick=2)
        plan = recovery.plan_recovery(self.root)
        original_push = media.push

        def pause_after_push(*args, **kwargs):
            value = original_push(*args, **kwargs)
            self.configure(enabled=False, max_per_tick=2)
            return value

        with patch.object(media, 'push', side_effect=pause_after_push) as push:
            result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(push.call_count, 1)
        self.assertEqual(result['attempted'], 1)
        self.assertIn('recovery_disabled', self.codes(result))
        self.assertEqual(sum(j['state'] == 'delivered' for j in media.jobs(self.root)), 1)

    def test_original_push_delivers_once_and_does_not_mark_learning_complete(self):
        self.job()
        plan = recovery.plan_recovery(self.root, now=1000)
        with patch.object(media, 'push', wraps=media.push) as push:
            result = recovery.apply_recovery(self.root, plan, now=1000)
            again = recovery.apply_recovery(self.root, plan, now=1001)
        self.assertEqual(push.call_count, 1)
        self.assertEqual(result['outcomes'][0]['outcome'], 'delivered')
        self.assertFalse(result['outcomes'][0]['personal_learning_completed'])
        self.assertEqual(again['attempted'], 0)
        self.assertEqual(media.jobs(self.root)[0]['state'], 'delivered')
        self.assertFalse((self.root / '批准记录').exists())

    def test_failed_snapshot_is_not_replayed_after_restart_and_error_is_redacted(self):
        self.job()
        plan = recovery.plan_recovery(self.root, now=1000)
        with patch.object(media, 'push', side_effect=OSError('PRIVATE_STDERR_AND_CREDENTIAL')) as push:
            result = recovery.apply_recovery(self.root, plan, now=1000)
            again = recovery.apply_recovery(self.root, plan, now=5000)
        self.assertEqual(push.call_count, 1)
        self.assertEqual(result['outcomes'][0]['error_type'], 'OSError')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertIn('recovery_already_attempted', self.codes(again))
        self.assertEqual(recovery.plan_recovery(self.root, now=5000)['actions'], [])

    def test_changed_source_is_not_executed_from_stale_plan(self):
        job = self.job()
        plan = recovery.plan_recovery(self.root)
        job['reason'] = 'changed after planning'
        media.save_job(self.root, job)
        with patch.object(media, 'push', side_effect=AssertionError('stale plan')):
            result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('recovery_plan_stale_or_invalid', self.codes(result))

    def test_frozen_packet_change_is_not_transferred(self):
        job = self.job()
        plan = recovery.plan_recovery(self.root)
        packet = media.safe_file(media.queue(self.root), job['packet_path'])
        packet.write_bytes(b'{}')
        with patch.object(media, 'push', side_effect=AssertionError('bad packet')):
            result = recovery.apply_recovery(self.root, plan)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('recovery_source_or_packet_invalid', self.codes(recovery.plan_recovery(self.root)))

    def test_valid_packet_swap_between_precheck_and_push_is_rejected_atomically(self):
        job = self.job()
        plan = recovery.plan_recovery(self.root)
        original_push = media.push
        frozen = json.loads(media.safe_file(media.queue(self.root), job['packet_path']).read_text(encoding='utf-8'))
        manifest = json.loads(base64.b64decode(frozen['files']['result.json']))
        changed_text = '另一份合法但未在计划中的正文。'.encode('utf-8')
        manifest['text_file']['sha256'] = media.flow.digest(changed_text)
        manifest_bytes = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
        frozen['files']['content.md'] = base64.b64encode(changed_text).decode('ascii')
        frozen['files']['result.json'] = base64.b64encode(manifest_bytes).decode('ascii')
        media.verify_bundle(frozen)
        digest = media.flow.digest(manifest_bytes)

        def swap_then_push(root, identifier, **kwargs):
            self.assertEqual(kwargs['expected_job_sha256'], plan['actions'][0]['source_sha256'])
            with media.locked(root):
                changed = media.flow.read_json(media.path_for(root, identifier))
                target = media.queue(root) / '待回传' / identifier / (digest + '.json')
                target.write_text(json.dumps(frozen), encoding='utf-8')
                changed.update(packet_sha256=digest, packet_path=target.relative_to(media.queue(root)).as_posix())
                media.save_job(root, changed)
            return original_push(root, identifier, **kwargs)

        with patch.object(media, 'push', side_effect=swap_then_push):
            with patch.object(media, 'transfer', side_effect=AssertionError('must not transfer changed packet')) as transfer:
                result = recovery.apply_recovery(self.root, plan)
        transfer.assert_not_called()
        self.assertEqual(result['outcomes'][0]['outcome'], 'failed')
        self.assertEqual(result['outcomes'][0]['error_type'], 'ValueError')
        self.assertEqual(media.jobs(self.root)[0]['state'], 'delivery_pending')

    def test_expired_leases_are_manual_and_never_batch_reclaimed(self):
        for name in ('one', 'two'):
            job = media.request(self.root, 'https://example.com/' + name, 'isolated')
            job = media.claim(self.root, job['id'])
            job['lease_until'] = 10
            media.save_job(self.root, job)
        before = self.source_bytes()
        with patch.object(media, 'pending', side_effect=AssertionError('no batch reclaim')):
            plan = recovery.plan_recovery(self.root, now=1000)
            result = recovery.apply_recovery(self.root, plan, now=1000)
        self.assertEqual(plan['actions'], [])
        self.assertEqual(sum(o['code'] == 'expired_lease_manual_required' for o in plan['observations']), 2)
        self.assertEqual(result['attempted'], 0)
        self.assertEqual(before, self.source_bytes())

    def test_blocked_cancelled_and_test_jobs_are_not_auto_retried(self):
        for name, state in [('one', 'blocked'), ('two', 'cancelled')]:
            job = self.job(name)
            job['state'] = state
            media.save_job(self.root, job)
        self.job('testing', test_only=True)
        with patch.object(media, 'retry', side_effect=AssertionError('manual only')):
            plan = recovery.plan_recovery(self.root)
        self.assertEqual(plan['actions'], [])

    def test_pass_limit_policy_change_and_forged_action_are_rejected(self):
        self.job('one'); self.job('two')
        plan = recovery.plan_recovery(self.root)
        self.assertEqual(len(plan['actions']), 1)
        self.assertIn('recovery_pass_limit', self.codes(plan))
        forged = dict(plan, actions=[dict(plan['actions'][0], action='execute_shell')])
        with self.assertRaises(ValueError):
            recovery.apply_recovery(self.root, forged)
        self.configure(cooldown_seconds=20)
        with self.assertRaises(ValueError):
            recovery.apply_recovery(self.root, plan)

    def test_attempt_budget_and_cooldown_persist_across_changed_snapshots(self):
        job = self.job()
        plan = recovery.plan_recovery(self.root, now=1000)
        with patch.object(media, 'push', side_effect=OSError('offline')):
            recovery.apply_recovery(self.root, plan, now=1000)
        job['reason'] = 'first source revision'
        media.save_job(self.root, job)
        self.assertIn('recovery_cooldown', self.codes(recovery.plan_recovery(self.root, now=1100)))
        second = recovery.plan_recovery(self.root, now=2000)
        with patch.object(media, 'push', side_effect=OSError('offline')):
            recovery.apply_recovery(self.root, second, now=2000)
        job['reason'] = 'second source revision'
        media.save_job(self.root, job)
        plan = recovery.plan_recovery(self.root, now=4000)
        self.assertEqual(plan['actions'], [])
        self.assertIn('recovery_attempt_limit', self.codes(plan))

    def test_uncertain_started_attempt_is_not_replayed(self):
        job = self.job()
        plan = recovery.plan_recovery(self.root, now=1000)
        self.root.joinpath('任务中枢').mkdir()
        connection = recovery._connect(self.root)
        action = plan['actions'][0]
        connection.execute('INSERT INTO attempts VALUES(?,?,?,?,?,NULL,?,NULL,NULL)',
                           (action['id'], job['id'], 'retry_delivery', action['source_sha256'], 1000, 'started'))
        connection.commit(); connection.close()
        with patch.object(media, 'push', side_effect=AssertionError('uncertain outside action')):
            result = recovery.apply_recovery(self.root, plan, now=5000)
        self.assertEqual(result['attempted'], 0)
        self.assertIn('recovery_already_attempted', self.codes(result))

    def test_bad_ledger_fails_closed_without_writes(self):
        self.job()
        path = self.root / '任务中枢' / 'recovery.sqlite3'
        path.parent.mkdir()
        path.write_bytes(b'not a database')
        plan = recovery.plan_recovery(self.root)
        self.assertEqual(plan['actions'], [])
        self.assertIn('recovery_ledger_unavailable', self.codes(plan))
        self.assertEqual(path.read_bytes(), b'not a database')

    def test_defaults_and_strict_configuration(self):
        (self.root / 'task_center.local.json').unlink()
        self.assertFalse(recovery.plan_recovery(self.root)['enabled'])
        self.configure(enabled='false')
        with self.assertRaises(ValueError):
            recovery.plan_recovery(self.root)
        self.configure(max_per_tick=0)
        with self.assertRaises(ValueError):
            recovery.plan_recovery(self.root)
        self.configure()
        with self.assertRaises(ValueError):
            recovery.plan_recovery(self.root, now=dt.datetime(2026, 11, 6))


if __name__ == '__main__':
    unittest.main()
