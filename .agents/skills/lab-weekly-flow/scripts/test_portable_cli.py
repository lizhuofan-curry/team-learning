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


if __name__=='__main__':
    unittest.main(verbosity=2)
