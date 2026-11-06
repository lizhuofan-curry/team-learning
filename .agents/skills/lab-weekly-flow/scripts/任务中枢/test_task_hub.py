from pathlib import Path
import tempfile
import unittest

try:
    from .task_hub import Hub
except ImportError:
    from task_hub import Hub


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.hub = Hub(self.root)

    def tearDown(self):
        self.hub.close()
        self.temp.cleanup()

    def task(self, identifier="a", **kwargs):
        return self.hub.register("manual", identifier, "任务", "research", **kwargs)

    def test_registration_is_stable_and_does_not_overwrite(self):
        first = self.task()
        again = self.hub.register("manual", "a", "变更标题", "research", status="working")
        self.assertEqual(first, again)
        with self.assertRaises(ValueError):
            self.task(test_only=True)
        self.assertEqual(len(self.hub.list_tasks()), 1)

    def test_completion_requires_evidence_and_valid_scope(self):
        task = self.task()
        with self.assertRaises(ValueError):
            self.hub.set_status(task["id"], "completed")
        with self.assertRaises(ValueError):
            self.hub.set_status(task["id"], "mastered")
        with self.assertRaises(ValueError):
            self.task("wide", scope="execute_anything")
        done = self.hub.set_status(task["id"], "completed", evidence=["/tmp/result.json"])
        self.assertEqual(done["status"], "completed")
        self.assertNotIn("mastery", done)

    def test_optimistic_revision_and_noop(self):
        task = self.task()
        updated = self.hub.set_status(task["id"], "working", expected_revision=1)
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(self.hub.set_status(task["id"], "working"), updated)
        with self.assertRaises(ValueError):
            self.hub.set_status(task["id"], "blocked", expected_revision=1)
        self.assertEqual(self.hub.get_task(task["id"]), updated)

    def test_immutable_event_deduplication_and_conflict(self):
        event = self.hub.ingest_event("hermes", "m1", {"text": "消息不是授权"})
        self.assertEqual(event, self.hub.ingest_event("hermes", "m1", {"text": "消息不是授权"}))
        with self.assertRaises(ValueError):
            self.hub.ingest_event("hermes", "m1", {"text": "changed"})
        self.assertIsNone(event["task_id"])
        self.assertEqual(len(self.hub.list_events()), 1)

    def test_explicit_link_is_idempotent_and_cannot_be_reassigned(self):
        one, two = self.task("one"), self.task("two")
        event = self.hub.ingest_event("hermes", "m1", {"text": "后续意见"})
        linked = self.hub.link_event(event["id"], one["id"])
        self.assertEqual(linked, self.hub.link_event(event["id"], one["id"]))
        self.assertEqual(len(self.hub.list_events(one["id"])), 1)
        with self.assertRaises(ValueError):
            self.hub.link_event(event["id"], two["id"])
        self.assertEqual(self.hub.get_task(one["id"])["status"], "queued")

    def test_test_records_are_hidden_and_cannot_link_live_records(self):
        live, test = self.task("live"), self.task("test", test_only=True)
        event = self.hub.ingest_event("fixture", "test", {"test_only": True})
        self.assertEqual(len(self.hub.list_tasks()), 1)
        self.assertEqual(len(self.hub.list_tasks(include_tests=True)), 2)
        self.assertEqual(self.hub.list_events(), [])
        with self.assertRaises(ValueError):
            self.hub.link_event(event["id"], live["id"])
        self.assertEqual(self.hub.link_event(event["id"], test["id"])["task_id"], test["id"])

    def test_direct_ingestion_cannot_cross_test_boundary_or_unknown_task(self):
        live, test = self.task("live"), self.task("test", test_only=True)
        for payload, task_id in (({"test_only": True}, live["id"]),
                                 ({"test_only": False}, test["id"]),
                                 ({"text": "missing"}, "missing")):
            with self.assertRaises(ValueError):
                self.hub.ingest_event("source", "rejected", payload, task_id)
        self.assertEqual(self.hub.list_events(include_tests=True), [])

    def test_restart_preserves_state_and_audit(self):
        task = self.task()
        self.hub.ingest_event("source", "e1", {"v": 1}, task["id"])
        with Hub(self.root) as reopened:
            self.assertEqual(reopened.get_task(task["id"]), task)
            self.assertEqual(len(reopened.list_events(task["id"])), 1)
            self.assertEqual(reopened.connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 2)

    def test_two_connections_reject_stale_revision(self):
        task = self.task()
        with Hub(self.root) as other:
            other.set_status(task["id"], "working", expected_revision=task["revision"])
            with self.assertRaises(ValueError):
                self.hub.set_status(task["id"], "blocked", expected_revision=task["revision"])

    def test_invalid_payload_does_not_leave_partial_event(self):
        for payload in (["list"], {"test_only": "false"}, {"number": float("nan")}):
            with self.assertRaises(ValueError):
                self.hub.ingest_event("source", "bad", payload)
        self.assertEqual(self.hub.list_events(include_tests=True), [])


if __name__ == "__main__":
    unittest.main()
