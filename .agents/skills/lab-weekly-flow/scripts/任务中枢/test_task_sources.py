import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
    from . import task_sources as sources
except ImportError:
    import task_sources as sources


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = dt.datetime(2026, 11, 6, 12, 0, tzinfo=sources.TIMEZONE)

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def media(self, state="pending", test_only=False, suffix="one", **extra):
        url = "https://example.com/" + suffix
        identifier = sources.media.job_id(url)
        record = dict(version=1, id=identifier, url=url, state=state,
                      test_only=test_only, created_at=self.now.isoformat(), **extra)
        return self.write("媒体队列/任务/" + identifier + ".json", record)

    def hermes(self, test_only=False, source_id="message-one"):
        body = "私密原文，不应复制到投影或作为命令执行"
        record = dict(version=1, id=sources.collaboration.msg_id("hermes", source_id),
                      sender="hermes", source_id=source_id,
                      created_at=self.now.isoformat(), kind="correction", topic="实验修正",
                      text=body, text_sha256=hashlib.sha256(body.encode()).hexdigest(),
                      supersedes=None, test_only=test_only)
        return self.write("协作消息/Hermes发出/" + record["id"] + ".json", record)

    def sync(self, **changes):
        data = dict(version=1, status="ok", errors={},
                    last_attempt=self.now.isoformat(), last_success=self.now.isoformat())
        data.update(changes)
        return self.write("协作消息/同步状态/latest.json", data)

    def snapshot(self, **kwargs):
        return sources.build_snapshot(self.root, now=self.now, **kwargs)

    def test_mapping_preserves_delivery_vs_learning_distinction(self):
        for state in sources.STATE_MAP:
            extra = {"lease_until": self.now.timestamp() + 60} if state == "processing" else {}
            self.media(state, suffix=state, **extra)
        self.sync()
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["tasks"]), len(sources.STATE_MAP))
        self.assertNotIn("completed", {task["status"] for task in snapshot["tasks"]})
        delivered_id = sources.media.job_id("https://example.com/delivered")
        delivered = next(task for task in snapshot["tasks"] if task["external_id"] == delivered_id)
        self.assertEqual(delivered["status"], "awaiting_review")

    def test_snapshot_does_not_write_or_recover_expired_queue(self):
        self.media("processing", lease_until=self.now.timestamp() - 1)
        self.hermes()
        self.sync()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        snapshot = self.snapshot()
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn("media_lease_expired", {item["code"] for item in snapshot["observations"]})
        self.assertEqual(snapshot["tasks"][0]["status"], "working")

    def test_private_event_body_is_not_copied_or_auto_linked(self):
        path = self.hermes()
        self.sync()
        event = self.snapshot()["events"][0]
        self.assertIsNone(event["task_ref"])
        self.assertNotIn("text", event["payload"])
        self.assertEqual(event["payload"]["reference"], str(path.resolve()))
        self.assertIn("message_sha256", event["payload"])

    def test_partial_delivery_keeps_coverage_limit_as_information(self):
        self.media("delivered", content_status="partial_ready")
        self.sync()
        snapshot = self.snapshot()
        observation = snapshot["observations"][0]
        self.assertEqual(observation["code"], "media_content_partial")
        self.assertEqual(observation["severity"], "info")
        self.assertIn("不要求逐条本人批准", snapshot["tasks"][0]["next_action"])

    def test_test_records_are_hidden_by_default(self):
        self.media(test_only=True)
        self.hermes(test_only=True)
        self.sync()
        self.assertEqual(self.snapshot()["tasks"], [])
        self.assertEqual(self.snapshot()["events"], [])
        self.assertEqual(len(self.snapshot(include_tests=True)["tasks"]), 1)
        self.assertEqual(len(self.snapshot(include_tests=True)["events"]), 1)

    def test_bad_record_does_not_hide_valid_records(self):
        self.media()
        bad = self.root / "媒体队列/任务/broken.json"
        bad.write_text("{", encoding="utf-8")
        self.sync()
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["tasks"]), 1)
        self.assertIn("invalid_source_record", {item["code"] for item in snapshot["observations"]})

    def test_media_identity_mismatch_is_rejected(self):
        path = self.media()
        data = json.loads(path.read_text()); data["url"] += "wrong"
        path.write_text(json.dumps(data))
        self.assertEqual(self.snapshot()["tasks"], [])

    def test_hermes_content_hash_is_verified(self):
        path = self.hermes()
        data = json.loads(path.read_text()); data["text"] = "tampered"
        path.write_text(json.dumps(data))
        self.assertEqual(self.snapshot()["events"], [])

    def test_missing_sync_does_not_create_directories(self):
        before = list(self.root.iterdir())
        self.assertEqual(self.snapshot()["observations"][0]["code"], "sync_missing")
        self.assertEqual(list(self.root.iterdir()), before)

    def test_stale_sync_is_not_claimed_as_failure(self):
        old = (self.now - dt.timedelta(minutes=16)).isoformat()
        self.sync(last_success=old, last_attempt=old)
        observation = self.snapshot()["observations"][0]
        self.assertEqual(observation["code"], "sync_stale")
        self.assertIn("不能仅据此诊断", observation["detail"])

    def test_sync_error_does_not_expose_error_details(self):
        self.sync(status="retry_pending", errors={"ssh": "private credential-like details"})
        serialized = json.dumps(self.snapshot(), ensure_ascii=False)
        self.assertNotIn("private credential-like details", serialized)
        self.assertIn("sync_needs_check", serialized)

    def test_invalid_sync_and_naive_time(self):
        self.sync(last_success="bad")
        self.assertEqual(self.snapshot()["observations"][0]["code"], "invalid_source_record")
        with self.assertRaises(ValueError):
            sources.build_snapshot(self.root, now=dt.datetime(2026, 11, 6))


if __name__ == "__main__":
    unittest.main()
