"""Exercise the optional task-index hook through the existing tick entry point."""

import builtins
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT_ROOT = Path(__file__).resolve().parent.parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
SPEC = importlib.util.spec_from_file_location(
    "task_tick_collaboration_under_test", SCRIPT_ROOT / "collaboration_flow.py"
)
collaboration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collaboration)


class TaskTickTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config.local.json").write_text(
            '{"mode":"local"}', encoding="utf-8"
        )
        (self.root / "media.local.json").write_text(
            '{"enabled":true}', encoding="utf-8"
        )
        # A sentinel proves a display/index pass leaves source bytes untouched.
        self.media_file = self.root / "媒体队列" / "任务" / "sentinel.json"
        self.media_file.parent.mkdir(parents=True)
        self.media_file.write_bytes(b'{"state":"blocked","test_only":false}\n')
        self.original_media = self.media_file.read_bytes()
        self.index = Mock(name="sync_sources")
        self.media_discover = Mock(return_value={"enabled": True, "added": 0})
        self.exchange = Mock(return_value={"pulled": {}, "pushed": {}})
        self.inbox_sync = Mock(return_value={"events_seen": 1})
        self.addCleanup(patch.stopall)
        patch.object(collaboration.flow, "sync", self.inbox_sync).start()
        patch.object(collaboration, "exchange", self.exchange).start()
        patch.dict(
            sys.modules,
            {
                "media_queue": SimpleNamespace(discover=self.media_discover),
                "task_center": SimpleNamespace(sync_sources=self.index),
            },
        ).start()
        patch.object(
            collaboration.subprocess,
            "run",
            side_effect=AssertionError("tick test must not launch an external command"),
        ).start()

    def configure(self, enabled):
        (self.root / "task_center.local.json").write_text(
            json.dumps({"enabled": enabled}), encoding="utf-8"
        )

    def run_tick(self, role="codex"):
        state, code = collaboration.tick(self.root, {"role": role, "mode": "local"})
        stored = json.loads(
            (self.root / "协作消息" / "同步状态" / "latest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(stored, state)
        self.inbox_sync.assert_called_once()
        self.exchange.assert_called_once()
        if role == "codex":
            self.media_discover.assert_called_once_with(self.root)
        self.assertEqual(self.media_file.read_bytes(), self.original_media)
        self.assertFalse((self.root / "协作消息" / "读取回执").exists())
        self.assertFalse((self.root / "批准记录").exists())
        return state, code

    def guarded_import(self, error):
        original = builtins.__import__

        def import_module(name, *args, **kwargs):
            if name == "task_center":
                raise error
            return original(name, *args, **kwargs)

        return patch("builtins.__import__", side_effect=import_module)

    def test_missing_configuration_never_imports_index(self):
        with self.guarded_import(AssertionError("unexpected task_center import")):
            state, code = self.run_tick()
        self.assertEqual((state["status"], code), ("ok", 0))
        self.assertNotIn("task_center", state)
        self.index.assert_not_called()

    def test_disabled_configuration_never_imports_index(self):
        self.configure(False)
        with self.guarded_import(AssertionError("unexpected task_center import")):
            state, code = self.run_tick()
        self.assertEqual((state["status"], code), ("ok", 0))
        self.assertNotIn("task_center", state)
        self.index.assert_not_called()

    def test_non_boolean_switch_is_rejected_without_import(self):
        self.configure("false")
        with self.guarded_import(AssertionError("unexpected task_center import")):
            state, code = self.run_tick()
        self.assertEqual(state["errors"], {"task_center": "ValueError"})
        self.assertEqual(code, 2)
        self.index.assert_not_called()

    def test_non_object_config_is_reported_without_breaking_sync(self):
        (self.root / "task_center.local.json").write_text("[]", encoding="utf-8")
        state, code = self.run_tick()
        self.assertEqual(state["errors"], {"task_center": "ValueError"})
        self.assertEqual(code, 2)
        self.assertIn("collaboration", state)
        self.index.assert_not_called()

    def test_enabled_index_keeps_observations_without_transport_failure(self):
        self.configure(True)
        observation = {"code": "media_blocked", "severity": "attention"}
        result = {"tasks": 1, "events": 0, "observations": [observation]}
        self.index.return_value = result
        state, code = self.run_tick()
        self.index.assert_called_once_with(self.root, sync_state=dict(
            version=1, last_attempt=state["last_attempt"], last_success=state["last_attempt"],
            status="ok", errors={}))
        self.assertEqual(state["task_center"], result)
        self.assertEqual(state["errors"], {})
        self.assertEqual((state["status"], code), ("ok", 0))
        self.assertEqual(state["last_success"], state["last_attempt"])

    def assert_index_failure_is_isolated(self, error, expected_name):
        self.configure(True)
        self.index.side_effect = error
        state, code = self.run_tick()
        self.assertEqual(state["errors"], {"task_center": expected_name})
        self.assertEqual((state["status"], code), ("retry_pending", 2))
        self.assertIn("learning_inbox", state)
        self.assertIn("collaboration", state)
        self.assertIn("media_queue", state)
        # Only the exception class is published, not private error text.
        self.assertNotIn("PRIVATE_DIAGNOSTIC", json.dumps(state))
        self.index.assert_called_once_with(self.root, sync_state=dict(
            version=1, last_attempt=state["last_attempt"], last_success=state["last_attempt"],
            status="ok", errors={}))

    def test_index_value_error_does_not_skip_existing_sync(self):
        self.assert_index_failure_is_isolated(
            ValueError("PRIVATE_DIAGNOSTIC"), "ValueError"
        )

    def test_index_database_error_does_not_skip_existing_sync(self):
        self.assert_index_failure_is_isolated(
            sqlite3.OperationalError("PRIVATE_DIAGNOSTIC"), "OperationalError"
        )

    def test_index_import_failure_is_reported_separately(self):
        self.configure(True)
        with self.guarded_import(ModuleNotFoundError("PRIVATE_DIAGNOSTIC")):
            state, code = self.run_tick()
        self.assertEqual(state["errors"], {"task_center": "ModuleNotFoundError"})
        self.assertEqual((state["status"], code), ("retry_pending", 2))
        self.assertIn("learning_inbox", state)
        self.assertIn("collaboration", state)
        self.assertIn("media_queue", state)
        self.assertNotIn("PRIVATE_DIAGNOSTIC", json.dumps(state))
        self.index.assert_not_called()

    def test_hermes_role_does_not_run_mac_index(self):
        self.configure(True)
        with self.guarded_import(AssertionError("unexpected task_center import")):
            state, code = self.run_tick(role="hermes")
        self.assertEqual((state["status"], code), ("ok", 0))
        self.assertNotIn("task_center", state)
        self.index.assert_not_called()
        self.media_discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
