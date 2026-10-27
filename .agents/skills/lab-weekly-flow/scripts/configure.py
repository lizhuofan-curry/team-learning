#!/usr/bin/env python3
"""Generate local JSON with native paths; avoid hand-escaped Windows paths."""
import argparse
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
        obj['personal_vault'] = str(vault)
        obj['obsidian_reports'] = str(vault/'wiki/outputs/周报')
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
        backup = root/'config.local.previous.json'
        if backup.exists() and backup.read_bytes()!=dest.read_bytes():
            p.error('已有不同配置备份，请先核对config.local.previous.json，未更改配置')
        backup.write_bytes(dest.read_bytes())
    dest.write_bytes(raw)
    print(json.dumps({'config':str(dest),'mode':obj['mode']},ensure_ascii=False))


if __name__=='__main__':
    main()
