#!/usr/bin/env python3
"""Check repository-local Markdown links and Obsidian wikilinks, offline.

Run: python3 scripts/check_docs.py .
External URLs and heading/block anchors are not checked. This is not a full
Markdown/HTML renderer: raw HTML links and dynamically generated paths are out
of scope. Code examples and HTML comments are ignored.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
from pathlib import Path
import re
import subprocess
from typing import Optional
from urllib.parse import unquote, urlsplit


SKIP_DIRS = {'.git', '.obsidian', '.venv', 'node_modules', '__pycache__', 'tmp'}
INLINE_LINK = re.compile(r'(?<!\\)!?\[(?:\\.|[^\]\\\n])*\]\(')
REFERENCE = re.compile(r'^ {0,3}\[[^\]\n]+\]:[ \t]*', re.MULTILINE)
WIKILINK = re.compile(r'(?<!\\)!?\[\[([^\]\n]+)\]\]')
SCHEME = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*:')


@dataclass(frozen=True)
class Link:
    line: int
    destination: str
    wiki: bool = False


@dataclass(frozen=True)
class Issue:
    file: str
    line: int
    destination: str
    reason: str


def blank(text: str) -> str:
    return ''.join('\n' if ch == '\n' else ' ' for ch in text)


def visible_markdown(text: str) -> str:
    """Keep offsets/line numbers while masking common code blocks and spans."""
    result = []
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence:
            result.append(blank(line))
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
        elif marker:
            fence = (marker[1][0], len(marker[1]))
            result.append(blank(line))
        elif line.startswith(('    ', '\t')):
            result.append(blank(line))
        else:
            result.append(line)
    masked = ''.join(result)
    masked = re.sub(r'<!--.*?-->', lambda m: blank(m[0]), masked, flags=re.DOTALL)
    return re.sub(r'(`+)(.*?)\1', lambda m: blank(m[0]), masked, flags=re.DOTALL)


def destination_at(text: str, start: int) -> Optional[str]:
    """Read an angle-bracket destination or a balanced bare destination."""
    while start < len(text) and text[start].isspace():
        start += 1
    if start == len(text):
        return None
    if text[start] == '<':
        end = re.search(r'(?<!\\)>', text[start + 1:])
        return text[start + 1:start + 1 + end.start()] if end else None
    depth = 0
    i = start
    while i < len(text):
        char = text[i]
        if char == '\\' and i + 1 < len(text):
            i += 2
            continue
        if char == '(':
            depth += 1
        elif char == ')':
            if depth == 0:
                break
            depth -= 1
        elif char.isspace() and depth == 0:
            break
        i += 1
    return text[start:i]


def extract_links(text: str) -> list[Link]:
    masked = visible_markdown(text)
    links = []
    for pattern in (INLINE_LINK, REFERENCE):
        for match in pattern.finditer(masked):
            destination = destination_at(masked, match.end())
            if destination:
                links.append(Link(masked.count('\n', 0, match.start()) + 1, destination))
    for match in WIKILINK.finditer(masked):
        links.append(Link(masked.count('\n', 0, match.start()) + 1, match[1], True))
    return sorted(links, key=lambda link: link.line)


def repository_files(root: Path) -> list[Path]:
    """Honor gitignore when checking a checkout, including new local files."""
    if (root / '.git').exists():
        result = subprocess.run(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        files = [root / name.decode('utf-8') for name in result.stdout.split(b'\0') if name]
    else:
        files = [path for path in root.rglob('*') if path.is_file()]
    return sorted(set(path for path in files if path.is_file() and
                      not SKIP_DIRS.intersection(path.relative_to(root).parts)))


def local_destination(link: Link) -> Optional[str]:
    value = html.unescape(link.destination.strip())
    if link.wiki:
        value = value.split('|', 1)[0].strip()
    value = re.sub(r'\\([\\`*_{}\[\]()#+.!<> -])', r'\1', value)
    if not value or value.startswith('#'):
        return None
    if value.startswith('//'):
        return None
    if value.lower().startswith('file:') or re.match(r'^[A-Za-z]:[\\/]', value):
        raise ValueError('本机绝对路径不能供队友使用，请改为仓库内相对路径')
    if SCHEME.match(value):
        return None
    value = unquote(urlsplit(value).path)
    if not value:
        return None
    if Path(value).is_absolute() or '\\' in value:
        raise ValueError('请使用仓库内相对路径，并用 / 分隔目录')
    return value


def check_target(root: Path, source: Path, link: Link, files: list[Path]) -> Optional[str]:
    try:
        target = local_destination(link)
    except ValueError as error:
        return str(error)
    if target is None:
        return None
    variants = [target]
    if link.wiki and not Path(target).suffix:
        variants.append(target + '.md')
    bases = [source.parent]
    if link.wiki:
        bases.append(root)
    for base in bases:
        for variant in variants:
            path = (base / variant).resolve()
            if not path.is_relative_to(root):
                return '链接指向仓库外部，队友克隆后无法获取'
            if path.exists():
                return None
    if link.wiki:
        matches = {
            path for path in files
            if any(path.relative_to(root).as_posix() == variant or
                   path.relative_to(root).as_posix().endswith('/' + variant)
                   for variant in variants)
            and path.exists() and path.resolve().is_relative_to(root)
        }
        if len(matches) == 1:
            return None
        if len(matches) > 1:
            return '双链匹配到多个同名文件，请补充目录路径'
    return '目标文件或附件不存在'


def check_repository(root: Path) -> tuple[list[Issue], int, int]:
    root = root.resolve()
    files = repository_files(root)
    documents = [path for path in files if path.suffix.lower() in {'.md', '.markdown'}]
    issues = []
    count = 0
    for path in documents:
        relative = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root):
            issues.append(Issue(relative, 1, '', 'Markdown 文件链接到仓库外部'))
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as error:
            issues.append(Issue(relative, 1, '', '无法读取 Markdown：' + type(error).__name__))
            continue
        for link in extract_links(text):
            count += 1
            reason = check_target(root, path, link, files)
            if reason:
                issues.append(Issue(relative, link.line, link.destination, reason))
    return issues, len(documents), count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path('.'))
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error('仓库目录不存在')
    try:
        issues, documents, links = check_repository(args.root)
    except (OSError, subprocess.CalledProcessError) as error:
        print('检查无法完成：' + type(error).__name__)
        return 2
    for issue in issues:
        print(f'{issue.file}:{issue.line}: 错误：{issue.reason} [{issue.destination!r}]')
    print(f'检查 {documents} 篇 Markdown、{links} 个链接；发现 {len(issues)} 个错误。')
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
