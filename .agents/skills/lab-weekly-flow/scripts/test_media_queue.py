import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import media_queue as q

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)/'Mac';self.root.mkdir()
        self.cloud=Path(self.t.name)/'云端';self.cloud.mkdir()
        self.cfg={'enabled':True,'since':'2026-10-29','grace_seconds':0,'lease_seconds':100,'max_attempts':2,'retry_seconds':0}
        (self.root/'media.local.json').write_text(json.dumps(self.cfg))
        (self.root/'collaboration.local.json').write_text('{"mode":"local","role":"codex"}')
    def tearDown(self):self.t.cleanup()
    def event(self,url='https://www.example.com/article',day='2026-10-29',kind='user-original',channel='wechat'):
        return q.flow.capture(self.root,day,url,channel,kind,'test-source:'+url+day+kind+channel,'resource')
    def make_packet(self,url='https://www.example.com/article',status='article_ready',test=False):
        base=self.root/'媒体结果/web/article';base.mkdir(parents=True,exist_ok=True)
        text='真实正文片段，计划并不代表完成。'.encode();(base/'content.md').write_bytes(text)
        m={'schema_version':1,'platform':'web','resource_id':'article','canonical_url':url,'source_url':url,'status':status,'content_source':['browser_rendered_text'],'text_file':{'path':'content.md','sha256':q.flow.digest(text)},'test_only':test,'visual_verified':False}
        (base/'result.json').write_text(json.dumps(m,ensure_ascii=False));return base
    def test_discover_only_new_original_wechat_resources_and_deduplicates(self):
        self.event();self.event(day='2026-10-28');self.event(kind='assistant-summary');self.event(channel='codex')
        self.assertEqual(q.discover(self.root)['added'],1)
        self.assertEqual(q.discover(self.root)['added'],0)
        self.assertEqual(len(q.jobs(self.root)),1)
    def test_normalization_preserves_content_selectors(self):
        a=q.normalize_url('https://www.bilibili.com/video/BV1234567890/?p=2&vd_source=abc')
        self.assertIn('p=2',a);self.assertNotIn('vd_source',a)
        self.assertIn('modal_id=123',q.normalize_url('https://www.douyin.com/?modal_id=123'))
    def test_new_arrival_with_wrong_old_date_is_not_lost(self):
        self.assertEqual(q.discover(self.root)['added'],0)
        p=self.event('https://example.com/new-but-old-stamped',day='2026-10-28')
        original=p.read_bytes();e=json.loads(original)
        self.assertEqual(q.discover(self.root)['added'],1)
        j=q.jobs(self.root)[0]
        self.assertIn(e['id'],j['source_date_warnings'])
        self.assertEqual(j['source_date_warnings'][e['id']]['recorded_date'],'2026-10-28')
        self.assertEqual(p.read_bytes(),original)
        self.assertEqual(q.discover(self.root)['added'],0)
    def test_initial_old_history_stays_ignored_after_restart(self):
        self.event('https://example.com/old',day='2026-10-28')
        self.assertEqual(q.discover(self.root)['added'],0)
        self.assertEqual(q.discover(self.root)['added'],0)
        self.assertEqual(q.jobs(self.root),[])
        self.event('https://example.com/new',day='2026-10-28')
        self.assertEqual(q.discover(self.root)['added'],1)
    def test_explicit_bookmark_only_request_is_not_opened(self):
        self.event('只收藏，不要读取：https://example.com/article')
        self.assertEqual(q.discover(self.root)['added'],0)
    def test_reject_private_urls_credentials_and_commands(self):
        for u in ('file:///etc/passwd','https://127.0.0.1/x','https://10.0.0.1/x','http://localhost/x','https://x:y@example.com/','https://example.com/?token=abc','https://example.com/\ncommand'):
            with self.subTest(u=u),self.assertRaises(ValueError):q.request(self.root,u,'x')
    def test_sources_merge_without_reviving_delivered_job(self):
        j=q.request(self.root,'https://example.com/','a');j['state']='delivered';q.save_job(self.root,j)
        k=q.request(self.root,j['url'],'b');self.assertEqual(k['state'],'delivered');self.assertEqual(k['sources'],['a','b'])
    def test_lease_prevents_duplicate_workers(self):
        j=q.request(self.root,'https://example.com/','a');c=q.claim(self.root,j['id'])
        with self.assertRaises(ValueError):q.claim(self.root,j['id'])
        with self.assertRaises(ValueError):q.finish(self.root,j['id'],'0'*32,outcome='blocked',reason='not owner')
        self.assertEqual(q.jobs(self.root)[0]['lease_token'],c['lease_token'])
    def test_expired_lease_recovery_and_attempt_limit(self):
        j=q.request(self.root,'https://example.com/','a')
        for _ in range(2):
            c=q.claim(self.root,j['id']);c['lease_until']=0;q.save_job(self.root,c);q.pending(self.root)
        self.assertEqual(q.jobs(self.root)[0]['state'],'blocked');self.assertEqual(q.pending(self.root),[])
        q.retry(self.root,j['id']);self.assertEqual(len(q.pending(self.root)),1)
    def test_failed_attempt_stays_queued_then_stops(self):
        j=q.request(self.root,'https://example.com/','a')
        for i in range(2):
            c=q.claim(self.root,j['id']);r=q.finish(self.root,j['id'],c['lease_token'],outcome='retry_wait',reason='temporary offline')
        self.assertEqual(r['state'],'blocked')
    def test_browser_infrastructure_deferral_does_not_exhaust_resource_attempts(self):
        j=q.request(self.root,'https://example.com/','a')
        for _ in range(3):
            c=q.claim(self.root,j['id']);r=q.finish(self.root,j['id'],c['lease_token'],outcome='deferred',reason='browser not available')
        self.assertEqual(r['state'],'retry_wait');self.assertEqual(r['attempts'],0)
        self.assertEqual(r['infrastructure_deferrals'],3);self.assertEqual(len(q.pending(self.root)),1)
    def test_packet_hash_path_and_unrelated_url_checks(self):
        base=self.make_packet();b=q.packet(self.root,base)
        q.verify_bundle(b)
        b['files']['content.md']=base64.b64encode(b'wrong').decode()
        with self.assertRaises(ValueError):q.verify_bundle(b)
        for n in ('../secret','/etc/passwd','x\\y','a/../../x'):
            with self.assertRaises(ValueError):q.safe_file(base,n)
        j=q.request(self.root,'https://example.org/other','x');c=q.claim(self.root,j['id'])
        with self.assertRaises(ValueError):q.finish(self.root,j['id'],c['lease_token'],base)
    def test_note_cannot_be_complete_with_missing_or_unread_images(self):
        base=self.make_packet();m=json.loads((base/'result.json').read_text());m.update(resource_kind='note_image_post',images_expected_from_page=3,images_obtained=0,images_visually_read=0,images=[])
        (base/'result.json').write_text(json.dumps(m))
        with self.assertRaises(ValueError):q.packet(self.root,base)
        m['status']='partial_ready';(base/'result.json').write_text(json.dumps(m));q.packet(self.root,base)
    def test_receive_idempotent_and_preserves_failure(self):
        base=self.make_packet();b=q.packet(self.root,base)
        dest=self.cloud/'媒体结果/web/article';dest.mkdir(parents=True);old=b'{"status":"request_blocked"}';(dest/'result.json').write_bytes(old)
        r=q.receive(self.cloud,b);self.assertEqual(r,q.receive(self.cloud,b))
        self.assertTrue(any(p.read_bytes()==old for p in (dest/'history').iterdir()))
        self.assertFalse((self.cloud/'批准记录').exists());self.assertFalse((self.cloud/'收件箱').exists())
    def test_receive_preflights_all_before_writes_and_preserves_complete(self):
        base=self.make_packet();b=q.packet(self.root,base);q.receive(self.cloud,b)
        changed=json.loads(json.dumps(b));m=json.loads(base64.b64decode(changed['files']['result.json']));m['content_source']=['other'];changed['files']['result.json']=base64.b64encode(json.dumps(m).encode()).decode()
        with self.assertRaises(ValueError):q.receive(self.cloud,changed)
        b['files']['../escape']=base64.b64encode(b'x').decode()
        with self.assertRaises(ValueError):q.receive(self.cloud,b)
        self.assertFalse((self.cloud/'媒体结果/web/escape').exists())
    def test_symlink_packet_and_destination_rejected(self):
        base=self.make_packet();target=base/'external.md';target.write_text('x');(base/'content.md').unlink();(base/'content.md').symlink_to(target)
        with self.assertRaises(ValueError):q.packet(self.root,base)
    def test_complete_round_trip_retry_keeps_single_status_and_snapshot(self):
        base=self.make_packet();j=q.request(self.root,'https://www.example.com/article','a');c=q.claim(self.root,j['id']);r=q.finish(self.root,j['id'],c['lease_token'],base)
        self.assertEqual(r['state'],'delivery_pending')
        with patch.object(q,'transfer',side_effect=lambda root,action,extra=(),bundle=None:q.receive(self.cloud,bundle)):
            r=q.push(self.root,j['id']);self.assertEqual(r['status'],'delivered');q.push(self.root,j['id'])
        self.assertEqual(q.jobs(self.root)[0]['state'],'delivered')
        self.assertEqual(len(list((self.root/'协作消息/Codex发出').glob('*.json'))),1)
        self.assertEqual(q.pending(self.root),[])
    def test_network_failure_keeps_immutable_packet_for_retry(self):
        base=self.make_packet();j=q.request(self.root,'https://www.example.com/article','a');c=q.claim(self.root,j['id']);q.finish(self.root,j['id'],c['lease_token'],base)
        with patch.object(q,'transfer',side_effect=subprocess.TimeoutExpired('ssh',55)),self.assertRaises(subprocess.TimeoutExpired):q.push(self.root,j['id'])
        self.assertEqual(q.jobs(self.root)[0]['state'],'delivery_pending')
        self.assertFalse((self.root/'协作消息/Codex发出').exists())
    def test_test_jobs_hidden_and_cannot_be_mixed_with_live_packet(self):
        base=self.make_packet();j=q.request(self.root,'https://www.example.com/article','test',test_only=True)
        self.assertEqual(q.pending(self.root),[]);c=q.claim(self.root,j['id'])
        with self.assertRaises(ValueError):q.finish(self.root,j['id'],c['lease_token'],base)
    def test_cli_unicode_paths_and_receive(self):
        base=self.make_packet();b=q.packet(self.root,base)
        r=subprocess.run([sys.executable,str(Path(q.__file__)), '--root',str(self.cloud),'receive'],input=json.dumps(b).encode(),capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['status'],'stored')
    def test_disabled_queue_does_not_return_jobs_or_send(self):
        j=q.request(self.root,'https://example.com/','a')
        (self.root/'media.local.json').write_text('{"enabled":false}')
        self.assertEqual(q.pending(self.root),[])
        with self.assertRaises(ValueError):q.claim(self.root,j['id'])
        with self.assertRaises(ValueError):q.push(self.root,j['id'])

if __name__=='__main__':unittest.main()
