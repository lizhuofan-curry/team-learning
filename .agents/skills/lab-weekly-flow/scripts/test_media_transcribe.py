import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import media_transcribe as m

class TranscriptTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.media=self.root/'selected.mp4';self.media.write_bytes(b'test selected video')
  self.adapter=self.root/'adapter.py';self.adapter.write_bytes(b'known adapter fixture')
  self.ffmpeg=self.root/'ffmpeg';self.ffmpeg.write_bytes(b'fixture, not executable')
  self.calls=[];self.fail_second=False
 def tearDown(self):self.temp.cleanup()
 def fake(self,args,**kwargs):
  self.calls.append(args)
  if args[0]==str(self.ffmpeg):
   target=Path(args[-1]).parent
   for i in range(2):
    with wave.open(str(target/f'part-{i:03d}.wav'),'wb') as w:
     w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*16000*30)
   return subprocess.CompletedProcess(args,0,b'',b'')
  if self.fail_second and 'part-001.wav' in args[args.index('--input')+1]:
   return subprocess.CompletedProcess(args,2,b'',b'SENSEVOICE_ERROR:API_REQUEST_TIMEOUT')
  return subprocess.CompletedProcess(args,0,'识别原文：计划明天练习，今天尚未完成。'.encode(),b'')
 def run_media(self):
  return m.run(self.root,'douyin','123','https://v.douyin.com/abc/','https://www.douyin.com/video/123',self.media,self.ffmpeg,self.adapter,sys.executable,60,30)
 def test_coverage_is_contiguous_and_requires_complete_duration(self):
  self.assertEqual(m.coverage([30,30,2],62),[(0,30),(30,60),(60,62)])
  for values,expected in [([30],60),([],60),([0],0),([float('nan')],1)]:
   with self.assertRaises(ValueError):m.coverage(values,expected)
 def test_full_run_preserves_raw_text_and_resume_does_not_call_api(self):
  with patch.object(m.subprocess,'run',side_effect=self.fake):r=self.run_media()
  self.assertEqual(r['status'],'transcript_ready');self.assertEqual(r['segments'],2)
  p=self.root/'媒体结果/douyin/123';manifest=json.loads((p/'result.json').read_text(encoding='utf-8'))
  self.assertEqual(manifest['audio_coverage_seconds'],[0,60]);self.assertFalse(manifest['word_timestamps_available']);self.assertFalse(manifest['count_as_owner_learning'])
  self.assertIn('尚未完成',(p/'transcript.md').read_text(encoding='utf-8'))
  with patch.object(m.subprocess,'run',side_effect=AssertionError('must not retry completed transcription')):again=self.run_media()
  self.assertTrue(again['reused_completed_run'])
 def test_failure_keeps_successful_segments_and_resumes_missing_only(self):
  self.fail_second=True
  with patch.object(m.subprocess,'run',side_effect=self.fake),self.assertRaises(ValueError):self.run_media()
  work=self.root/'媒体缓存/douyin/123/sensevoice-full'
  self.assertTrue((work/'part-000.txt').exists());self.assertFalse((self.root/'媒体结果/douyin/123/result.json').exists())
  self.fail_second=False;self.calls=[]
  with patch.object(m.subprocess,'run',side_effect=self.fake):r=self.run_media()
  self.assertEqual(r['status'],'transcript_ready');self.assertEqual(len(self.calls),1)
  self.assertIn('part-001.wav',self.calls[0][self.calls[0].index('--input')+1])
 def test_podcast_audio_is_labelled_as_audio(self):
  with patch.object(m.subprocess,'run',side_effect=self.fake):
   m.run(self.root,'xiaoyuzhou','episode1','https://www.xiaoyuzhoufm.com/episode/episode1','https://www.xiaoyuzhoufm.com/episode/episode1',self.media,self.ffmpeg,self.adapter,sys.executable,60,30,resource_kind='audio')
  p=self.root/'媒体结果/xiaoyuzhou/episode1'
  self.assertEqual(json.loads((p/'result.json').read_text(encoding='utf-8'))['resource_kind'],'audio')
  self.assertIn('播客/音频',(p/'transcript.md').read_text(encoding='utf-8'))
 def test_chinese_transcript_survives_non_utf8_default_file_encoding(self):
  original=Path.read_text
  def windows_default(path,encoding=None,errors=None):
   return original(path,encoding=encoding or 'cp1252',errors=errors)
  with patch.object(Path,'read_text',windows_default),patch.object(m.subprocess,'run',side_effect=self.fake):
   result=self.run_media()
  self.assertEqual(result['status'],'transcript_ready')
  self.assertIn('尚未完成',(self.root/'媒体结果/douyin/123/transcript.md').read_text(encoding='utf-8'))
 def test_changed_input_is_rejected_without_any_api_call(self):
  with patch.object(m.subprocess,'run',side_effect=self.fake):self.run_media()
  self.media.write_bytes(b'other media')
  with patch.object(m.subprocess,'run',side_effect=AssertionError('must not call API')),self.assertRaises(ValueError):self.run_media()

if __name__=='__main__':unittest.main()
