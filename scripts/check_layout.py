#!/usr/bin/env python3
"""Check team-learning file placement and portable names; no file mutations."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import unicodedata

from check_docs import repository_files


ROOT_FILES = {
    'README.md', 'AGENTS.md', '.gitignore', '.gitattributes',
    '协作约定.md', '分工与课程覆盖.md', '资源索引.md',
    'Git协作入门.md', 'Agent资料整理指南.md', '文件组织规范.md',
}
TECH_DIRS = {'.github', '.agents', 'scripts', 'tests'}
TOPIC_DIRS = {'课程资料', '实验资料', '共同知识'}
LEARNING_DIRS = TOPIC_DIRS | {'周报'}
FORBIDDEN = re.compile(r'[<>:"\\|?*]|[\x00-\x1f]')
TEMPORARY = re.compile(
    r'^(?:未命名\s*\d*|新建文件\s*\d*|新建文本文档\s*\d*)$'
    r'|final[_ -]+final|(?:[_ -]?副本(?:\s*\d*)?|[（(]副本[）)])$',
    re.IGNORECASE,
)


def check_layout(root: Path) -> tuple[list[str], int]:
    root = root.resolve()
    files = repository_files(root)
    relative = [p.relative_to(root) for p in files]
    paths = {p.as_posix() for p in relative}
    issues = set()
    seen = {}
    topics = set()
    for path in relative:
        parts = path.parts
        if len(parts) == 1:
            if parts[0] not in ROOT_FILES:
                issues.add(f'{path}: 根目录只放约定的入口文件，请将资料归入学习目录或说明新增入口用途')
        elif parts[0] not in LEARNING_DIRS | TECH_DIRS:
            issues.add(f'{parts[0]}/: 未约定的顶层目录，请先明确用途并更新规范')
        if parts[0] in TOPIC_DIRS:
            if len(parts) == 2 and parts[1] != 'README.md':
                issues.add(f'{path}: 学习目录第一层只放README，资料请归入课程、项目或主题目录')
            elif len(parts) > 2:
                topics.add('/'.join(parts[:2]))
        # Include directories, not just leaves, in cross-platform collision checks.
        for length in range(1, len(parts) + 1):
            name = '/'.join(parts[:length])
            key = unicodedata.normalize('NFC', name).casefold()
            if key in seen and seen[key] != name:
                pair = sorted((seen[key], name))
                issues.add(f'{pair[0]} 与 {pair[1]}: 路径仅大小写或Unicode形式不同')
            else:
                seen[key] = name
        if parts[0] in LEARNING_DIRS:
            for part in parts[1:]:
                if FORBIDDEN.search(part) or part.endswith((' ', '.')):
                    issues.add(f'{path}: 名称含跨平台不兼容字符或结尾空格、点')
                if TEMPORARY.search(Path(part).stem):
                    issues.add(f'{path}: 名称含临时或模糊副本标记，请写明主题或版本')
    for topic in topics:
        if topic + '/README.md' not in paths:
            issues.add(f'{topic}/: 缺少README.md，请提供资料范围、来源和主要文件入口')
    return sorted(issues), len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path('.'))
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error('仓库目录不存在')
    try:
        issues, files = check_layout(args.root)
    except (OSError, subprocess.CalledProcessError) as error:
        print('布局检查无法完成：' + type(error).__name__)
        return 2
    for issue in issues:
        print('错误：' + issue)
    print(f'布局检查 {files} 个文件；发现 {len(issues)} 个错误。')
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
