#!/usr/bin/env python3
"""Private media queue and checked packet transfer. Browsing is done by Codex tools."""
import argparse
import base64
import contextlib
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import learning_flow as flow

MAX_PACKET = 24_000_000
MAX_WIRE = 34_000_000
READY = {'article_ready', 'subtitle_ready', 'transcript_ready', 'partial_ready'}
TERMINAL = {'delivered', 'blocked', 'cancelled'}
URLS = re.compile(r'https?://[^\s<>"\u201c\u201d]+', re.I)
NAME = re.compile(r'[A-Za-z0-9_-]{1,128}')
JOB = re.compile(r'[a-f0-9]{24}')
TOKEN = re.compile(r'[a-f0-9]{32}')


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds')


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid URL')
    u = urlsplit(value)
    host = (u.hostname or '').lower().rstrip('.')
    if u.scheme not in ('https', 'http') or u.username or u.password or u.port not in (None, 80, 443):
        raise ValueError('only public HTTP(S) page URLs')
    if not host or '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
        raise ValueError('local/private host not supported')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('local/private address not supported')
    # Strip tracking only on these known platforms. Other query parameters may
    # select content; never turn a signed/private query into a new URL by guessing.
    params = parse_qsl(u.query, keep_blank_values=True)
    if host in ('www.douyin.com', 'douyin.com', 'v.douyin.com'):
        params = [(k,v) for k,v in params if k not in ('from', 'previous_page', 'enter_from') and not k.startswith('utm_')]
    elif host in ('www.bilibili.com', 'bilibili.com', 'b23.tv'):
        params = [(k,v) for k,v in params if k not in ('vd_source','spm_id_from','trackid','from_spmid','share_source','share_medium') and not k.startswith('utm_')]
    if any(re.search(r'token|secret|api.?key|password|signature|credential',k,re.I) for k,v in params):
        raise ValueError('credential-like URL query not queued')
    return urlunsplit((u.scheme,host,u.path or '/',urlencode(params),''))


def job_id(url):
    return flow.digest(normalize_url(url).encode())[:24]


def queue(root):
    return Path(root)/'媒体队列'


@contextlib.contextmanager
def locked(root,name='.lock'):
    if name not in ('.lock','.discovery.lock'):raise ValueError('invalid lock name')
    path=queue(root)/name
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with path.open('a+b') as f:
        if os.name=='nt':
            import msvcrt
            if path.stat().st_size==0:f.write(b'0');f.flush()
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        try:yield
        finally:
            if os.name=='nt':
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def path_for(root,identifier):
    if not JOB.fullmatch(identifier):raise ValueError('invalid job id')
    return queue(root)/'任务'/(identifier+'.json')


def jobs(root):
    result=[]
    for p in sorted((queue(root)/'任务').glob('*.json')):
        r=flow.read_json(p)
        if p!=path_for(root,r['id']) or r['id']!=job_id(r['url']):raise ValueError('job identity mismatch')
        result.append(r)
    return result


def save_job(root,j):
    p=path_for(root,j['id']);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    flow.replace_state(p,j);p.chmod(0o600)


def config(root):
    p=Path(root)/'media.local.json'
    return flow.read_json(p) if p.exists() else {'enabled':False}


def request(root,url,source,reason='resource pending local verification',test_only=False):
    url=normalize_url(url)
    if not isinstance(source,str) or not 0<len(source)<400:raise ValueError('invalid source')
    with locked(root):
        existing=next((j for j in jobs(root) if url==j['url'] or url in j.get('aliases',[])),None)
        if existing:
            if existing['test_only']!=test_only:raise ValueError('test/live resource collision')
            if source not in existing['sources']:
                existing['sources'].append(source);save_job(root,existing)
            return existing
        j={'version':1,'id':job_id(url),'url':url,'sources':[source],
           'reason':reason,'created_at':now(),'first_seen_epoch':time.time(),
           'state':'pending','attempts':0,'next_attempt_epoch':0,'test_only':test_only,'aliases':[]}
        save_job(root,j);return j


def discover(root):
    c=config(root)
    if not c.get('enabled'):return {'enabled':False,'added':0}
    since=flow.date_value(c['since']); added=0; skipped=0
    # Record first observation separately from the author's recorded event date.
    # Initial older records form a baseline; future arrivals are new even if an
    # upstream agent mistakenly stamps yesterday's date. Never rewrite originals
    # or infer occurrence dates from mtime.
    ledger=queue(root)/'发现状态.json'
    with locked(root,'.discovery.lock'):
        initial=not ledger.exists()
        state=flow.read_json(ledger) if not initial else {'version':1,'initialized_at':now(),'seen':{}}
        if state.get('version')!=1 or not isinstance(state.get('seen'),dict):raise ValueError('invalid discovery ledger')
        before={j['id'] for j in jobs(root)}
        changed=initial
        for date in sorted((Path(root)/'收件箱').glob('????-??-??')):
            for p in sorted(date.glob('*.json')):
                e=flow.validate_event(flow.read_json(p))
                if e['kind']!='user-original' or e['channel']!='wechat' or e.get('category')!='resource':continue
                if e['id'] in state['seen']:continue
                seen={'recorded_date':e['date'],'first_observed_at':now(),'status':'observed'}
                state['seen'][e['id']]=seen;changed=True
                if initial and e['date']<since:
                    seen['status']='baseline_old_record';continue
                if re.search(r'只收藏|仅收藏|只存链接|仅保存链接|先别读|不要读取|不要打开|不需要解析|不自动读取',e['text']):
                    seen['status']='bookmark_only';continue
                for raw in URLS.findall(e['text']):
                    raw=raw.rstrip('。，；、！!？?）)]}')
                    try:
                        j=request(root,raw,'capture:'+e['id'])
                        if e['date']<since:
                            with locked(root):
                                j=flow.read_json(path_for(root,j['id']))
                                warnings=j.setdefault('source_date_warnings',{})
                                warnings[e['id']]={'recorded_date':e['date'],'first_observed_at':seen['first_observed_at'],'basis':'newly observed inbox arrival; occurrence date not inferred'}
                                save_job(root,j)
                        if j['id'] not in before:added+=1;before.add(j['id'])
                        seen['status']='queued_or_already_known'
                    except ValueError:skipped+=1
        if changed:
            ledger.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            flow.replace_state(ledger,state);ledger.chmod(0o600)
    return {'enabled':True,'added':added,'skipped_urls':skipped}


def pending(root):
    c=config(root); current=time.time(); result=[]
    if not c.get('enabled'):return result
    with locked(root):
        for j in jobs(root):
            if j['state']=='processing' and j.get('lease_until',0)<=current:
                j['state']='pending' if j['attempts']<c.get('max_attempts',2) else 'blocked'
                j['last_error']='worker lease expired; interrupted attempt retained'
                j.pop('lease_token',None);save_job(root,j)
            if j['state'] in ('pending','retry_wait') and j.get('next_attempt_epoch',0)<=current and current-j['first_seen_epoch']>=c.get('grace_seconds',120):
                if not j['test_only']:result.append(j)
            elif j['state']=='delivery_pending' and not j['test_only']:
                result.append(j)
    return sorted(result,key=lambda j:(j['created_at'],j['id']))


def claim(root,identifier):
    c=config(root)
    if not c.get('enabled'):raise ValueError('media queue disabled')
    with locked(root):
        j=flow.read_json(path_for(root,identifier));current=time.time()
        if j['state'] not in ('pending','retry_wait') or j.get('next_attempt_epoch',0)>current:raise ValueError('job not claimable')
        if j['attempts']>=c.get('max_attempts',2):raise ValueError('attempt limit reached')
        j.update(state='processing',attempts=j['attempts']+1,lease_token=secrets.token_hex(16),lease_until=current+c.get('lease_seconds',1800),updated_at=now())
        save_job(root,j);return j


def safe_file(base,name):
    if not isinstance(name,str):raise ValueError('invalid content path')
    rel=PurePosixPath(name)
    if rel.is_absolute() or any(x in ('','..','.') for x in rel.parts) or '\\' in name or ':' in name or len(rel.parts)>5:
        raise ValueError('unsafe content path')
    p=base.joinpath(*rel.parts)
    if base.is_symlink() or p.is_symlink() or any(x.is_symlink() for x in p.parents if x!=base and base in x.parents):raise ValueError('symlink not supported')
    if not p.resolve().is_relative_to(base.resolve()):raise ValueError('content escapes packet')
    return p


def verify_bundle(bundle):
    if not isinstance(bundle,dict) or set(bundle)!={'version','platform','resource_id','files'} or bundle['version']!=1:raise ValueError('invalid packet bundle')
    for k in ('platform','resource_id'):
        if not isinstance(bundle[k],str) or not NAME.fullmatch(bundle[k]):raise ValueError('invalid media identity')
    if not isinstance(bundle['files'],dict) or len(bundle['files'])>25 or 'result.json' not in bundle['files']:raise ValueError('invalid packet files')
    files={};total=0
    for n,s in bundle['files'].items():
        safe_file(Path('/virtual-media-root'),n)
        if not isinstance(s,str) or len(s)>MAX_WIRE:raise ValueError('invalid base64 content')
        raw=base64.b64decode(s,validate=True);total+=len(raw)
        if total>MAX_PACKET:raise ValueError('media packet too large; select bounded content')
        files[n]=raw
    manifest=json.loads(files['result.json'])
    if manifest.get('schema_version')!=1 or manifest.get('platform')!=bundle['platform'] or manifest.get('resource_id')!=bundle['resource_id']:raise ValueError('manifest identity mismatch')
    if manifest.get('status') not in READY:raise ValueError('not a readable packet')
    normalize_url(manifest['canonical_url'])
    if not manifest.get('content_source') or not isinstance(manifest.get('test_only'),bool):raise ValueError('missing source/test marker')
    item=manifest['text_file']
    if not isinstance(item,dict) or not item.get('path','').endswith(('.md','.txt')):raise ValueError('text_file must identify UTF-8 text')
    refs=[item]+manifest.get('images',[])
    expected={'result.json'}
    for r in refs:
        n=r['path'];expected.add(n)
        if n=='result.json' or n not in files or flow.digest(files[n])!=r['sha256']:raise ValueError('content hash mismatch')
    if set(files)!=expected or len(refs)!=len(expected)-1:raise ValueError('undeclared/duplicate file')
    if not files[item['path']].decode('utf-8').strip():raise ValueError('empty text')
    if manifest.get('resource_kind')=='note_image_post':
        images=manifest.get('images',[])
        obtained=manifest['images_obtained'];read=manifest['images_visually_read'];total=manifest['images_expected_from_page']
        if not (isinstance(total,int) and total>0 and 0<=read<=obtained<=total and obtained==len(images)):raise ValueError('image coverage mismatch')
        if read!=sum(x.get('visual_read') is True for x in images):raise ValueError('read image flags mismatch')
        if manifest['status']=='article_ready' and (read!=total or manifest.get('visual_verified') is not True):raise ValueError('unread/missing images cannot be complete')
    return manifest,files


def packet(root,directory):
    base=Path(directory).resolve();media=(Path(root)/'媒体结果').resolve()
    if (Path(root)/'媒体结果').is_symlink():raise ValueError('symlink media directory')
    if not base.is_relative_to(media) or len(base.relative_to(media).parts)!=2:raise ValueError('packet must be under 媒体结果/platform/id')
    if Path(directory).is_symlink() or (base/'result.json').is_symlink():raise ValueError('symlink packet')
    m=flow.read_json(base/'result.json')
    names=['result.json',m['text_file']['path']]+[x['path'] for x in m.get('images',[])]
    files={}
    for n in names:
        f=safe_file(base,n)
        if f.stat().st_size>MAX_PACKET:raise ValueError('file too large')
        files[n]=base64.b64encode(f.read_bytes()).decode()
    b={'version':1,'platform':base.parent.name,'resource_id':base.name,'files':files}
    verify_bundle(b);return b


def receive(root,bundle):
    m,files=verify_bundle(bundle)
    base=Path(root)/'媒体结果'/bundle['platform']/bundle['resource_id']
    if base.is_symlink() or base.parent.is_symlink() or (Path(root)/'媒体结果').is_symlink():raise ValueError('symlink destination')
    with locked(root):
        base.mkdir(parents=True,exist_ok=True,mode=0o700)
        old=base/'result.json'
        if old.exists() and old.read_bytes()!=files['result.json']:
            prior=flow.read_json(old)
            if prior.get('status') in ('article_ready','subtitle_ready','transcript_ready'):
                raise ValueError('different complete packet exists; preserve it for review')
        for n,raw in files.items():
            p=safe_file(base,n)
            if p.exists() and p.read_bytes()!=raw:
                backup=base/'history'/(flow.digest(p.read_bytes())+'-'+p.name)
                flow.store(backup,p.read_bytes());backup.chmod(0o600)
        for n in sorted(files,key=lambda x:x=='result.json'):
            p=safe_file(base,n);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if p.exists() and p.read_bytes()==files[n]:continue
            # replace_state is JSON-only; media bytes need atomic replacement.
            import tempfile
            fd,name=tempfile.mkstemp(prefix='.media-',dir=str(p.parent))
            try:
                with os.fdopen(fd,'wb') as f:f.write(files[n])
                os.chmod(name,0o600);os.replace(name,p)
            finally:
                if os.path.exists(name):os.unlink(name)
        return {'status':'stored','manifest_sha256':flow.digest(files['result.json']),
                'files':{n:flow.digest(safe_file(base,n).read_bytes()) for n in files},
                'content_read_by_hermes_model':False}


def finish(root,identifier,token,directory=None,outcome=None,reason=None):
    if not TOKEN.fullmatch(token):raise ValueError('invalid lease token')
    b=packet(root,directory) if directory else None
    with locked(root):
        j=flow.read_json(path_for(root,identifier))
        if j['state']!='processing' or j.get('lease_token')!=token or j.get('lease_until',0)<time.time():raise ValueError('lease lost/expired')
        if b:
            m,files=verify_bundle(b)
            if j['test_only']!=m['test_only']:raise ValueError('test marker mismatch')
            canonical=normalize_url(m['canonical_url'])
            if canonical!=j['url'] and normalize_url(m.get('source_url',m['canonical_url']))!=j['url']:
                raise ValueError('packet URL does not match claimed resource')
            if canonical not in j['aliases']:j['aliases'].append(canonical)
            sha=flow.digest(files['result.json'])
            snap=queue(root)/'待回传'/identifier/(sha+'.json')
            flow.store(snap,flow.canonical(b)+b'\n');snap.chmod(0o600)
            j.update(state='delivery_pending',packet_sha256=sha,packet_path=snap.relative_to(queue(root)).as_posix(),content_status=m['status'])
        else:
            if outcome not in ('blocked','retry_wait','deferred'):raise ValueError('missing outcome')
            if not reason or len(reason)>2000:raise ValueError('missing bounded failure reason')
            if outcome=='deferred':
                # An unavailable browser/locked desktop is infrastructure, not
                # evidence that the resource itself failed an extraction.
                j['attempts']=max(0,j['attempts']-1)
                j['infrastructure_deferrals']=j.get('infrastructure_deferrals',0)+1
                final='retry_wait'
            else:
                final='blocked' if j['attempts']>=config(root).get('max_attempts',2) else outcome
            j.update(state=final,last_error=reason,next_attempt_epoch=time.time()+config(root).get('retry_seconds',900))
        j.pop('lease_token',None);j.pop('lease_until',None);j['updated_at']=now();save_job(root,j);return j


def remote_command(root,action,extra=()):
    c=flow.read_json(Path(root)/'collaboration.local.json')
    if c.get('mode')=='local':return None
    r=c['remote'];host=r['host']
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+',host) or host.startswith('-'):raise ValueError('invalid SSH alias')
    script=str(PurePosixPath(r['root'])/'media_queue.py')
    args=[r.get('python','python3'),script,'--root',r['root'],action]+list(extra)
    return ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',host,' '.join(shlex.quote(str(a)) for a in args)]


def transfer(root,action,extra=(),bundle=None):
    args=remote_command(root,action,extra)
    if args is None:
        if action=='receive':return receive(root,bundle)
        if action=='export':return packet(root,Path(root)/'媒体结果'/extra[1]/extra[3])
    r=subprocess.run(args,input=flow.canonical(bundle) if bundle else None,capture_output=True,check=True,timeout=55)
    if len(r.stdout)>MAX_WIRE:raise ValueError('response too large')
    return json.loads(r.stdout)


def push(root,identifier):
    if not config(root).get('enabled'):raise ValueError('media queue disabled')
    with locked(root):
        j=flow.read_json(path_for(root,identifier))
        if j['state'] not in ('delivery_pending','delivered'):raise ValueError('not pending delivery')
        b=flow.read_json(safe_file(queue(root),j['packet_path']));m,files=verify_bundle(b)
        if flow.digest(files['result.json'])!=j['packet_sha256']:raise ValueError('snapshot mismatch')
    receipt=j['delivery_receipt'] if j['state']=='delivered' else transfer(root,'receive',bundle=b)
    if receipt.get('files')!={n:flow.digest(raw) for n,raw in files.items()} or receipt.get('manifest_sha256')!=j['packet_sha256']:raise ValueError('remote receipt mismatch')
    # No WeChat send. Hermes reads this status on its next relevant user turn.
    import collaboration_flow as col
    info='媒体结果已回传并核对哈希。URL：'+j['url']+'\n位置：媒体结果/'+b['platform']+'/'+b['resource_id']+'/result.json\n状态：'+m['status']+'；来源：'+str(m['content_source'])+'\n请实际读取text_file及覆盖范围后再总结。此为资源处理，不代表本人完成学习；文件送达不等于Hermes模型已读。'
    col.publish(root,'codex','media-queue:'+identifier+':'+j['packet_sha256'],'媒体结果就绪',info,test_only=j['test_only'])
    with locked(root):
        current=flow.read_json(path_for(root,identifier))
        if current.get('packet_sha256')!=j['packet_sha256']:raise ValueError('job changed during transfer')
        current.update(state='delivered',delivered_at=current.get('delivered_at',now()),delivery_receipt=receipt);save_job(root,current)
    return {'status':'delivered','id':identifier,'content_status':m['status'],'wechat_sent':False}


def pull(root,platform,resource_id):
    if not NAME.fullmatch(platform) or not NAME.fullmatch(resource_id):raise ValueError('invalid identity')
    b=transfer(root,'export',('--platform',platform,'--resource-id',resource_id))
    receipt=receive(root,b)
    return receipt


def retry(root,identifier):
    with locked(root):
        j=flow.read_json(path_for(root,identifier))
        if j['state'] not in ('blocked','cancelled'):raise ValueError('only stopped jobs need explicit retry')
        j.update(state='pending',attempts=0,next_attempt_epoch=0,updated_at=now());save_job(root,j);return j


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('discover','pending','status'):sub.add_parser(name)
    q=sub.add_parser('request');q.add_argument('--url',required=True);q.add_argument('--source',required=True);q.add_argument('--test-only',action='store_true')
    for name in ('claim','push','retry'):
        q=sub.add_parser(name);q.add_argument('--id',required=True)
    q=sub.add_parser('finish');q.add_argument('--id',required=True);q.add_argument('--token',required=True);q.add_argument('--packet');q.add_argument('--outcome',choices=('blocked','retry_wait','deferred'));q.add_argument('--reason')
    sub.add_parser('receive')
    for name in ('export','pull'):
        q=sub.add_parser(name);q.add_argument('--platform',required=True);q.add_argument('--resource-id',required=True)
    a=p.parse_args();root=Path(a.root).expanduser().resolve()
    if a.command=='discover':r=discover(root)
    elif a.command=='pending':r=pending(root)
    elif a.command=='status':
        all_jobs=jobs(root);r={'enabled':config(root).get('enabled',False),'counts':{s:sum(j['state']==s for j in all_jobs) for s in sorted({j['state'] for j in all_jobs})}}
    elif a.command=='request':r=request(root,a.url,a.source,test_only=a.test_only)
    elif a.command=='claim':r=claim(root,a.id)
    elif a.command=='finish':r=finish(root,a.id,a.token,a.packet,a.outcome,a.reason)
    elif a.command=='push':r=push(root,a.id)
    elif a.command=='retry':r=retry(root,a.id)
    elif a.command=='receive':
        raw=sys.stdin.buffer.read(MAX_WIRE+1)
        if len(raw)>MAX_WIRE:raise ValueError('wire packet too large')
        r=receive(root,json.loads(raw))
    elif a.command=='export':
        if not NAME.fullmatch(a.platform) or not NAME.fullmatch(a.resource_id):raise ValueError('invalid identity')
        r=packet(root,root/'媒体结果'/a.platform/a.resource_id)
    else:r=pull(root,a.platform,a.resource_id)
    print(json.dumps(r,ensure_ascii=False));return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as e:
        print(json.dumps({'error':type(e).__name__,'detail':str(e) if isinstance(e,ValueError) else '媒体操作未完成；原件保留，未输出连接或凭据正文'},ensure_ascii=False),file=sys.stderr)
        sys.exit(2)
