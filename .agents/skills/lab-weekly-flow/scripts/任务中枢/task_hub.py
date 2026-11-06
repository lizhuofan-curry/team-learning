#!/usr/bin/env python3
"""Local task records and event links. This module never executes recorded work."""
import contextlib
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3


STATUSES = frozenset({"queued", "working", "waiting", "awaiting_review", "blocked", "completed", "cancelled"})
SCOPES = frozenset({"read_only", "local_prepare"})


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity(source, external_id):
    _text(source, "source", 200)
    _text(external_id, "external_id", 1000)
    return hashlib.sha256(_json([source, external_id]).encode("utf-8")).hexdigest()[:24]


def _text(value, name, limit=10000, allow_empty=False):
    if not isinstance(value, str) or (not value.strip() and not allow_empty) or len(value) > limit:
        raise ValueError("invalid " + name)
    return value


def _now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="microseconds")


def _evidence(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("evidence must be a list of non-empty strings")
    return list(dict.fromkeys(value))


def _state(status, evidence):
    if status not in STATUSES:
        raise ValueError("invalid task status")
    if status == "completed" and not evidence:
        raise ValueError("completed requires evidence; it does not assert personal mastery")


class Hub:
    """One SQLite store under a workflow root. Construct only when initialization is intended."""

    def __init__(self, root):
        self.path = Path(root) / "任务中枢" / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=15000")
        try:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
                    title TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                    evidence TEXT NOT NULL, next_action TEXT NOT NULL, test_only INTEGER NOT NULL,
                    scope TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(source, external_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
                    payload TEXT NOT NULL, task_id TEXT REFERENCES tasks(id),
                    created_at TEXT NOT NULL, test_only INTEGER NOT NULL,
                    UNIQUE(source, external_id)
                );
                CREATE INDEX IF NOT EXISTS events_task_id ON events(task_id);
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL,
                    action TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            self.path.chmod(0o600)
        except BaseException:
            self.connection.close()
            raise

    @contextlib.contextmanager
    def _write(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _audit(self, entity_id, action, data):
        self.connection.execute("INSERT INTO audit(entity_id,action,data,created_at) VALUES(?,?,?,?)",
                                (entity_id, action, _json(data), _now()))

    @staticmethod
    def _task(row):
        if row is None:
            return None
        result = dict(row)
        result["evidence"] = json.loads(result["evidence"])
        result["test_only"] = bool(result["test_only"])
        return result

    @staticmethod
    def _event(row):
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["test_only"] = bool(result["test_only"])
        return result

    def register(self, source, external_id, title, kind, status="queued", evidence=None,
                 next_action="", test_only=False, scope="local_prepare"):
        identifier = _identity(source, external_id)
        _text(title, "title")
        _text(kind, "kind", 100)
        _text(next_action, "next_action", allow_empty=True)
        evidence = _evidence(evidence)
        _state(status, evidence)
        if scope not in SCOPES or not isinstance(test_only, bool):
            raise ValueError("invalid task scope or test_only")
        with self._write():
            old = self.get_task(identifier)
            if old is not None:
                if old["source"] != source or old["external_id"] != external_id:
                    raise ValueError("task identity collision")
                if old["test_only"] != test_only or old["scope"] != scope or old["kind"] != kind:
                    raise ValueError("task classification conflict")
                return old
            stamp = _now()
            self.connection.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (identifier, source, external_id, title, kind, status,
                                     _json(evidence), next_action, int(test_only), scope, 1, stamp, stamp))
            self._audit(identifier, "registered", {"source": source, "external_id": external_id})
            return self.get_task(identifier)

    def get_task(self, task_id):
        return self._task(self.connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def list_tasks(self, include_tests=False):
        query = "SELECT * FROM tasks" + ("" if include_tests else " WHERE test_only=0") + " ORDER BY created_at,id"
        return [self._task(row) for row in self.connection.execute(query)]

    def set_status(self, task_id, status, evidence=None, next_action="", expected_revision=None):
        _text(next_action, "next_action", allow_empty=True)
        with self._write():
            old = self.get_task(task_id)
            if old is None:
                raise ValueError("unknown task")
            if expected_revision is not None and (type(expected_revision) is not int or old["revision"] != expected_revision):
                raise ValueError("task revision conflict")
            records = old["evidence"] if evidence is None else _evidence(evidence)
            _state(status, records)
            if (status, records, next_action) == (old["status"], old["evidence"], old["next_action"]):
                return old
            self.connection.execute("UPDATE tasks SET status=?,evidence=?,next_action=?,revision=revision+1,updated_at=? WHERE id=?",
                                    (status, _json(records), next_action, _now(), task_id))
            self._audit(task_id, "status_changed", {"from": old["status"], "to": status,
                                                   "revision": old["revision"] + 1, "evidence": records,
                                                   "next_action": next_action})
            return self.get_task(task_id)

    def _validate_link(self, task_id, test_only):
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("unknown task")
        if task["test_only"] != test_only:
            raise ValueError("test and live records cannot be linked")

    def ingest_event(self, source, external_id, payload, task_id=None):
        identifier = _identity(source, external_id)
        if not isinstance(payload, dict) or not isinstance(payload.get("test_only", False), bool):
            raise ValueError("event payload must be a JSON object with a boolean test_only")
        encoded = _json(payload)
        test_only = payload.get("test_only", False)
        with self._write():
            old = self._event(self.connection.execute("SELECT * FROM events WHERE id=?", (identifier,)).fetchone())
            if old is not None:
                if old["source"] != source or old["external_id"] != external_id or _json(old["payload"]) != encoded:
                    raise ValueError("immutable event conflict")
                if task_id is not None and old["task_id"] != task_id:
                    raise ValueError("event association differs; use link_event for an unlinked event")
                return old
            if task_id is not None:
                self._validate_link(task_id, test_only)
            self.connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                                    (identifier, source, external_id, encoded, task_id, _now(), int(test_only)))
            self._audit(identifier, "event_ingested", {"task_id": task_id})
            return self._event(self.connection.execute("SELECT * FROM events WHERE id=?", (identifier,)).fetchone())

    def list_events(self, task_id=None, include_tests=False):
        clauses, args = [], []
        if task_id is not None:
            clauses.append("task_id=?")
            args.append(task_id)
        if not include_tests:
            clauses.append("test_only=0")
        query = "SELECT * FROM events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at,id"
        return [self._event(row) for row in self.connection.execute(query, args)]

    def link_event(self, event_id, task_id):
        with self._write():
            event = self._event(self.connection.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone())
            if event is None:
                raise ValueError("unknown event")
            self._validate_link(task_id, event["test_only"])
            if event["task_id"] == task_id:
                return event
            if event["task_id"] is not None:
                raise ValueError("event is already linked to another task")
            self.connection.execute("UPDATE events SET task_id=? WHERE id=?", (task_id, event_id))
            self._audit(event_id, "event_linked", {"task_id": task_id})
            return self._event(self.connection.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone())

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
