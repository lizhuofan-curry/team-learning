import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_docs


class CheckDocsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def write(self, name, content=''):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def issues(self):
        return check_docs.check_repository(self.root)[0]

    def test_chinese_paths_encoded_spaces_and_parentheses(self):
        self.write('附件/实验 (1).png')
        self.write('资料/README.md', '![图](../附件/实验%20(1).png)\n[图](<../附件/实验 (1).png>)')
        self.assertEqual([], self.issues())

    def test_missing_image_fails_and_fix_passes(self):
        self.write('README.md', '# 标题\n\n![图片](附件/缺失.png)\n')
        issues = self.issues()
        self.assertEqual(1, len(issues))
        self.assertEqual(3, issues[0].line)
        self.assertEqual('目标文件或附件不存在', issues[0].reason)
        self.write('附件/缺失.png')
        self.assertEqual([], self.issues())

    def test_references_external_links_and_anchors(self):
        self.write('附件/图.png')
        self.write('README.md', '[图片][图]\n\n[图]: 附件/图.png "标题"\n[网页](https://example.com/does-not-exist)\n[邮箱](mailto:a@example.com)\n[目录](#目录)')
        self.assertEqual([], self.issues())

    def test_broken_reference_definition_is_found(self):
        self.write('README.md', '[课件][课程]\n\n[课程]: 不存在.pdf')
        self.assertEqual(1, len(self.issues()))

    def test_code_and_comments_are_not_checked(self):
        self.write('README.md', '```markdown\n![例子](missing1.png)\n```\n~~~\n[例子](missing2.md)\n~~~\n`[例子](missing3.md)`\n    [例子](missing4.md)\n<!-- [例子](missing5.md) -->')
        self.assertEqual([], self.issues())

    def test_nested_list_links_fail_until_attachment_exists(self):
        self.write('README.md', '- 资料\n    - [课件](missing.pdf)\n')
        issues = self.issues()
        self.assertEqual(1, len(issues))
        self.assertEqual(2, issues[0].line)
        self.write('missing.pdf')
        self.assertEqual([], self.issues())

    def test_list_continuations_and_multiple_nesting_levels(self):
        for text in [
            '- 资料\n    [课件](missing.pdf)\n',
            '1. 资料\n    - 子目录\n        - [课件](missing.pdf)\n',
            '- 资料\n\n    - ![图片](missing.png)\n',
            '- 资料\n\t- [课件](missing.pdf)\n',
        ]:
            with self.subTest(text=text):
                self.write('README.md', text)
                self.assertEqual(1, len(self.issues()))

    def test_code_blocks_inside_lists_remain_ignored(self):
        for text in [
            '- 资料\n\n      [代码例子](missing.pdf)\n',
            '- 资料\n    - 子项\n\n          [代码例子](missing.pdf)\n',
            '- ```markdown\n  [代码例子](missing.pdf)\n  ```\n',
            '- 资料\n\n    ```markdown\n    [代码例子](missing.pdf)\n    ```\n',
            '-     [代码例子](missing.pdf)\n',
        ]:
            with self.subTest(text=text):
                self.write('README.md', text)
                self.assertEqual([], self.issues())

    def test_list_context_ends_before_top_level_code(self):
        self.write('README.md', '- 资料\n\n正文\n\n    [代码例子](missing.pdf)\n')
        self.assertEqual([], self.issues())

    def test_unclosed_list_fence_ends_with_its_containing_item(self):
        cases = [
            ('- ```text\n  example\n- [课件](missing.pdf)\n', 3),
            ('- ~~~text\n  example\n\n[课件](missing.pdf)\n', 4),
            ('1. ```text\n   example\n2. [课件](missing.pdf)\n', 3),
            ('- 父项\n  - ```text\n    example\n  - [课件](missing.pdf)\n', 4),
            ('- 父项\n  - ```text\n    example\n  [课件](missing.pdf)\n', 4),
        ]
        for text, line in cases:
            with self.subTest(text=text):
                self.write('README.md', text)
                issues = self.issues()
                self.assertEqual([(line, 'missing.pdf')],
                                 [(issue.line, issue.destination) for issue in issues])

    def test_unclosed_fence_keeps_masking_within_its_container(self):
        for text in [
            '```text\n- [代码例子](missing.pdf)\n',
            '- ```text\n\n  [代码例子](missing.pdf)\n',
            '- 父项\n  - ```text\n\n    [代码例子](missing.pdf)\n',
        ]:
            with self.subTest(text=text):
                self.write('README.md', text)
                self.assertEqual([], self.issues())

    def test_non_one_ordered_marker_cannot_interrupt_paragraph(self):
        for marker in ['0.', '2.', '99)', '123456789.']:
            with self.subTest(marker=marker):
                self.write('README.md', f'正文\n{marker} 接续正文\n\n    [代码例子](missing.pdf)\n')
                self.assertEqual([], self.issues())
        self.write('README.md', '- 正文\n  2. 接续正文\n\n      [代码例子](missing.pdf)\n')
        self.assertEqual([], self.issues())

    def test_ordered_lists_still_start_after_blocks_or_as_siblings(self):
        for text in [
            '正文\n1. 资料\n\n    [课件](missing.pdf)\n',
            '正文\n\n2. 资料\n\n    [课件](missing.pdf)\n',
            '# 标题\n2. 资料\n\n    [课件](missing.pdf)\n',
            '***\n2. 资料\n\n    [课件](missing.pdf)\n',
            '```text\nexample\n```\n2. 资料\n\n    [课件](missing.pdf)\n',
            '1. 前项\n2. 资料\n\n    [课件](missing.pdf)\n',
        ]:
            with self.subTest(text=text):
                self.write('README.md', text)
                self.assertEqual(1, len(self.issues()))

    def test_thematic_break_does_not_start_list_context(self):
        for divider in ['* * *', '- - -', '_ _ _', '***', '---', ' *  *  * ', '  - - -']:
            with self.subTest(divider=divider):
                self.write('README.md', divider + '\n\n    [代码例子](missing.pdf)\n')
                self.assertEqual([], self.issues())

    def test_thematic_break_inside_list_preserves_parent_context(self):
        self.write('README.md', '- 资料\n  * * *\n\n      [代码例子](missing.pdf)\n\n  [课件](missing2.pdf)\n')
        issues = self.issues()
        self.assertEqual(1, len(issues))
        self.assertEqual('missing2.pdf', issues[0].destination)

    def test_escaped_parentheses_and_fragment(self):
        self.write('资料(上).pdf')
        self.write('README.md', '[课件](资料\\(上\\).pdf#page=1)')
        self.assertEqual([], self.issues())

    def test_wikilinks_alias_and_image_dimensions(self):
        self.write('共同知识/ReAct.md', '# ReAct')
        self.write('附件/示意图.png')
        self.write('README.md', '[[ReAct#概念|解释]]\n![[示意图.png|300]]')
        self.assertEqual([], self.issues())

    def test_ambiguous_wikilink_requires_path(self):
        self.write('甲/笔记.md')
        self.write('乙/笔记.md')
        self.write('README.md', '[[笔记]]')
        self.assertIn('多个同名文件', self.issues()[0].reason)
        self.write('README.md', '[[甲/笔记]]')
        self.assertEqual([], self.issues())

    def test_dotted_note_wikilinks_and_aliases(self):
        self.write('共同知识/lecture.v2.md')
        self.write('README.md', '[[lecture.v2]]\n[[lecture.v2#概念|解释]]\n[[共同知识/lecture.v2]]')
        self.assertEqual([], self.issues())

    def test_dotted_note_name_ending_in_md(self):
        self.write('共同知识/lecture.md.md')
        self.write('README.md', '[[lecture.md]]')
        self.assertEqual([], self.issues())

    def test_dotted_notes_still_report_missing_or_ambiguous(self):
        self.write('README.md', '[[lecture.v2]]')
        self.assertEqual(1, len(self.issues()))
        self.write('甲/lecture.v2.md')
        self.write('乙/lecture.v2.md')
        self.assertIn('多个同名文件', self.issues()[0].reason)
        self.write('README.md', '[[甲/lecture.v2]]')
        self.assertEqual([], self.issues())

    def test_wikilink_attachments_keep_exact_path_resolution(self):
        self.write('附件/diagram.v2.png')
        self.write('共同知识/diagram.v2.png.md')
        self.write('README.md', '![[diagram.v2.png|300]]\n![[附件/diagram.v2.png]]')
        self.assertEqual([], self.issues())

    def test_machine_absolute_paths_are_reported(self):
        self.write('README.md', '[本机](file:///Users/example/note.md)\n[本机](C:/notes/note.md)')
        self.assertEqual(2, len(self.issues()))

    def test_outside_repository_link_is_reported(self):
        self.write('README.md', '[外部](../outside.md)')
        self.assertIn('仓库外部', self.issues()[0].reason)

    def test_gitignore_is_honored_but_new_notes_are_checked(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.write('.gitignore', 'local-only/\n')
        self.write('local-only/忽略.md', '[例子](missing.md)')
        self.write('README.md', '[新笔记](不存在.md)')
        self.assertEqual(1, len(self.issues()))

    def test_cli_exit_codes_change_after_repair(self):
        self.write('README.md', '![图片](图.png)')
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(sys, 'argv', ['check_docs.py', str(self.root)]):
                self.assertEqual(1, check_docs.main())
            self.write('图.png')
            with mock.patch.object(sys, 'argv', ['check_docs.py', str(self.root)]):
                self.assertEqual(0, check_docs.main())


if __name__ == '__main__':
    unittest.main()
