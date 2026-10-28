"""2-9诊断：先检查读工具、提交工具、最短读→提交循环。

由用户执行；不是状态栏对照重跑，原始15个失败结果保持不变。
这里只提供必要的1或2个工具，明确参数类型，检查结构化tool_calls。
正文中声称提交或写出调用JSON均不能当成真实调用。
"""
import copy
import json
import time
from datetime import datetime
from pathlib import Path

from status_tools import SimulatedWorkspace, TOOLS

MODEL = "qwen3:0.6b"
PARAMETERS = {"temperature": 0, "seed": 42, "reasoning_effort": "none", "max_tokens": 512}
SYSTEM = "你是工具助手。用户要求工具动作时，实际调用注册工具；不要只在正文描述动作或写调用JSON。参数content必须是字符串。"
READ = next(t for t in TOOLS if t["function"]["name"] == "read_file")
SUBMIT = next(t for t in TOOLS if t["function"]["name"] == "submit_report")


def apply_calls(message, world, allowed_names):
    events = []
    for call in (message.tool_calls or [])[:4]:
        try:
            arguments = json.loads(call.function.arguments)
        except (ValueError, TypeError):
            arguments = None
        if call.function.name in allowed_names:
            event = world.execute(call.function.name, arguments)
        else:
            event = {"tool": call.function.name, "arguments": arguments, "ok": False,
                     "blocked": True, "payload": {"ok": False, "error_type": "UnregisteredTool"}}
        event["tool_call_id"] = call.id
        events.append(event)
    return events


def request(client, messages, tools, row, checkpoint):
    turn = {"request_messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)}
    row["turns"].append(turn)
    checkpoint()
    started = time.perf_counter()
    response = client.chat.completions.create(model=MODEL, messages=messages,
                                             tools=tools, tool_choice="auto", **PARAMETERS)
    turn["elapsed_seconds"] = time.perf_counter() - started
    turn["response"] = response.model_dump(mode="json")
    checkpoint()
    if not response.choices:
        raise RuntimeError("没有choices。")
    return response.choices[0]


def single_check(client, kind, row, checkpoint):
    world = SimulatedWorkspace("state")
    messages = [{"role": "system", "content": SYSTEM}]
    if kind == "read":
        tools = [READ]
        expected = {"path": "/lab/archive/note.txt"}
        expected_name = "read_file"
        messages.append({"role": "user", "content":
            "现在只执行一次read_file，path为/lab/archive/note.txt。请实际调用工具。"})
    else:
        tools = [SUBMIT]
        prior = world.execute("read_file", {"path": "/lab/archive/note.txt"})
        row["preloaded_read"] = prior
        messages.extend([
            {"role": "user", "content": "请读/lab/archive/note.txt，然后提交它的原文。"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "provided_read", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"/lab/archive/note.txt"}'}}]},
            {"role": "tool", "tool_call_id": "provided_read", "content": json.dumps(prior["payload"], ensure_ascii=False)},
            {"role": "user", "content":
                "上面的工具已经成功读取。现在只调用submit_report，content必须是字符串CURRENT-926，不能传整个对象，也不能仅在正文说已提交。"},
        ])
        expected = {"content": "CURRENT-926"}
        expected_name = "submit_report"
    row["expected_tool"] = expected_name
    row["expected_arguments"] = expected
    choice = request(client, messages, tools, row, checkpoint)
    events = [] if choice.finish_reason == "length" else apply_calls(choice.message, world, {expected_name})
    row["events"] = events
    row["body"] = choice.message.content or ""
    row["finish_reason"] = choice.finish_reason
    row["passed"] = (len(choice.message.tool_calls or []) == 1 and len(events) == 1
        and events[0]["tool"] == expected_name and events[0]["arguments"] == expected and events[0]["ok"])
    row["final_state"] = world.snapshot()
    checkpoint()


def loop_check(client, row, checkpoint):
    world = SimulatedWorkspace("state")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content":
        "请实际执行两步：先用read_file读取/lab/archive/note.txt；再用submit_report提交读取结果中content字段的原文字符串。"
        "两个工具都成功返回后才简短回复。"}]
    tools = [READ, SUBMIT]
    row["events"] = []
    row["status"] = "running"
    for number in range(1, 5):
        choice = request(client, messages, tools, row, checkpoint)
        message = choice.message
        row["body"] = message.content or ""
        if choice.finish_reason == "length":
            row["status"] = "truncated"
            break
        calls = list(message.tool_calls or [])
        if not calls:
            row["status"] = "answered" if choice.finish_reason == "stop" and row["body"].strip() else "empty_or_invalid"
            break
        if len(calls) > 4 or len({c.id for c in calls}) != len(calls):
            row["status"] = "invalid_calls"
            break
        if number == 4:
            row["status"] = "round_budget_reached"
            break
        messages.append({"role": "assistant", "content": row["body"], "tool_calls": [{
            "id": c.id, "type": "function", "function": {"name": c.function.name,
            "arguments": c.function.arguments}} for c in calls]})
        events = apply_calls(message, world, {"read_file", "submit_report"})
        row["events"].extend(events)
        for event in events:
            messages.append({"role": "tool", "tool_call_id": event["tool_call_id"],
                             "content": json.dumps(event["payload"], ensure_ascii=False)})
        row["latest_state"] = world.snapshot()
        checkpoint()
    row["final_state"] = world.snapshot()
    row["passed"] = (row["status"] == "answered" and world.proof("read") and world.proof("submit")
                     and not any(e.get("blocked") or e.get("duplicate_write") for e in row["events"]))
    checkpoint()


def main():
    from openai import OpenAI
    client = OpenAI(base_url="http://127.0.0.1:11434/v1", api_key="ollama", timeout=180, max_retries=0)
    output = Path(__file__).resolve().parents[1] / "诊断结果" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    record = {"stage": "basic_tool_diagnostic", "model": MODEL, "parameters": PARAMETERS,
              "rows": [], "error": None, "scope": "单独简化任务；不作为原15任务的新成绩或状态栏效果证据。"}

    def checkpoint():
        (output / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print("基础工具链检查：单次读取、单次提交、最短读取→提交循环。", flush=True)
    print("不预热；前两项各1次请求，第三项最多4次，共最多6次本机请求。", flush=True)
    checkpoint()
    try:
        for kind, title in (("read", "只调用读取"), ("submit", "只调用提交"), ("loop", "读取后实际提交")):
            print("\n检查：", title, flush=True)
            row = {"kind": kind, "turns": []}
            record["rows"].append(row)
            if kind == "loop":
                loop_check(client, row, checkpoint)
            else:
                single_check(client, kind, row, checkpoint)
            print("判定：", "通过" if row["passed"] else "未通过", flush=True)
            print("正文：", row.get("body") or "（无正文）", flush=True)
            print("实际模拟动作：", [(e["tool"], e["ok"]) for e in row["events"]], flush=True)
    except Exception as exc:
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print("诊断中断：", record["error"], flush=True)
    finally:
        record["model_requests_attempted"] = sum(len(r["turns"]) for r in record["rows"])
        record["complete"] = record["error"] is None and len(record["rows"]) == 3 and all("passed" in r for r in record["rows"])
        checkpoint()
        print("实际请求尝试：", record["model_requests_attempted"], flush=True)
        print("诊断记录：", output / "record.json", flush=True)
    if not record["complete"]:
        raise SystemExit(1)
    print("BASIC_TOOL_DIAGNOSTIC_COMPLETE：三项已测量，通过情况见上方，不改写原实验结果。")


if __name__ == "__main__":
    main()
