import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_layout


class CheckLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('用于检查文件布局', encoding='utf-8')

    def issues(self):
        return check_layout.check_layout(self.root)[0]

    def test_known_layout_and_technical_code_names_pass(self):
        for name in ['README.md', '.github/workflows/check-docs.yml',
                     '.agents/skills/team-learning-materials/SKILL.md',
                     '实验资料/AgentBook/README.md', '实验资料/AgentBook/第04章/代码/main.py',
                     '课程资料/数据结构/README.md', '课程资料/数据结构/课件/线性表.pdf',
                     '共同知识/Agent基础/README.md', '共同知识/Agent基础/ReAct.md',
                     '周报/李卓凡/李卓凡2026-10-19_2026-10-25_周报.md']:
            self.write(name)
        self.assertEqual([], self.issues())

    def test_concentrated_guides_are_allowed_but_loose_root_guides_fail(self):
        self.write('协作指南/README.md')
        self.write('协作指南/文件组织规范.md')
        self.write('协作指南/模板/共享笔记模板.md')
        self.assertEqual([], self.issues())
        self.write('文件组织规范.md')
        self.assertTrue(any('根目录' in item for item in self.issues()))

    def test_root_loose_files_and_unknown_directory_fail(self):
        self.write('线性表.pdf')
        self.write('随便放/笔记.md')
        self.assertTrue(any('根目录' in s for s in self.issues()))
        self.assertTrue(any('顶层目录' in s for s in self.issues()))

    def test_course_loose_file_and_missing_readme_fail_then_pass(self):
        self.write('课程资料/线性表.pdf')
        self.assertTrue(any('第一层' in s for s in self.issues()))
        (self.root / '课程资料/线性表.pdf').unlink()
        self.write('课程资料/数据结构/线性表.pdf')
        self.assertTrue(any('缺少README' in s for s in self.issues()))
        self.write('课程资料/数据结构/README.md')
        self.assertEqual([], self.issues())

    def test_temporary_names_fail_without_rejecting_versioned_notes(self):
        self.write('共同知识/Agent基础/README.md')
        for name in ['未命名 1.md', '学习笔记_副本.md', '笔记_final_final.md']:
            self.write('共同知识/Agent基础/' + name)
        self.assertEqual(3, len(self.issues()))
        for path in (self.root / '共同知识/Agent基础').glob('*.md'):
            if path.name != 'README.md':
                path.unlink()
        self.write('共同知识/Agent基础/草稿状态与版本v2.md')
        self.assertEqual([], self.issues())

    def test_incompatible_name_is_reported(self):
        self.write('课程资料/数据结构/README.md')
        self.write('课程资料/数据结构/线性表:课件.pdf')
        self.assertTrue(any('不兼容' in s for s in self.issues()))

    def test_case_collision_also_detects_conflicting_directory_names(self):
        # Pure path fixture remains meaningful on case-insensitive macOS disks.
        with mock.patch.object(check_layout, 'repository_files', return_value=[
            self.root.resolve() / 'scripts/Task/a.py',
            self.root.resolve() / 'scripts/task/b.py',
        ]):
            self.assertTrue(any('仅大小写' in s for s in self.issues()))

    def test_ignored_files_not_checked_but_new_files_are_checked(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.write('.gitignore')
        (self.root / '.gitignore').write_text('本机临时/\n', encoding='utf-8')
        self.write('本机临时/未命名.md')
        self.assertEqual([], self.issues())
        self.write('新建文件.md')
        self.assertTrue(self.issues())

    def test_cli_failure_and_repair_exit_codes(self):
        self.write('资料.pdf')
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
            sys, 'argv', ['check_layout.py', str(self.root)]
        ):
            self.assertEqual(1, check_layout.main())
            (self.root / '资料.pdf').unlink()
            self.write('README.md')
            self.assertEqual(0, check_layout.main())


if __name__ == '__main__':
    unittest.main()
