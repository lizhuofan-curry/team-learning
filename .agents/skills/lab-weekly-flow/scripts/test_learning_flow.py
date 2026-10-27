import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('flow', Path(__file__).with_name('learning_flow.py'))
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_capture_is_idempotent_and_does_not_replace_original(self):
        first = flow.capture(self.root, '2026-10-27', '本人原话', 'wechat', 'user-original', '1')
        second = flow.capture(self.root, '2026-10-27', '本人原话', 'wechat', 'user-original', '1')
        self.assertEqual(first, second)
        with self.assertRaises(ValueError):
            flow.capture(self.root, '2026-10-27', '修改后内容', 'wechat', 'user-original', '1')
        self.assertEqual(flow.read_json(first)['text'], '本人原话')

    def test_modified_event_rejected(self):
        p = flow.capture(self.root, '2026-10-27', '原文', 'local', 'user-original')
        e = flow.read_json(p)
        e['text'] = '篡改'
        with self.assertRaises(ValueError):
            flow.import_bundle(self.root / 'target', dict(version=1, events=[e]))

    def test_date_and_id_cannot_escape_inbox(self):
        p = flow.capture(self.root, '2026-10-27', '原文', 'local', 'user-original', '../../escape')
        self.assertTrue(p.is_relative_to(self.root / '收件箱'))
        with self.assertRaises(ValueError):
            flow.capture(self.root, '../../escape', '原文', 'local', 'user-original')

    def test_prepare_filters_date_and_test_materials(self):
        flow.capture(self.root, '2026-10-27', '本周', 'local', 'user-original')
        flow.capture(self.root, '2026-10-20', '上周', 'local', 'user-original')
        flow.capture(self.root, '2026-10-27', '测试', 'system-test', 'test')
        packet = flow.read_json(flow.prepare(self.root, '2026-10-26', '2026-11-01'))
        self.assertEqual([e['text'] for e in packet['events']], ['本周'])
        self.assertIsNone(packet['previous_report'])

    def test_prepare_pins_previous_report(self):
        previous = self.root / '上周.md'
        previous.write_text('下周计划：源码学习',encoding='utf-8')
        packet = flow.read_json(flow.prepare(self.root, '2026-10-26', '2026-11-01', previous))
        self.assertEqual(packet['previous_report']['sha256'], flow.digest(previous.read_bytes()))

    def reviewed(self):
        raw = '真实内容待本人审核'.encode()
        key = flow.digest(raw)
        p = flow.review_import(self.root, dict(sha256=key, content_b64=base64.b64encode(raw).decode(), period={'start':'2026-10-26','end':'2026-11-01'}))
        return p, key

    def test_archive_without_approval_refused(self):
        p, key = self.reviewed()
        with self.assertRaises(ValueError):
            flow.archive(self.root, {}, p, '2026-10-26', '2026-11-01')
        self.assertFalse((self.root / '已归档').exists())

    def test_approval_binds_exact_draft_bytes(self):
        p, key = self.reviewed()
        flow.approve_review(self.root, key, '本人已核对这个版本', 'codex')
        edited = self.root / '修改稿.md'
        edited.write_text(p.read_text(encoding='utf-8') + '追加',encoding='utf-8')
        with self.assertRaises(ValueError):
            flow.archive(self.root, {}, edited, '2026-10-26', '2026-11-01')

    def test_unknown_review_cannot_be_approved(self):
        with self.assertRaises(ValueError):
            flow.approve_review(self.root, 'a'*64, '本人已核对这个版本', 'wechat')

    def test_archive_is_idempotent_and_conflicts_preserve_files(self):
        p, key = self.reviewed()
        flow.approve_review(self.root, key, '本人已核对这个版本', 'codex')
        config = {'weekly_archive': str(self.root / '正式'), 'obsidian_reports': str(self.root / 'wiki')}
        result = flow.archive(self.root, config, p, '2026-10-26', '2026-11-01')
        flow.archive(self.root, config, p, '2026-10-26', '2026-11-01')
        for dest in result['archived']:
            self.assertEqual(Path(dest).read_bytes(), p.read_bytes())
        conflict = Path(result['archived'][1])
        conflict.write_text('不能覆盖的旧周报',encoding='utf-8')
        with self.assertRaises(ValueError):
            flow.archive(self.root, config, p, '2026-10-26', '2026-11-01')
        self.assertEqual(conflict.read_text(encoding='utf-8'), '不能覆盖的旧周报')

    def test_cloud_bundle_import_repeated_and_test_approval_rejected(self):
        p, key = self.reviewed()
        flow.approve_review(self.root, key, '这是隔离测试批准', 'test')
        flow.capture(self.root, '2026-10-27', '原话', 'wechat', 'user-original')
        target = self.root / '另一个节点'
        flow.import_bundle(target, flow.export(self.root))
        flow.import_bundle(target, flow.export(self.root))
        self.assertEqual(len(flow.export(target)['events']), 1)
        with self.assertRaises(ValueError):
            flow.archive(target, {}, p, '2026-10-26', '2026-11-01')

    def test_local_sync_needs_no_ssh(self):
        self.assertEqual(flow.sync(self.root, {'mode':'local'})['mode'], 'local')

    def test_unsafe_ssh_host_rejected(self):
        config = {'remote':{'host':'-oProxyCommand=bad','root':'/tmp/x','script':'/tmp/x.py'}}
        with self.assertRaises(ValueError):
            flow.remote_command(config, 'export')

    def test_codex_plans_are_kept_as_plans_not_completed_results(self):
        p = flow.capture(self.root, '2026-10-27', '下周做第五章', 'codex', 'user-original', 'thread-turn-plan', 'plan')
        self.assertEqual(flow.read_json(p)['category'], 'plan')
        packet = flow.read_json(flow.prepare(self.root, '2026-10-26', '2026-11-01'))
        self.assertEqual(packet['events'][0]['category'], 'plan')

    def test_raw_archive_is_opt_in_original_only_and_append_only(self):
        flow.capture(self.root, '2026-10-27', '微信原话\n', 'wechat', 'user-original')
        flow.capture(self.root, '2026-10-27', 'AI摘要', 'wechat', 'assistant-summary')
        flow.capture(self.root, '2026-10-27', '测试', 'system-test', 'test')
        with self.assertRaises(ValueError):
            flow.archive_captures(self.root, {})
        config = {'raw_captures': str(self.root / 'raw/学习记录/微信素材')}
        result = flow.archive_captures(self.root, config)
        self.assertEqual(len(result['raw_captures']), 1)
        p = Path(result['raw_captures'][0])
        self.assertTrue(p.read_bytes().endswith('微信原话\n'.encode()))
        flow.archive_captures(self.root, config)
        p.write_text('用户修改后的原件',encoding='utf-8')
        with self.assertRaises(ValueError):
            flow.archive_captures(self.root, config)
        self.assertEqual(p.read_text(encoding='utf-8'), '用户修改后的原件')

    def test_repeat_approval_in_another_channel_does_not_break_sync(self):
        p, key = self.reviewed()
        flow.approve_review(self.root, key, '本人在Codex确认此稿', 'codex')
        flow.approve_review(self.root, key, '本人在微信再次确认此稿', 'wechat')
        flow.archive(self.root, {}, p, '2026-10-26', '2026-11-01')

    def test_approved_report_cannot_be_archived_as_another_week(self):
        p, key = self.reviewed()
        flow.approve_review(self.root, key, '本人已核对这个版本', 'codex')
        with self.assertRaises(ValueError):
            flow.archive(self.root, {}, p, '2026-11-02', '2026-11-08')

    def test_new_review_invalidates_old_version_approval(self):
        p, key = self.reviewed()
        flow.approve_review(self.root, key, '本人已核对这个版本', 'codex')
        new = '新的待审核稿'.encode()
        flow.review_import(self.root, dict(sha256=flow.digest(new), content_b64=base64.b64encode(new).decode(), period={'start':'2026-10-26','end':'2026-11-01'}))
        with self.assertRaises(ValueError):
            flow.approve_review(self.root, key, '再次批准旧版本', 'wechat')
        with self.assertRaises(ValueError):
            flow.archive(self.root, {}, p, '2026-10-26', '2026-11-01')

    def test_replayed_approved_draft_cannot_replace_new_review(self):
        old_path, old_key = self.reviewed()
        flow.approve_review(self.root, old_key, '本人批准最初的稿件A', 'codex')
        approval_path = self.root / '批准记录' / (old_key + '.json')
        original_approval = approval_path.read_bytes()
        period = {'start': '2026-10-26', 'end': '2026-11-01'}
        new_content = '稿件B：需要重新审核'.encode()
        new_key = flow.digest(new_content)
        new_path = flow.review_import(self.root, dict(
            sha256=new_key, content_b64=base64.b64encode(new_content).decode(), period=period))

        with self.assertRaises(ValueError):
            flow.review_import(self.root, dict(
                sha256=old_key, content_b64=base64.b64encode(old_path.read_bytes()).decode(), period=period))

        index_path = self.root / '审核索引' / '2026-10-26_2026-11-01.json'
        self.assertEqual(flow.read_json(index_path)['sha256'], new_key)
        self.assertEqual(approval_path.read_bytes(), original_approval)
        self.assertEqual(old_path.read_bytes(), '真实内容待本人审核'.encode())
        with self.assertRaises(ValueError):
            flow.archive(self.root, {}, old_path, period['start'], period['end'])
        with self.assertRaises(ValueError):
            flow.archive(self.root, {}, new_path, period['start'], period['end'])
        flow.approve_review(self.root, new_key, '本人重新核对并批准稿件B', 'wechat')
        result = flow.archive(self.root, {}, new_path, period['start'], period['end'])
        self.assertEqual(Path(result['archived'][0]).read_bytes(), new_content)

    def test_current_review_retry_preserves_approval_and_index(self):
        path, key = self.reviewed()
        flow.approve_review(self.root, key, '本人批准当前稿件', 'codex')
        index_path = self.root / '审核索引' / '2026-10-26_2026-11-01.json'
        before_index = index_path.read_bytes()
        retried = flow.review_import(self.root, dict(
            sha256=key, content_b64=base64.b64encode(path.read_bytes()).decode(),
            period={'start': '2026-10-26', 'end': '2026-11-01'}))
        self.assertEqual(retried, path)
        self.assertEqual(index_path.read_bytes(), before_index)
        flow.archive(self.root, {}, path, '2026-10-26', '2026-11-01')

    def test_utf8_cli_with_non_utf8_parent_environment(self):
        root = self.root / '中文路径 with space'
        env = dict(os.environ, PYTHONIOENCODING='ascii')
        text = '计划：学习网络，明天再做实验 ✅\n'
        script = str(Path(__file__).with_name('learning_flow.py'))
        r = subprocess.run([sys.executable, script, '--root',str(root),'capture','--date','2026-10-27','--text-file','-','--channel','wechat'], input=text.encode(), capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr.decode('utf-8',errors='replace'))
        self.assertEqual(flow.export(root)['events'][0]['text'],text)

    def test_windows_utf8_bom_config(self):
        p = self.root / 'config.local.json'
        p.write_bytes(b'\xef\xbb\xbf'+json.dumps({'mode':'local','personal_vault':'中文路径'},ensure_ascii=False).encode())
        self.assertEqual(flow.read_json(p)['personal_vault'],'中文路径')


if __name__ == '__main__':
    unittest.main(verbosity=2)
