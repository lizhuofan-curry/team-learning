#!/usr/bin/env python3
"""Generate local JSON with native paths; avoid hand-escaped Windows paths."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--personal-vault')
    p.add_argument('--weekly-archive')
    p.add_argument('--obsidian-reports', help='本人明确选择的Obsidian周报目录；不指定时保留已有值')
    p.add_argument('--archive-wechat-originals', action='store_true')
    p.add_argument('--mode', choices=['local','cloud'])
    p.add_argument('--remote-host')
    p.add_argument('--remote-root')
    a = p.parse_args()
    root = Path(a.root).expanduser().resolve()
    dest = root/'config.local.json'
    obj = json.loads(dest.read_text(encoding='utf-8-sig')) if dest.exists() else {'mode':'local'}
    if a.mode:
        obj['mode'] = a.mode
    if a.personal_vault:
        vault = Path(a.personal_vault).expanduser().resolve()
        old_vault=obj.get('personal_vault')
        changing=bool(old_vault and Path(old_vault).expanduser().resolve()!=vault)
        if changing and obj.get('raw_captures') and not a.archive_wechat_originals:
            p.error('更换个人库时原话目录仍指向旧位置；请明确选择--archive-wechat-originals的新库默认目录，或另建工作流并配置本人选择的位置。原配置未更改。')
        if changing and obj.get('obsidian_reports') and not a.obsidian_reports:
            p.error('更换个人库时请用--obsidian-reports明确新周报位置，避免继续写旧库。原配置未更改。')
        obj['personal_vault'] = str(vault)
        if not obj.get('obsidian_reports') and (not vault.exists() or (vault/'wiki').is_dir()):
            obj['obsidian_reports'] = str(vault/'wiki/outputs/周报')
    if a.obsidian_reports:
        obj['obsidian_reports'] = str(Path(a.obsidian_reports).expanduser().resolve())
    if a.weekly_archive:
        obj['weekly_archive'] = str(Path(a.weekly_archive).expanduser().resolve())
    if a.archive_wechat_originals:
        if not obj.get('personal_vault'):
            p.error('追加原话须先指定--personal-vault')
        obj['raw_captures'] = str(Path(obj['personal_vault'])/'raw/学习记录/微信素材')
    if a.remote_host or a.remote_root:
        if not a.remote_host or not a.remote_root or not a.remote_root.startswith('/'):
            p.error('云端须同时填写--remote-host及Linux服务器绝对路径--remote-root')
        obj['remote'] = dict(host=a.remote_host, python='python3', root=a.remote_root,
                             script=a.remote_root.rstrip('/')+'/learning_flow.py')
    if obj.get('mode') == 'cloud' and not obj.get('remote'):
        p.error('cloud模式缺少remote配置')
    root.mkdir(parents=True,exist_ok=True)
    raw = (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode()
    if dest.exists() and dest.read_bytes()!=raw:
        old=dest.read_bytes()
        backup = root/'config.local.previous.json'
        history=root/'config.local.backups'/(hashlib.sha256(old).hexdigest()+'.json')
        history.parent.mkdir(parents=True,exist_ok=True)
        if history.exists() and history.read_bytes()!=old:
            p.error('配置历史备份内容不匹配，未更改配置')
        if not history.exists():
            history.write_bytes(old)
        if not backup.exists():
            backup.write_bytes(old)
    dest.write_bytes(raw)
    needs=[]
    if obj.get('personal_vault') and not obj.get('obsidian_reports'):
        needs.append('已有个人库不采用raw/wiki结构，请本人选择周报归档目录并使用--obsidian-reports；尚未配置Obsidian周报归档。')
    print(json.dumps({'config':str(dest),'mode':obj['mode'],'needs_configuration':needs},ensure_ascii=False))


if __name__=='__main__':
    main()
