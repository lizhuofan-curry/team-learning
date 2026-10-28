#!/usr/bin/env python3
"""Private Codex/Hermes file exchange. No models, messages, approvals or Git."""
import argparse
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import learning_flow as flow

ROLES = ("codex", "hermes")
FOLDERS = {"codex": "Codex发出", "hermes": "Hermes发出"}
KINDS = ("status", "request", "correction", "weekly-version")
MAX_BUNDLE = 8_000_000


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def check_time(value):
    if not isinstance(value, str) or dt.datetime.fromisoformat(value).utcoffset() is None:
        raise ValueError("需要带时区的时间")


def peer(role):
    if role not in ROLES:
        raise ValueError("未知Agent角色")
    return ROLES[1 - ROLES.index(role)]


def msg_id(sender, source):
    return flow.digest(flow.canonical([sender, source]))[:24]


def envelope_hash(message):
    return flow.digest(flow.canonical(message))


def validate_message(m):
    required = {"version", "id", "sender", "source_id", "created_at", "kind", "topic", "text", "text_sha256", "supersedes", "test_only"}
    if not isinstance(m, dict) or set(m) != required or m["version"] != 1:
        raise ValueError("协作消息格式错误")
    peer(m["sender"])
    for key, limit in (("source_id", 300), ("topic", 200), ("text", 200000)):
        if not isinstance(m[key], str) or not 0 < len(m[key].encode("utf-8")) <= limit:
            raise ValueError("消息字段长度错误")
    if m["id"] != msg_id(m["sender"], m["source_id"]) or m["text_sha256"] != flow.digest(m["text"].encode("utf-8")):
        raise ValueError("消息编号或内容哈希错误")
    if m["kind"] not in KINDS or not isinstance(m["test_only"], bool):
        raise ValueError("消息类型错误")
    if m["supersedes"] is not None and not re.fullmatch(r"[a-f0-9]{24}", m["supersedes"]):
        raise ValueError("旧消息编号错误")
    check_time(m["created_at"])
    return m


def message_path(root, m):
    validate_message(m)
    return root / "协作消息" / FOLDERS[m["sender"]] / (m["id"] + ".json")


def write_private(path, data):
    existed = path.exists()
    if not existed:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flow.store(path, data)
    if not existed:
        path.chmod(0o600)
    return path


def publish(root, role, source_id, topic, text, kind="status", supersedes=None, test_only=False):
    peer(role)
    m = dict(version=1, id=msg_id(role, source_id), sender=role, source_id=source_id,
             created_at=now(), kind=kind, topic=topic, text=text,
             text_sha256=flow.digest(text.encode("utf-8")), supersedes=supersedes, test_only=test_only)
    p = message_path(root, m)
    if p.exists():
        old = validate_message(flow.read_json(p))
        # Same source retried later retains its original timestamp and bytes.
        if {k:v for k,v in old.items() if k != "created_at"} != {k:v for k,v in m.items() if k != "created_at"}:
            raise ValueError("同来源已有不同内容；修订请用新source-id并关联supersedes")
        return old
    write_private(p, flow.canonical(m) + b"\n")
    return m


def messages(root, sender):
    peer(sender)
    result = []
    for p in sorted((root / "协作消息" / FOLDERS[sender]).glob("*.json")):
        m = validate_message(flow.read_json(p))
        if m["sender"] != sender or p.name != m["id"] + ".json":
            raise ValueError("消息位置不匹配")
        result.append(m)
    return result


def validate_ack(a):
    if not isinstance(a, dict) or set(a) != {"version", "reader", "message_id", "message_sha256", "read_at", "status"} or a["version"] != 1 or a["status"] != "read":
        raise ValueError("读取回执格式错误")
    peer(a["reader"])
    if not re.fullmatch(r"[a-f0-9]{24}", a["message_id"]):
        raise ValueError("消息编号错误")
    flow.valid_hash(a["message_sha256"])
    check_time(a["read_at"])
    return a


def ack_path(root, a):
    validate_ack(a)
    return root / "协作消息/读取回执" / a["reader"] / (a["message_id"] + "-" + a["message_sha256"] + ".json")


def check_ack_message(root, a, incoming=None):
    sender = peer(a["reader"])
    p = root / "协作消息" / FOLDERS[sender] / (a["message_id"] + ".json")
    m = (incoming or {}).get(a["message_id"])
    if m is None:
        m = validate_message(flow.read_json(p))
    if m["sender"] != sender or envelope_hash(m) != a["message_sha256"]:
        raise ValueError("回执未绑定当前消息的精确版本")


def acknowledge(root, role, identifier, sha256):
    a = dict(version=1, reader=role, message_id=identifier, message_sha256=sha256, read_at=now(), status="read")
    validate_ack(a)
    check_ack_message(root, a)
    p = ack_path(root, a)
    if p.exists():
        return validate_ack(flow.read_json(p))
    write_private(p, flow.canonical(a) + b"\n")
    return a


def list_incoming(root, role, unread=False, include_tests=False):
    result = []
    for m in messages(root, peer(role)):
        a = dict(version=1, reader=role, message_id=m["id"], message_sha256=envelope_hash(m), read_at=now(), status="read")
        if (not include_tests and m["test_only"]) or (unread and ack_path(root, a).exists()):
            continue
        result.append(dict(message=m, message_sha256=envelope_hash(m), read=ack_path(root, a).exists()))
    return sorted(result, key=lambda x:(x["message"]["created_at"],x["message"]["id"]))


def export_bundle(root, role):
    # Only this endpoint's own publications and read receipts leave the endpoint.
    acks = []
    for p in sorted((root / "协作消息/读取回执" / role).glob("*.json")):
        a = validate_ack(flow.read_json(p))
        if a["reader"] != role or p != ack_path(root, a):
            raise ValueError("回执位置不匹配")
        check_ack_message(root, a)
        acks.append(a)
    b = dict(version=1, sender=role, messages=messages(root, role), acknowledgements=acks)
    if len(flow.canonical(b)) > MAX_BUNDLE:
        raise ValueError("协作包超过8MB，需分批迁移；未推进同步状态")
    return b


def import_bundle(root, role, bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"version", "sender", "messages", "acknowledgements"} or bundle["version"] != 1 or bundle["sender"] != peer(role):
        raise ValueError("协作包方向错误")
    if len(flow.canonical(bundle)) > MAX_BUNDLE or not isinstance(bundle["messages"], list) or not isinstance(bundle["acknowledgements"], list):
        raise ValueError("协作包大小或集合错误")
    writes = []
    seen = {}
    new_messages = new_acks = 0
    for m in bundle["messages"]:
        validate_message(m)
        if m["sender"] != peer(role):
            raise ValueError("不能从另一端代发本端消息")
        p = message_path(root, m)
        writes.append((p, flow.canonical(m) + b"\n"))
        new_messages += int(not p.exists())
    for a in bundle["acknowledgements"]:
        validate_ack(a)
        if a["reader"] != peer(role):
            raise ValueError("不能导入本端自己的读取声明")
        check_ack_message(root, a)
        p = ack_path(root, a)
        writes.append((p, flow.canonical(a) + b"\n"))
        new_acks += int(not p.exists())
    # Preflight conflicts for the entire bundle before publishing any file.
    for p, raw in writes:
        if (p in seen and seen[p] != raw) or (p.exists() and p.read_bytes() != raw):
            raise ValueError("协作包冲突；已有文件保留")
        seen[p] = raw
    for p, raw in seen.items():
        write_private(p, raw)
    return dict(messages_added=new_messages, acknowledgements_added=new_acks)


def remote_args(root, config, action):
    r = config["remote"]
    host = r["host"]
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]+", host) or host.startswith("-"):
        raise ValueError("SSH别名错误")
    argv = [r.get("python", "python3"), r["script"], "--root", r["root"], action]
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, " ".join(shlex.quote(str(v)) for v in argv)]


def exchange(root, config):
    role = config["role"]
    if config.get("mode") == "local":
        return dict(mode="local", note="同机共用目录；两位Agent各用自己的--role读取并回执")
    response = subprocess.run(remote_args(root, config, "export"), capture_output=True, check=True, timeout=25)
    if len(response.stdout) > MAX_BUNDLE:
        raise ValueError("远程协作包过大")
    pulled = import_bundle(root, role, json.loads(response.stdout))
    payload = flow.canonical(export_bundle(root, role))
    response = subprocess.run(remote_args(root, config, "import"), input=payload, capture_output=True, check=True, timeout=25)
    pushed = json.loads(response.stdout)
    return dict(pulled=pulled, pushed=pushed)


@contextlib.contextmanager
def tick_lock(root):
    p = root / "协作消息/同步状态/tick.lock"
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with p.open("a+b") as stream:
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                if p.stat().st_size == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    pass
            yield acquired
        finally:
            if acquired and os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            elif acquired:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def tick(root, config):
    state_path = root / "协作消息/同步状态/latest.json"
    with tick_lock(root) as locked:
        if not locked:
            return dict(status="busy"), 0
        prior = flow.read_json(state_path) if state_path.exists() else {}
        state = dict(version=1, last_attempt=now(), last_success=prior.get("last_success"), status="running")
        failures = {}
        for step, action in (("learning_inbox", lambda: flow.sync(root, flow.read_json(root / "config.local.json"))),
                             ("collaboration", lambda: exchange(root, config))):
            try:
                state[step] = action()
            except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as error:
                # Do not leak remote stderr, message text, credentials or host details.
                failures[step] = type(error).__name__
        state["status"] = "retry_pending" if failures else "ok"
        state["errors"] = failures
        if not failures:
            state["last_success"] = state["last_attempt"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        flow.replace_state(state_path, state)
        state_path.chmod(0o600)
        return state, 2 if failures else 0


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--role", choices=ROLES, help="同机共用目录时，Agent显式选择自己的角色")
    commands = parser.add_subparsers(dest="action", required=True)
    p = commands.add_parser("publish")
    p.add_argument("--source-id", required=True)
    p.add_argument("--topic", required=True)
    p.add_argument("--kind", choices=KINDS, default="status")
    p.add_argument("--text-file", required=True)
    p.add_argument("--supersedes")
    p.add_argument("--test-only", action="store_true")
    p = commands.add_parser("list")
    p.add_argument("--unread", action="store_true")
    p.add_argument("--include-tests", action="store_true")
    p = commands.add_parser("ack")
    p.add_argument("--id", required=True)
    p.add_argument("--sha256", required=True)
    for name in ("export", "import", "sync", "status"):
        commands.add_parser(name)
    p = commands.add_parser("tick")
    p.add_argument("--quiet", action="store_true", help="调度模式只写状态文件，不输出素材或周期消息")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    config = flow.read_json(root / "collaboration.local.json")
    role = args.role or config["role"]
    config = dict(config, role=role)
    peer(role)
    exit_code = 0
    if args.action == "publish":
        text = sys.stdin.read() if args.text_file == "-" else Path(args.text_file).read_text(encoding="utf-8-sig")
        m = publish(root, role, args.source_id, args.topic, text, args.kind, args.supersedes, args.test_only)
        result = dict(id=m["id"], message_sha256=envelope_hash(m), queued=True)
    elif args.action == "list":
        result = list_incoming(root, role, args.unread, args.include_tests)
    elif args.action == "ack":
        result = acknowledge(root, role, args.id, args.sha256)
    elif args.action == "export":
        result = export_bundle(root, role)
    elif args.action == "import":
        raw = sys.stdin.buffer.read(MAX_BUNDLE + 1)
        if len(raw) > MAX_BUNDLE:
            raise ValueError("协作包过大")
        result = import_bundle(root, role, json.loads(raw))
    elif args.action == "sync":
        result = exchange(root, config)
    elif args.action == "tick":
        result, exit_code = tick(root, config)
    else:
        p = root / "协作消息/同步状态/latest.json"
        result = flow.read_json(p) if p.exists() else dict(status="not_run")
    if not (args.action == "tick" and args.quiet):
        print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(error=type(error).__name__, detail="操作未完成；保留原件，不输出素材或连接错误正文"), ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
