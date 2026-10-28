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
    '分工与课程覆盖.md', '资源索引.md',
}
TECH_DIRS = {'.github', '.agents', 'scripts', 'tests'}
GUIDE_DIRS = {'协作指南'}
TOPIC_DIRS = {'课程资料', '实验记录', '共同知识'}
LEARNING_DIRS = TOPIC_DIRS | {'周报'}
FORBIDDEN = re.compile(r'[<>:"\\|?*]|[\x00-\x1f]')
WINDOWS_RESERVED = re.compile(
    r'^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)',
    re.IGNORECASE,
)
TEMPORARY = re.compile(
    r'^(?:未命名\s*\d*|新建文件\s*\d*|新建文本文档\s*\d*)$'
    r'|final[_ -]+final|(?:[_ -]?副本(?:\s*\d*)?|[（(]副本[）)])$',
    re.IGNORECASE,
)
CHAPTER = re.compile(r'^第([0-9]{2})章$')
EXPERIMENT = re.compile(r'^([1-9][0-9]*)-([1-9][0-9]*)$')
MEMBER = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$')


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
        elif parts[0] not in LEARNING_DIRS | TECH_DIRS | GUIDE_DIRS:
            issues.add(f'{parts[0]}/: 未约定的顶层目录，请先明确用途并更新规范')
        if parts[0] in TOPIC_DIRS:
            if len(parts) == 2 and parts[1] != 'README.md':
                issues.add(f'{path}: 学习目录第一层只放README，资料请归入课程、项目或主题目录')
            elif len(parts) > 2:
                topics.add('/'.join(parts[:2]))
        # Numbered team experiments share one experiment index, while each
        # member owns a separate namespace for records, code and evidence.
        if parts[0] == '实验记录' and len(parts) >= 5:
            chapter = CHAPTER.fullmatch(parts[2])
            experiment = EXPERIMENT.fullmatch(parts[3])
            numbered = re.match(r'^[0-9]+[.-][0-9]+', parts[3])
            if numbered and (not chapter or not experiment):
                issues.add(f'{path}: 编号实验统一使用第NN章/章号-实验号，例如第01章/1-1')
            if chapter and experiment:
                if int(chapter[1]) != int(experiment[1]):
                    issues.add(f'{path}: 章节与实验编号不一致')
                if len(parts) == 5:
                    if parts[4] not in {'README.md', '对比分析.md'}:
                        issues.add(f'{path}: 个人实验记录请放在实验编号下的成员账号目录，避免覆盖同伴')
                elif not MEMBER.fullmatch(parts[4]) or '--' in parts[4]:
                    issues.add(f'{path}: 成员目录请使用小写GitHub账号，而非姓名、空格或临时名称')
                elif parts[-1].endswith('实验记录.md') and len(parts) == 6:
                    expected = f'{parts[3]}_{parts[4]}_实验记录.md'
                    if parts[5] != expected:
                        issues.add(f'{path}: 实验记录文件应命名为{expected}')
        # Include directories, not just leaves, in cross-platform collision checks.
        for length in range(1, len(parts) + 1):
            name = '/'.join(parts[:length])
            key = unicodedata.normalize('NFC', name).casefold()
            if key in seen and seen[key] != name:
                pair = sorted((seen[key], name))
                issues.add(f'{pair[0]} 与 {pair[1]}: 路径仅大小写或Unicode形式不同')
            else:
                seen[key] = name
        if parts[0] in LEARNING_DIRS | GUIDE_DIRS:
            for part in parts[1:]:
                if FORBIDDEN.search(part) or part.endswith((' ', '.')):
                    issues.add(f'{path}: 名称含跨平台不兼容字符或结尾空格、点')
                if WINDOWS_RESERVED.match(part):
                    issues.add(f'{path}: 名称使用Windows保留名称，请修改文件或目录名')
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
