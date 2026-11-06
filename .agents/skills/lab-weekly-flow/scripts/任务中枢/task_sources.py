#!/usr/bin/env python3
"""Read existing workflow records without advancing queues or creating receipts.

The returned tasks are projections, not another executor or an authorization
source. In particular, media delivery only means that a packet was delivered.
"""
import datetime as dt
import json
import math
from pathlib import Path
import stat
import sys
from urllib.parse import urlsplit

# Reuse the installed workflow's identity/format checks; these modules perform
# no IO at import time. The adapters deliberately never call queue mutators.
_WORKFLOW = str(Path(__file__).resolve().parent.parent)
if _WORKFLOW not in sys.path:
    sys.path.insert(0, _WORKFLOW)
import collaboration_flow as collaboration
import media_queue as media


TIMEZONE = dt.timezone(dt.timedelta(hours=8))
STALE_SECONDS = 15 * 60
STATE_MAP = {
    "pending": "queued", "retry_wait": "queued", "processing": "working",
    "delivery_pending": "waiting", "delivered": "awaiting_review",
    "blocked": "blocked", "cancelled": "cancelled",
}
NEXT_ACTION = {
    "pending": "由现有媒体执行任务认领；任务中枢不执行读取。",
    "retry_wait": "等待原媒体队列的重试时机；不另开重复任务。",
    "processing": "核对现有执行记录，等待媒体处理结果。",
    "delivery_pending": "核对原队列的待回传包和回执，再由原流程重试传输。",
    "delivered": "结果已送达，待读取/核对；不要求逐条本人批准，送达不代表本人学习完成。",
    "blocked": "核对原记录中的受阻原因，决定是否由原队列重试。",
    "cancelled": "保持取消状态；需要恢复时明确提出。",
}


def _time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


def _read(root, path):
    # Reading a malformed or unexpectedly large record should not prevent other
    # independent records from appearing in the snapshot.
    try:
        resolved = path.resolve()
    except RuntimeError as error:
        raise ValueError("unresolvable record path") from error
    if path.is_symlink() or not resolved.is_relative_to(root):
        raise ValueError("record outside workflow or symbolic link")
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
        raise ValueError("unsupported record")
    try:
        result = json.loads(resolved.read_text(encoding="utf-8"))
    except RecursionError as error:
        raise ValueError("record nesting too deep") from error
    if not isinstance(result, dict):
        raise ValueError("object required")
    return result


def _observation(code, source, path, detail, external_id=None, severity="warning"):
    return {"code": code, "severity": severity, "source": source,
            "external_id": external_id, "evidence": str(path), "detail": detail}


def _media_record(root, path):
    record = _read(root, path)
    identifier = record.get("id")
    if (record.get("version") != 1 or not isinstance(identifier, str)
            or not media.JOB.fullmatch(identifier)
            or path.name != identifier + ".json"
            or not isinstance(record.get("url"), str)
            or identifier != media.job_id(record["url"])
            or record.get("state") not in STATE_MAP
            or not isinstance(record.get("test_only"), bool)):
        raise ValueError("invalid media identity or state")
    _time(record.get("created_at"))
    if record["state"] == "processing":
        lease = record.get("lease_until")
        if (isinstance(lease, bool) or not isinstance(lease, (int, float))
                or not math.isfinite(lease)):
            raise ValueError("invalid processing lease")
    return record


def _hermes_record(root, path):
    record = collaboration.validate_message(_read(root, path))
    if record["sender"] != "hermes" or path.name != record["id"] + ".json":
        raise ValueError("invalid Hermes record location")
    return record


def build_snapshot(root, now=None, include_tests=False, sync_state=None):
    """Return ``tasks``, unlinked ``events`` and actionable ``observations``.

    ``now`` accepts an aware datetime for deterministic checks. No function in
    this module writes state, invokes a model, contacts a network or interprets
    a message body as a command. Event payloads hold references and hashes;
    private message bodies remain in their original files.
    """
    root = Path(root).resolve()
    current = now if now is not None else dt.datetime.now(TIMEZONE)
    if not isinstance(current, dt.datetime) or current.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    snapshot = {"tasks": [], "events": [], "observations": []}
    observations = snapshot["observations"]
    for path in sorted((root / "媒体队列" / "任务").glob("*.json")):
        try:
            record = _media_record(root, path)
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            observations.append(_observation(
                "invalid_source_record", "media", path,
                "媒体任务记录无法校验；已跳过本条，原文件保持不变。"))
            continue
        if record["test_only"] and not include_tests:
            continue
        identifier, state = record["id"], record["state"]
        host = urlsplit(record["url"]).hostname or "媒体资源"
        snapshot["tasks"].append({
            "source": "media", "external_id": identifier,
            "title": "媒体资源：" + host + " / " + identifier[:8],
            "kind": "media", "status": STATE_MAP[state],
            "evidence": [str(path)], "next_action": NEXT_ACTION[state],
            "test_only": record["test_only"], "scope": "read_only",
        })
        if state == "processing" and record["lease_until"] <= current.timestamp():
            observations.append(_observation(
                "media_lease_expired", "media", path,
                "现有执行租约已到期，需核对原队列是否回收；本次没有重试或改写状态。",
                identifier))
        if state in ("delivery_pending", "blocked"):
            observations.append(_observation(
                "media_" + state, "media", path, NEXT_ACTION[state], identifier))
        if record.get("content_status") == "partial_ready":
            observations.append(_observation(
                "media_content_partial", "media", path,
                "原记录标注partial_ready：交付内容仍有缺项，使用时需读取原包的覆盖范围。",
                identifier, severity="info"))

    for path in sorted((root / "协作消息" / "Hermes发出").glob("*.json")):
        try:
            record = _hermes_record(root, path)
        except (OSError, ValueError, TypeError, KeyError):
            observations.append(_observation(
                "invalid_source_record", "hermes", path,
                "Hermes协作消息无法校验；已跳过本条，没有生成读取回执。"))
            continue
        if record["test_only"] and not include_tests:
            continue
        snapshot["events"].append({
            "source": "hermes", "external_id": record["id"],
            "payload": {"reference": str(path), "kind": record["kind"],
                        "topic": record["topic"], "text_sha256": record["text_sha256"],
                        "message_sha256": collaboration.envelope_hash(record),
                        "created_at": record["created_at"],
                        "test_only": record["test_only"]},
            "task_ref": None,
        })

    path = root / "协作消息" / "同步状态" / "latest.json"
    if sync_state is None and not path.exists():
        observations.append(_observation(
            "sync_missing", "sync", path, "未找到同步记录，无法判断最近一次传输状态。"))
        return snapshot
    try:
        sync = sync_state if sync_state is not None else _read(root, path)
        if (sync.get("version") != 1 or sync.get("status") not in
                ("ok", "retry_pending", "not_run") or not isinstance(sync.get("errors", {}), dict)):
            raise ValueError("invalid synchronization status")
        last_success = _time(sync["last_success"]) if sync.get("last_success") else None
        last_attempt = _time(sync["last_attempt"]) if sync.get("last_attempt") else None
        if sync["status"] == "ok" and last_success is None:
            raise ValueError("success timestamp missing")
    except (OSError, ValueError, TypeError, KeyError):
        observations.append(_observation(
            "invalid_source_record", "sync", path, "同步记录无法校验，不能据此认定传输正常。"))
        return snapshot
    if sync["status"] != "ok" or sync.get("errors"):
        observations.append(_observation(
            "sync_needs_check", "sync", path,
            "同步记录含未完成或错误状态，请核对原记录；本次没有触发同步。"))
    latest = last_success or last_attempt
    if latest is None:
        observations.append(_observation(
            "sync_unverified", "sync", path, "尚无可核实的同步时间记录。"))
    elif (current - latest).total_seconds() > STALE_SECONDS:
        observations.append(_observation(
            "sync_stale", "sync", path,
            "同步记录已超过15分钟，需核对在线、休眠或调度情况；不能仅据此诊断同步故障。"))
    elif (current - latest).total_seconds() < -60:
        observations.append(_observation(
            "sync_clock_skew", "sync", path, "同步时间晚于当前检查时间，需核对两端时钟。"))
    return snapshot
