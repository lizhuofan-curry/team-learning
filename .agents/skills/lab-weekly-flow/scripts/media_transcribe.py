#!/usr/bin/env python3
"""Transcribe one owner-selected local video through the existing SenseVoice adapter.
No URL discovery, key handling, provider switching, chat sending or approval.
"""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import wave
import learning_flow as flow
import media_queue as mq


def digest_file(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def coverage(durations,expected,tolerance=1.0):
    if not durations or any(not math.isfinite(x) or x<=0 for x in durations):raise ValueError('invalid segment duration')
    total=sum(durations)
    if abs(total-expected)>tolerance:raise ValueError('audio coverage does not match selected full media')
    start=0;out=[]
    for d in durations:out.append((start,start+d));start+=d
    return out


def run(root,platform,resource_id,source_url,canonical_url,media,ffmpeg,adapter,python,expected,segment_seconds=240,resource_kind="video"):
    if resource_kind not in ('video','audio'):raise ValueError('invalid resource kind')
    for x in (platform,resource_id):
        if not mq.NAME.fullmatch(x):raise ValueError('invalid media identity')
    mq.normalize_url(source_url);mq.normalize_url(canonical_url)
    media=Path(media).resolve();ffmpeg=Path(ffmpeg).resolve();adapter=Path(adapter).resolve()
    if not media.is_file() or not ffmpeg.is_file() or not adapter.is_file():raise ValueError('selected input/adapter/ffmpeg missing')
    if not (0<expected<=24*3600 and 30<=segment_seconds<=280):raise ValueError('invalid duration bounds')
    work=Path(root)/'媒体缓存'/platform/resource_id/'sensevoice-full'
    work.mkdir(parents=True,exist_ok=True,mode=0o700)
    state={'version':1,'source_url':source_url,'canonical_url':canonical_url,'input_sha256':digest_file(media),'expected_seconds':expected,'segment_seconds':segment_seconds,'provider':'siliconflow_sensevoice','adapter_sha256':digest_file(adapter)}
    if resource_kind != 'video':state['resource_kind']=resource_kind
    plan=work/'plan.json'
    if plan.exists() and flow.read_json(plan)!=state:raise ValueError('existing transcription plan differs; preserve earlier run')
    flow.store(plan,flow.canonical(state)+b'\n')
    progress=work/'progress.json'
    if progress.exists():
        completed=flow.read_json(progress)
        if completed.get('phase')=='completed':
            existing=mq.packet(root,Path(root)/'媒体结果'/platform/resource_id)
            manifest,files=mq.verify_bundle(existing)
            if flow.digest(files['result.json'])!=completed['manifest_sha256']:raise ValueError('completed media result changed; preserve it')
            return {'status':manifest['status'],'segments':completed['total'],'coverage_seconds':completed['audio_coverage_seconds'][1],'manifest_sha256':completed['manifest_sha256'],'provider':'siliconflow_sensevoice','reused_completed_run':True}
    chunks=work/'audio';chunks.mkdir(exist_ok=True,mode=0o700)
    marker=work/'segments.json'
    if not marker.exists():
        if list(chunks.glob('*.wav')):raise ValueError('incomplete segmentation exists; inspect before restarting')
        flow.replace_state(progress,{'phase':'extracting_audio','updated_at':mq.now(),'completed':0})
        subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe','-i',str(media),'-map','0:a:0','-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-f','segment','-segment_time',str(segment_seconds),'-reset_timestamps','1','-segment_format','wav',str(chunks/'part-%03d.wav')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180)
        measured=[]
        for p in sorted(chunks.glob('part-*.wav')):
            with wave.open(str(p),'rb') as w:
                if w.getnchannels()!=1 or w.getframerate()!=16000:raise ValueError('unexpected normalized audio format')
                duration=w.getnframes()/w.getframerate()
            if duration>300 or p.stat().st_size>50_000_000:raise ValueError('segment exceeds existing adapter limit')
            measured.append({'file':p.name,'duration':duration,'sha256':digest_file(p)})
        coverage([x['duration'] for x in measured],expected)
        flow.store(marker,flow.canonical(measured)+b'\n')
    measured=flow.read_json(marker)
    ranges=coverage([x['duration'] for x in measured],expected)
    results=[]
    for i,(part,bounds) in enumerate(zip(measured,ranges)):
        wav=chunks/part['file'];assert digest_file(wav)==part['sha256']
        text_path=work/f'part-{i:03d}.txt';meta_path=work/f'part-{i:03d}.json'
        if meta_path.exists():
            receipt=flow.read_json(meta_path)
            if receipt['audio_sha256']!=part['sha256'] or not text_path.exists() or digest_file(text_path)!=receipt['text_sha256']:raise ValueError('saved transcript hash mismatch')
        else:
            # Preserve successful segments; a subsequent run only resumes missing ones.
            start=time.monotonic()
            p=subprocess.run([python,str(adapter),'--input',str(wav),'--ffmpeg',str(ffmpeg),'--max-seconds','300','--diagnostics',str(work/f'part-{i:03d}-diagnostics.json')],capture_output=True,timeout=155)
            if p.returncode or not p.stdout.strip():
                code=re.search(rb'SENSEVOICE_ERROR:([A-Z0-9_]+)',p.stderr)
                flow.replace_state(progress,{'phase':'failed','segment_index':i,'completed':len(results),'total':len(measured),'error':code.group(1).decode() if code else 'ADAPTER_FAILED','updated_at':mq.now()})
                raise ValueError('SenseVoice segment failed: '+(code.group(1).decode() if code else 'ADAPTER_FAILED'))
            raw=p.stdout.decode('utf-8').strip().encode()
            flow.store(text_path,raw+b'\n');text_path.chmod(0o600)
            receipt={'segment_index':i,'start_seconds':bounds[0],'end_seconds':bounds[1],'audio_sha256':part['sha256'],'text_sha256':digest_file(text_path),'elapsed_seconds':round(time.monotonic()-start,3),'provider':'siliconflow_sensevoice'}
            flow.store(meta_path,flow.canonical(receipt)+b'\n')
        results.append(receipt)
        flow.replace_state(progress,{'phase':'transcribing','completed':len(results),'total':len(measured),'coverage_end_seconds':bounds[1],'updated_at':mq.now()})
        print(json.dumps({'phase':'segment_ready','completed':len(results),'total':len(measured)},ensure_ascii=False),flush=True)
    output=['# '+('播客/音频' if resource_kind=='audio' else '视频')+'完整音频转写（SenseVoice）','',f'原链接：{source_url}',f'规范链接：{canonical_url}',f'实际音频覆盖：0—{ranges[-1][1]:.3f}秒；页面时长约{expected:.3f}秒。','来源为本人授权的现有SenseVoice自动识别，逐段原始输出保留；不是平台AI章节，也不是人工校对字幕。时间仅为音频分段边界，不是逐句对齐。未核对完整画面，不代表本人已学习或掌握。','']
    for i,item in enumerate(results):
        output.extend([f'## 音频段{i+1}：{item["start_seconds"]:.3f}—{item["end_seconds"]:.3f}秒','',(work/f'part-{i:03d}.txt').read_text(encoding='utf-8').rstrip(),''])
    text='\n'.join(output).encode()
    manifest={'schema_version':1,'platform':platform,'resource_id':resource_id,'resource_kind':resource_kind,'source_url':source_url,'canonical_url':canonical_url,'status':'transcript_ready','content_source':['siliconflow_sensevoice_full_audio'],'checked_at':mq.now(),'text_file':{'path':'transcript.md','sha256':flow.digest(text)},'duration_seconds':expected,'audio_coverage_seconds':[0,ranges[-1][1]],'segments':results,'full_transcript_obtained':True,'audio_transcribed':True,'frames_reviewed':False,'visual_verified':False,'test_only':False,'count_as_owner_learning':False,'word_timestamps_available':False,'limitations':['ASR原始识别未经全文人工校对','分段边界不等于逐句字幕时间戳','没有核对完整视频画面']}
    raw=flow.canonical(manifest)+b'\n'
    bundle={'version':1,'platform':platform,'resource_id':resource_id,'files':{'result.json':base64.b64encode(raw).decode(),'transcript.md':base64.b64encode(text).decode()}}
    receipt=mq.receive(root,bundle)
    flow.replace_state(progress,{'phase':'completed','completed':len(results),'total':len(results),'audio_coverage_seconds':[0,ranges[-1][1]],'manifest_sha256':receipt['manifest_sha256'],'updated_at':mq.now()})
    return {'status':'transcript_ready','segments':len(results),'coverage_seconds':ranges[-1][1],'manifest_sha256':receipt['manifest_sha256'],'provider':'siliconflow_sensevoice'}


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    for a in ('root','platform','resource-id','source-url','canonical-url','media-file','ffmpeg','transcriber'):p.add_argument('--'+a,required=True)
    p.add_argument('--python',default=sys.executable);p.add_argument('--expected-seconds',type=float,required=True);p.add_argument('--segment-seconds',type=int,default=240)
    p.add_argument('--resource-kind',choices=['video','audio'],default='video')
    a=p.parse_args()
    r=run(Path(a.root).expanduser().resolve(),a.platform,a.resource_id,a.source_url,a.canonical_url,a.media_file,a.ffmpeg,a.transcriber,a.python,a.expected_seconds,a.segment_seconds,a.resource_kind)
    print(json.dumps(r,ensure_ascii=False),flush=True)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.SubprocessError,wave.Error) as e:
        print(json.dumps({'error':type(e).__name__,'detail':str(e) if isinstance(e,ValueError) else 'media transcription stopped; successful segments preserved'},ensure_ascii=False),file=sys.stderr);sys.exit(2)
