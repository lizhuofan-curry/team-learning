import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collaboration_flow as c


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.a = Path(self.temp.name) / 'Mac'
        self.b = Path(self.temp.name) / '云端'
        self.a.mkdir()
        self.b.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def send(self, root=None, role='codex', source='turn-1', text='计划明天练习，今天尚未完成。'):
        return c.publish(root or self.a, role, source, '学习工作流', text)

    def test_retry_preserves_timestamp_and_rejects_changed_source(self):
        m = self.send()
        with patch.object(c, 'now', return_value='2030-01-01T00:00:00+08:00'):
            self.assertEqual(self.send(), m)
        with self.assertRaises(ValueError):
            self.send(text='已完成')
        self.assertEqual(c.messages(self.a, 'codex'), [m])

    def test_round_trip_delivery_is_not_read_ack(self):
        m = self.send()
        r = c.import_bundle(self.b, 'hermes', c.export_bundle(self.a, 'codex'))
        self.assertEqual(r['messages_added'], 1)
        self.assertEqual(len(c.list_incoming(self.b, 'hermes', unread=True)), 1)
        self.assertEqual(c.export_bundle(self.b, 'hermes')['acknowledgements'], [])
        self.assertEqual(c.import_bundle(self.b, 'hermes', c.export_bundle(self.a, 'codex'))['messages_added'], 0)
        c.acknowledge(self.b, 'hermes', m['id'], c.envelope_hash(m))
        self.assertEqual(c.list_incoming(self.b, 'hermes', unread=True), [])
        c.import_bundle(self.a, 'codex', c.export_bundle(self.b, 'hermes'))
        ack_files = list((self.a/'协作消息/读取回执/hermes').glob('*.json'))
        self.assertEqual(len(ack_files), 1)
        self.assertFalse((self.a/'批准记录').exists())
        self.assertFalse((self.a/'收件箱').exists())

    def test_wrong_hash_or_missing_message_cannot_be_acknowledged(self):
        m = self.send()
        c.import_bundle(self.b, 'hermes', c.export_bundle(self.a, 'codex'))
        with self.assertRaises(ValueError):
            c.acknowledge(self.b, 'hermes', m['id'], '0'*64)
        with self.assertRaises(FileNotFoundError):
            c.acknowledge(self.b, 'hermes', '0'*24, '0'*64)
        self.assertEqual(c.export_bundle(self.b, 'hermes')['acknowledgements'], [])

    def test_import_preflights_whole_bundle_conflicts(self):
        m = self.send()
        c.import_bundle(self.b, 'hermes', c.export_bundle(self.a, 'codex'))
        self.send(source='turn-2')
        b = c.export_bundle(self.a, 'codex')
        old = next(x for x in b['messages'] if x['id']==m['id'])
        old['text'] = 'changed'
        old['text_sha256'] = c.flow.digest(b'changed')
        with self.assertRaises(ValueError):
            c.import_bundle(self.b, 'hermes', b)
        self.assertEqual(c.messages(self.b, 'codex'), [m])

    def test_sender_cannot_forge_other_agent(self):
        m = self.send()
        b = c.export_bundle(self.a, 'codex')
        b['sender'] = 'hermes'
        with self.assertRaises(ValueError):
            c.import_bundle(self.b, 'hermes', b)
        b['sender'] = 'codex'
        b['messages'][0]['sender'] = 'hermes'
        b['messages'][0]['id'] = c.msg_id('hermes', m['source_id'])
        with self.assertRaises(ValueError):
            c.import_bundle(self.b, 'hermes', b)

    def test_generated_paths_ignore_source_path_text(self):
        m = self.send(source='../../escape')
        self.assertEqual(c.message_path(self.a, m).parent, self.a/'协作消息/Codex发出')
        self.assertFalse((Path(self.temp.name)/'escape').exists())

    def test_test_messages_not_in_normal_agent_list(self):
        c.publish(self.a, 'codex', 'test-1', '测试', '隔离测试', test_only=True)
        c.import_bundle(self.b, 'hermes', c.export_bundle(self.a, 'codex'))
        self.assertEqual(c.list_incoming(self.b, 'hermes', unread=True), [])
        self.assertEqual(len(c.list_incoming(self.b, 'hermes', include_tests=True)), 1)

    def test_revision_keeps_old_and_links_new(self):
        m = self.send()
        n = c.publish(self.a, 'codex', 'turn-2', '学习工作流', '本人修正的下一步计划', supersedes=m['id'])
        self.assertEqual(n['supersedes'], m['id'])
        self.assertEqual(len(c.messages(self.a, 'codex')), 2)

    def test_lock_prevents_overlapping_ticks(self):
        with c.tick_lock(self.a) as first:
            self.assertTrue(first)
            with c.tick_lock(self.a) as second:
                self.assertFalse(second)
        with c.tick_lock(self.a) as third:
            self.assertTrue(third)

    def test_failed_tick_preserves_last_success_and_has_no_read_receipt(self):
        state = self.a/'协作消息/同步状态/latest.json'
        state.parent.mkdir(parents=True)
        c.flow.replace_state(state, {'last_success':'2026-10-28T10:00:00+08:00'})
        (self.a/'config.local.json').write_text('{"mode":"local"}', encoding='utf-8')
        with patch.object(c, 'exchange', side_effect=subprocess.TimeoutExpired('ssh', 25)):
            result, code = c.tick(self.a, {'role':'codex'})
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'retry_pending')
        self.assertEqual(result['last_success'], '2026-10-28T10:00:00+08:00')
        self.assertFalse((self.a/'协作消息/读取回执').exists())

    def test_sync_recovers_after_failure_without_duplicates(self):
        m = self.send()
        self.send(self.b, 'hermes', 'wx-1', '请调整本周周报的措辞，尚未完成练习。')
        cfg = {'role':'codex', 'remote':{'host':'hermes-test', 'root':str(self.b), 'script':'/safe/collaboration_flow.py'}}
        def remote(argv, **kwargs):
            if argv[-1].endswith(' export'):
                return subprocess.CompletedProcess(argv, 0, c.flow.canonical(c.export_bundle(self.b, 'hermes')), b'')
            reply = c.import_bundle(self.b, 'hermes', json.loads(kwargs['input']))
            return subprocess.CompletedProcess(argv, 0, c.flow.canonical(reply), b'')
        with patch.object(c.subprocess, 'run', side_effect=remote):
            first = c.exchange(self.a, cfg)
            second = c.exchange(self.a, cfg)
        self.assertEqual(first['pulled']['messages_added'], 1)
        self.assertEqual(second['pulled']['messages_added'], 0)
        self.assertEqual(second['pushed']['messages_added'], 0)
        self.assertEqual(c.messages(self.b, 'codex'), [m])

    def test_cli_utf8_stdin_and_readback(self):
        (self.a/'collaboration.local.json').write_text('{"role":"codex"}', encoding='utf-8')
        cmd = [sys.executable, str(Path(c.__file__)), '--root', str(self.a)]
        r = subprocess.run(cmd+['publish','--source-id','cli-1','--topic','中文','--text-file','-'], input='待核对，未完成'.encode(), capture_output=True, check=True)
        data = json.loads(r.stdout)
        self.assertTrue(data['queued'])
        r = subprocess.run(cmd+['export'], capture_output=True, check=True)
        self.assertEqual(json.loads(r.stdout)['messages'][0]['text'], '待核对，未完成')


if __name__ == '__main__':
    unittest.main()
