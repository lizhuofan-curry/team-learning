"""Integration tests executed on native Windows runners and macOS/Linux."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'中文项目 space'
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self,script,*args,input=None,ok=True):
        env=dict(os.environ,PYTHONIOENCODING='ascii')
        r=subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],input=input,capture_output=True,env=env)
        if ok:
            self.assertEqual(r.returncode,0,r.stderr.decode('utf-8',errors='replace'))
        else:
            self.assertNotEqual(r.returncode,0)
        return r

    def test_local_install_and_unicode_capture(self):
        home=self.root/'Hermes 数据';workflow=self.root/'学习工作流'
        self.run_cli('install_hermes.py','--hermes-home',home,'--workflow-root',workflow)
        self.run_cli('install_hermes.py','--hermes-home',home,'--workflow-root',workflow)
        config=json.loads((home/'skills/productivity/lab-learning-capture/capture.local.json').read_text(encoding='utf-8'))
        self.assertEqual(Path(config['workflow_root']),workflow.resolve())
        text='学习原话：1 B = 8 bit；尚待复习 ✅\r\n'.encode()
        self.run_cli('learning_flow.py','--root',workflow,'capture','--date','2026-10-27','--text-file','-','--channel','wechat',input=text)
        events=list((workflow/'收件箱').glob('*/*.json'))
        event=json.loads(events[0].read_text(encoding='utf-8'))
        self.assertEqual(event['text'],text.decode())

    def test_configure_paths_and_preserve_custom_keys(self):
        workflow=self.root/'学习工作流';workflow.mkdir()
        original={'mode':'local','custom':'保留此键'}
        (workflow/'config.local.json').write_text(json.dumps(original,ensure_ascii=False),encoding='utf-8-sig')
        vault=self.root/'我的 Wiki';reports=self.root/'个人周报'
        self.run_cli('configure.py','--root',workflow,'--personal-vault',vault,'--weekly-archive',reports,'--archive-wechat-originals')
        obj=json.loads((workflow/'config.local.json').read_text(encoding='utf-8'))
        self.assertEqual(obj['custom'],'保留此键')
        self.assertEqual(Path(obj['raw_captures']),vault.resolve()/'raw/学习记录/微信素材')

    def test_configure_preserves_existing_report_location_unless_explicit(self):
        workflow=self.root/'工作流';workflow.mkdir()
        vault=self.root/'已有库';vault.mkdir()
        reports=vault/'我的日记和周报'
        path=workflow/'config.local.json'
        path.write_text(json.dumps({'mode':'local','personal_vault':str(vault),'obsidian_reports':str(reports)},ensure_ascii=False),encoding='utf-8')
        self.run_cli('configure.py','--root',workflow,'--personal-vault',vault)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['obsidian_reports'],str(reports))
        selected=vault/'本人新选的周报目录'
        self.run_cli('configure.py','--root',workflow,'--obsidian-reports',selected)
        self.assertEqual(Path(json.loads(path.read_text(encoding='utf-8'))['obsidian_reports']),selected.resolve())

    def test_configure_does_not_impose_wiki_layout_on_flat_vault(self):
        vault=self.root/'普通Obsidian库';vault.mkdir()
        note=vault/'本人笔记.md';note.write_text('保持原笔记',encoding='utf-8')
        workflow=self.root/'工作流'
        result=self.run_cli('configure.py','--root',workflow,'--personal-vault',vault)
        config=json.loads((workflow/'config.local.json').read_text(encoding='utf-8'))
        self.assertNotIn('obsidian_reports',config)
        self.assertTrue(json.loads(result.stdout)['needs_configuration'])
        self.assertFalse((vault/'wiki').exists())
        self.assertEqual(note.read_text(encoding='utf-8'),'保持原笔记')

    def test_configuration_can_progress_from_local_to_cloud_with_history(self):
        workflow=self.root/'工作流';home=self.root/'Hermes数据';vault=self.root/'个人库'
        self.run_cli('install_hermes.py','--hermes-home',home,'--workflow-root',workflow)
        self.run_cli('configure.py','--root',workflow,'--personal-vault',vault,'--archive-wechat-originals')
        self.run_cli('configure.py','--root',workflow,'--mode','cloud','--remote-host','my-hermes','--remote-root','/home/member/.hermes/lab-learning')
        self.run_cli('configure.py','--root',workflow,'--mode','local')
        config=json.loads((workflow/'config.local.json').read_text(encoding='utf-8'))
        self.assertEqual(config['mode'],'local')
        self.assertEqual(len(list((workflow/'config.local.backups').glob('*.json'))),3)

    def test_vault_migration_does_not_silently_keep_old_raw_destination(self):
        workflow=self.root/'工作流';first=self.root/'旧库';second=self.root/'新库'
        self.run_cli('configure.py','--root',workflow,'--personal-vault',first,'--archive-wechat-originals')
        before=(workflow/'config.local.json').read_bytes()
        self.run_cli('configure.py','--root',workflow,'--personal-vault',second,ok=False)
        self.assertEqual((workflow/'config.local.json').read_bytes(),before)
        self.run_cli('configure.py','--root',workflow,'--personal-vault',second,'--archive-wechat-originals','--obsidian-reports',second/'周报')
        obj=json.loads((workflow/'config.local.json').read_text(encoding='utf-8'))
        self.assertEqual(Path(obj['raw_captures']),second.resolve()/'raw/学习记录/微信素材')
        self.assertEqual(Path(obj['obsidian_reports']),second.resolve()/'周报')

    def test_full_local_review_archive_retains_crlf_bytes(self):
        workflow=self.root/'workflow';formal=self.root/'正式周报';vault=self.root/'个人知识库'
        self.run_cli('configure.py','--root',workflow,'--personal-vault',vault,'--weekly-archive',formal)
        draft=self.root/'2026-10-26_2026-11-01_周报草稿.md'
        raw='# 测试稿\r\n\r\n本人确认所选版本。\r\n'.encode()
        draft.write_bytes(raw);key=hashlib.sha256(raw).hexdigest()
        self.run_cli('learning_flow.py','--root',workflow,'review','--draft',draft)
        self.run_cli('learning_flow.py','--root',workflow,'approve-review','--sha256',key,'--statement','隔离样例：本人确认该版本','--channel','codex')
        self.run_cli('learning_flow.py','--root',workflow,'archive','--draft',draft,'--start','2026-10-26','--end','2026-11-01')
        self.assertEqual((formal/'2026-10-26_2026-11-01_周报.md').read_bytes(),raw)
        self.assertEqual((vault/'wiki/outputs/周报/2026-10-26_2026-11-01_周报.md').read_bytes(),raw)

    def test_simulated_cloud_export_import_and_approval_roundtrip(self):
        client=self.root/'本机';server=self.root/'服务器';client.mkdir();server.mkdir()
        raw='# 测试周报\n'.encode();key=hashlib.sha256(raw).hexdigest()
        package=json.dumps(dict(sha256=key,content_b64=base64.b64encode(raw).decode(),period=dict(start='2026-10-26',end='2026-11-01'))).encode()
        for root in (client,server):
            self.run_cli('learning_flow.py','--root',root,'review-import',input=package)
        self.run_cli('learning_flow.py','--root',server,'approve-review','--sha256',key,'--statement','隔离测试微信明确确认','--channel','wechat')
        bundle=self.run_cli('learning_flow.py','--root',server,'export').stdout
        self.run_cli('learning_flow.py','--root',client,'import',input=bundle)
        self.run_cli('learning_flow.py','--root',client,'import',input=bundle)
        draft=client/'待审核'/f'{key}.md'
        self.run_cli('learning_flow.py','--root',client,'archive','--draft',draft,'--start','2026-10-26','--end','2026-11-01')

    def test_member_onboarding_creates_only_empty_personal_vault(self):
        workflow=self.root/'个人工作流';vault=self.root/'个人知识库';team=self.root/'团队克隆'
        args=['--root',workflow,'--personal-vault',vault,'--team-repo',team,'--team-url','https://github.com/example/shared-team','--initialize-personal-vault']
        self.run_cli('onboard_member.py',*args)
        self.assertTrue((vault/'raw').is_dir())
        self.assertFalse(list((vault/'raw').iterdir()))
        self.assertTrue((vault/'wiki/index.md').is_file())
        self.assertFalse(team.exists())
        config=json.loads((workflow/'config.local.json').read_text(encoding='utf-8'))
        self.assertEqual(Path(config['personal_vault']),vault.resolve())
        (vault/'AGENTS.md').write_text('成员自己的规则',encoding='utf-8')
        self.run_cli('onboard_member.py',*args)
        self.assertEqual((vault/'AGENTS.md').read_text(encoding='utf-8'),'成员自己的规则')

    def test_member_can_attach_existing_team_after_multiple_config_steps(self):
        workflow=self.root/'工作流';vault=self.root/'个人库';home=self.root/'Hermes数据';team=self.root/'团队克隆'
        self.run_cli('install_hermes.py','--hermes-home',home,'--workflow-root',workflow)
        self.run_cli('configure.py','--root',workflow,'--personal-vault',vault)
        self.run_cli('configure.py','--root',workflow,'--weekly-archive',self.root/'正式周报')
        self.run_cli('onboard_member.py','--root',workflow,'--personal-vault',vault,'--team-repo',team,'--team-url','https://github.com/example/shared-team')
        obj=json.loads((workflow/'config.local.json').read_text(encoding='utf-8'))
        self.assertEqual(Path(obj['team_repo']),team.resolve())
        self.assertEqual(Path(obj['personal_vault']),vault.resolve())
        self.assertFalse(team.exists())

    def test_member_onboarding_preserves_unrecognized_nonempty_directory(self):
        workflow=self.root/'工作流';vault=self.root/'已有笔记';vault.mkdir()
        note=vault/'笔记.md';note.write_text('重要原件',encoding='utf-8')
        self.run_cli('onboard_member.py','--root',workflow,'--personal-vault',vault,'--initialize-personal-vault',ok=False)
        self.assertEqual(note.read_text(encoding='utf-8'),'重要原件')
        self.assertFalse((vault/'wiki').exists());self.assertFalse(workflow.exists())

    def test_member_onboarding_rejects_nested_team_and_wrong_existing_config(self):
        workflow=self.root/'workflow';vault=self.root/'vault'
        self.run_cli('onboard_member.py','--root',workflow,'--personal-vault',vault,'--team-repo',vault/'团队',ok=False)
        self.assertFalse(workflow.exists())
        workflow.mkdir();original=b'{"mode":"local","personal_vault":"other-vault"}'
        (workflow/'config.local.json').write_bytes(original)
        self.run_cli('onboard_member.py','--root',workflow,'--personal-vault',vault,ok=False)
        self.assertEqual((workflow/'config.local.json').read_bytes(),original)


if __name__=='__main__':
    unittest.main(verbosity=2)
