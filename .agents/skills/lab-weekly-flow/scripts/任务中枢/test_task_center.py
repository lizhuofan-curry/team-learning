"""Integration checks with isolated workflow sources, never the real queue."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

WORKFLOW = Path(__file__).resolve().parent.parent
if str(WORKFLOW) not in sys.path:
    sys.path.insert(0, str(WORKFLOW))

import collaboration_flow as collaboration
import media_queue as media
import task_center
from 任务中枢.task_hub import Hub


class TaskCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_cli_emits_utf8_under_a_non_unicode_default_stream(self):
        environment = dict(os.environ, PYTHONIOENCODING='cp1252', PYTHONUTF8='0')
        result = subprocess.run([sys.executable, str(WORKFLOW / 'task_center.py'),
                                 '--root', str(self.root), 'create', '--key', 'encoding',
                                 '--title', '中文任务'], env=environment, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout.decode('utf-8'))['title'], '中文任务')

    def media_record(self):
        return media.request(self.root, "https://example.com/learning", "isolated-fixture")

    def message(self):
        return collaboration.publish(self.root, "hermes", "isolated-message", "任务后续意见",
                                     "请继续核对结果；此原话不扩大操作权限。", kind="correction")

    def cli(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = task_center.main(["--root", str(self.root), *arguments])
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def source_bytes(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file() and "任务中枢" not in path.relative_to(self.root).parts}

    def test_repeated_sync_deduplicates_tasks_and_events(self):
        self.media_record()
        self.message()
        first = task_center.sync_sources(self.root)
        second = task_center.sync_sources(self.root)
        self.assertEqual((first["tasks_added"], first["events_added"]), (1, 1))
        self.assertEqual((second["tasks_added"], second["tasks_updated"], second["events_added"]), (0, 0, 0))
        with Hub(self.root) as hub:
            self.assertEqual(len(hub.list_tasks()), 1)
            self.assertEqual(len(hub.list_events()), 1)
        self.assertFalse(first["execution_started"])

    def test_projection_follows_original_queue_state(self):
        source = self.media_record()
        task_center.sync_sources(self.root)
        source["state"] = "blocked"
        source["last_error"] = "fixture: requires login"
        media.save_job(self.root, source)
        changed = task_center.sync_sources(self.root)
        self.assertEqual(changed["tasks_updated"], 1)
        with Hub(self.root) as hub:
            self.assertEqual(hub.list_tasks()[0]["status"], "blocked")
        # Read view must also reflect a newer source before another index sync.
        source["state"] = "delivery_pending"
        media.save_job(self.root, source)
        current = task_center.view(self.root)["tasks"][0]
        self.assertEqual(current["status"], "waiting")
        self.assertEqual(current["indexed_status"], "blocked")

    def test_sync_and_view_preserve_source_bytes_and_create_no_receipts(self):
        self.media_record()
        self.message()
        before = self.source_bytes()
        task_center.sync_sources(self.root)
        task_center.view(self.root)
        self.assertEqual(self.source_bytes(), before)
        self.assertFalse((self.root / "协作消息" / "读取回执").exists())

    def test_delivered_is_not_completed_or_personal_mastery(self):
        source = self.media_record()
        source["state"] = "delivered"
        media.save_job(self.root, source)
        task_center.sync_sources(self.root)
        task = task_center.view(self.root)["tasks"][0]
        self.assertEqual(task["status"], "awaiting_review")
        self.assertIn("不要求逐条本人批准", task["next_action"])
        self.assertNotIn("mastery", task)

    def test_sync_does_not_overwrite_manual_status(self):
        created = self.cli("create", "--key", "study", "--title", "核对学习结果")
        changed = self.cli("set-status", "--task", created["id"], "--status", "working",
                           "--revision", str(created["revision"]), "--next-action", "核对结果文件")
        self.media_record()
        task_center.sync_sources(self.root)
        with Hub(self.root) as hub:
            self.assertEqual(hub.get_task(created["id"]), changed)

    def test_cli_refuses_manual_mutation_of_media_projection(self):
        self.media_record()
        task_center.sync_sources(self.root)
        with Hub(self.root) as hub:
            task = hub.list_tasks()[0]
        with self.assertRaisesRegex(ValueError, "仅手工任务"):
            self.cli("set-status", "--task", task["id"], "--status", "completed",
                     "--revision", str(task["revision"]), "--evidence", "/tmp/fictional.json")
        with Hub(self.root) as hub:
            self.assertEqual(hub.get_task(task["id"]), task)

    def test_explicit_event_link_is_idempotent_and_survives_restart(self):
        self.message()
        task_center.sync_sources(self.root)
        task = self.cli("create", "--key", "follow-up", "--title", "核对后续意见")
        event = task_center.view(self.root)["unlinked_events"][0]
        first = self.cli("link", "--event", event["id"], "--task", task["id"])
        again = self.cli("link", "--event", event["id"], "--task", task["id"])
        self.assertEqual(first, again)
        self.assertEqual(task_center.view(self.root)["unlinked_events"], [])
        with Hub(self.root) as reopened:
            self.assertEqual(reopened.list_events(task["id"])[0]["id"], event["id"])
            self.assertEqual(reopened.get_task(task["id"])["status"], "queued")
        # Syncing the same original message preserves its explicit association.
        self.assertEqual(task_center.sync_sources(self.root)["events_added"], 0)
        self.assertEqual(self.cli("events", "--task", task["id"])[0]["task_id"], task["id"])

    def test_uninitialized_status_preview_and_attention_do_not_create_database(self):
        self.media_record()
        before = self.source_bytes()
        self.assertFalse(self.cli("status")["initialized"])
        self.assertFalse(self.cli("attention")["initialized"])
        self.assertEqual(len(self.cli("preview")["tasks"]), 1)
        self.assertFalse((self.root / "任务中枢").exists())
        self.assertEqual(self.source_bytes(), before)


if __name__ == "__main__":
    unittest.main()
