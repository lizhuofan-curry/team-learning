#!/usr/bin/env python3
"""Install only this user skill and its bridge; never edit gateway credentials."""
import argparse
import json
from pathlib import Path
import sys


def write_identical(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f'已存在不同内容，不覆盖：{path}')
    if not path.exists():
        path.write_bytes(raw)


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hermes-home', required=True)
    p.add_argument('--workflow-root', required=True)
    a = p.parse_args()
    home = Path(a.hermes_home).expanduser().resolve()
    root = Path(a.workflow_root).expanduser().resolve()
    package = Path(__file__).resolve().parent.parent
    skill = home / 'skills/productivity/lab-learning-capture'
    script = root / 'learning_flow.py'
    # Preflight all files before any write.
    files = {
        skill / 'SKILL.md': (package / 'assets/hermes-skill/capture-skill.md').read_bytes(),
        script: (package / 'scripts/learning_flow.py').read_bytes(),
        root / 'collaboration_flow.py': (package / 'scripts/collaboration_flow.py').read_bytes(),
        root / 'auto_capture.py': (package / 'scripts/auto_capture.py').read_bytes(),
        skill / 'capture.local.json': (json.dumps({'workflow_root': str(root), 'script': str(script), 'python': sys.executable}, ensure_ascii=False, indent=2)+'\n').encode()
    }
    for dest, raw in files.items():
        if dest.exists() and dest.read_bytes() != raw:
            raise ValueError(f'已有不同内容，不覆盖：{dest}')
    for dest, raw in files.items():
        write_identical(dest, raw)
    if not (root / 'config.local.json').exists():
        write_identical(root / 'config.local.json', b'{"mode": "local"}\n')
    if not (root / 'collaboration.local.json').exists():
        write_identical(root / 'collaboration.local.json', b'{"version":1,"role":"hermes","mode":"local"}\n')
    print(json.dumps({'skill':str(skill),'root':str(root),'script':str(script)},ensure_ascii=False))


if __name__ == '__main__':
    main()
