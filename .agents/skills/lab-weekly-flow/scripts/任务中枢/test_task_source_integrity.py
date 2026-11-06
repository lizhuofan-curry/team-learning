"""Regression checks for cached tasks/events whose original source changed."""
import contextlib
import datetime as dt
import hashlib
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


class CachedSourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        # A healthy sync fixture makes the missing-source warning independently
        # observable instead of accidentally passing on an unrelated warning.
        stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
        path = self.root / "协作消息/同步状态/latest.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(version=1, status="ok", errors={},
                                        last_attempt=stamp, last_success=stamp)), encoding="utf-8")

    def cli(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = task_center.main(["--root", str(self.root), *arguments])
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def indexed_message(self):
        message = collaboration.publish(self.root, "hermes", "integrity-fixture",
                                        "实验后续意见", "请核对结果", kind="correction")
        task_center.sync_sources(self.root)
        with Hub(self.root) as hub:
            event = hub.list_events()[0]
            task = hub.register("manual", "integrity-target", "核对实验", "general")
        path = self.root / "协作消息/Hermes发出" / (message["id"] + ".json")
        return path, message, event, task

    def change_valid_message(self, path, message):
        # This remains a self-consistent source record. The cached event must
        # still refuse it because it is not the version originally indexed.
        message["text"] = "新的实验意见，须核对版本"
        message["text_sha256"] = hashlib.sha256(message["text"].encode("utf-8")).hexdigest()
        collaboration.validate_message(message)
        path.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")

    def assert_event_unavailable(self, event):
        result = task_center.view(self.root)
        current = next(item for item in result["unlinked_events"] if item["id"] == event["id"])
        self.assertFalse(current["source_available"])
        warning = next(item for item in result["observations"]
                       if item["code"] == "indexed_event_unavailable"
                       and item["external_id"] == event["external_id"])
        self.assertEqual(warning["severity"], "warning")
        # The immutable historical event remains intact and unlinked.
        with Hub(self.root) as hub:
            self.assertEqual(hub.list_events()[0], event)

    def test_event_conflict_keeps_history_and_indexes_other_event(self):
        path, message, event, task = self.indexed_message()
        self.cli("link", "--event", event["id"], "--task", task["id"])
        self.change_valid_message(path, message)
        newer = collaboration.publish(self.root, "hermes", "new-fixture-2",
                                      "后续意见", "独立事件")
        self.assertLess(message["id"], newer["id"])
        result = self.cli("sync")
        self.assertEqual(result["events_added"], 1)
        self.assertEqual(result["observations"][0]["code"], "immutable_event_conflict")
        with Hub(self.root) as hub:
            events = {item["external_id"]: item for item in hub.list_events()}
        self.assertEqual(events[message["id"]]["payload"], event["payload"])
        self.assertEqual(events[message["id"]]["task_id"], task["id"])
        self.assertIn(newer["id"], events)

    def test_oversized_lease_keeps_other_records_and_tick_state(self):
        invalid = media.request(self.root, "https://example.com/invalid-lease", "fixture")
        invalid.update(state="processing", lease_until=10**400)
        media.save_job(self.root, invalid)
        valid = media.request(self.root, "https://example.com/valid", "fixture")
        preview = self.cli("preview")
        self.assertEqual([t["external_id"] for t in preview["tasks"]], [valid["id"]])
        self.assertEqual(preview["observations"][0]["code"], "invalid_source_record")
        (self.root / "config.local.json").write_text('{"mode":"local"}', encoding="utf-8")
        (self.root / "task_center.local.json").write_text('{"enabled":true}', encoding="utf-8")
        (self.root / "协作消息/同步状态/latest.json").unlink()
        state, code = collaboration.tick(self.root, {"mode": "local", "role": "codex"})
        self.assertEqual((state["status"], code), ("ok", 0))
        self.assertEqual([o["code"] for o in state["task_center"]["observations"]],
                         ["invalid_source_record"])
        self.assertTrue((self.root / "协作消息/同步状态/latest.json").exists())

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")

    def test_source_directory_link_cannot_index_another_workflow(self):
        other = self.root / "other"
        chosen = self.root / "chosen"
        chosen.mkdir()
        collaboration.publish(other, "hermes", "other-fixture", "其他工作流", "隔离")
        self.symlink(chosen / "协作消息", other / "协作消息", directory=True)
        snapshot = task_center.build_snapshot(chosen)
        self.assertEqual(snapshot["events"], [])
        self.assertIn("invalid_source_record", [o["code"] for o in snapshot["observations"]])

    def test_index_rejects_links_to_another_workflow_state(self):
        other = self.root / "other"
        with Hub(other):
            pass
        folder = self.root / "任务中枢"
        self.symlink(folder, other / "任务中枢", directory=True)
        with self.assertRaises(ValueError):
            self.cli("create", "--key", "k", "--title", "隔离")
        with self.assertRaises(ValueError):
            self.cli("sync")
        if os.name == "nt":
            folder.rmdir()
        else:
            folder.unlink()
        folder.mkdir()
        database = folder / "state.sqlite3"
        self.symlink(database, other / "任务中枢/state.sqlite3")
        with self.assertRaises(ValueError):
            self.cli("create", "--key", "k", "--title", "隔离")
        lock_target = other / "lock"
        lock_target.touch()
        self.symlink(folder / ".sync.lock", lock_target)
        with self.assertRaises(ValueError):
            self.cli("sync")
        with Hub(other) as hub:
            self.assertEqual(hub.list_tasks(), [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_named_pipe_does_not_block_preview(self):
        folder = self.root / "协作消息/Hermes发出"
        folder.mkdir(parents=True)
        os.mkfifo(folder / "pipe.json")
        result = subprocess.run(
            [sys.executable, str(WORKFLOW / "task_center.py"), "--root", str(self.root), "preview"],
            capture_output=True, check=True, timeout=10)
        observations = json.loads(result.stdout)["observations"]
        self.assertEqual(observations[0]["code"], "invalid_source_record")

    def test_deleted_media_source_remains_visible_in_attention(self):
        record = media.request(self.root, "https://example.com/source-integrity", "fixture")
        task_center.sync_sources(self.root)
        path = self.root / "媒体队列/任务" / (record["id"] + ".json")
        path.unlink()
        status = task_center.view(self.root)
        task = status["tasks"][0]
        self.assertFalse(task["source_available"])
        self.assertEqual(task["status"], "waiting")
        attention = self.cli("attention")
        warning = next(item for item in attention["observations"]
                       if item["code"] == "indexed_source_unavailable"
                       and item["external_id"] == record["id"])
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(path.exists())

    def test_deleted_hermes_source_marks_cached_event_unavailable(self):
        path, message, event, task = self.indexed_message()
        path.unlink()
        self.assert_event_unavailable(event)
        self.assertFalse(path.exists())

    def test_changed_valid_hermes_source_marks_cached_event_unavailable(self):
        path, message, event, task = self.indexed_message()
        self.change_valid_message(path, message)
        before = path.read_bytes()
        self.assert_event_unavailable(event)
        self.assertEqual(path.read_bytes(), before)

    def test_link_refuses_deleted_hermes_source(self):
        path, message, event, task = self.indexed_message()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "原件当前无法核实"):
            self.cli("link", "--event", event["id"], "--task", task["id"])
        with Hub(self.root) as hub:
            self.assertIsNone(hub.list_events()[0]["task_id"])

    def test_link_refuses_changed_valid_hermes_source(self):
        path, message, event, task = self.indexed_message()
        self.change_valid_message(path, message)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "原件当前无法核实"):
            self.cli("link", "--event", event["id"], "--task", task["id"])
        self.assertEqual(path.read_bytes(), before)
        with Hub(self.root) as hub:
            self.assertIsNone(hub.list_events()[0]["task_id"])

    def test_verified_current_hermes_source_can_still_be_linked(self):
        path, message, event, task = self.indexed_message()
        before = path.read_bytes()
        linked = self.cli("link", "--event", event["id"], "--task", task["id"])
        self.assertEqual(linked["task_id"], task["id"])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / "协作消息/读取回执").exists())


if __name__ == "__main__":
    unittest.main()
