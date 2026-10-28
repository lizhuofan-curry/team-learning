"""用户运行：官方银行题的四格式预实验，生成与独立评分分开，导入不调用模型。"""

import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


EXPERIMENT = Path(__file__).resolve().parents[1]
SHARED_CODE = EXPERIMENT.parent / "3.1用户记忆评估" / "我的代码"
sys.path.insert(0, str(SHARED_CODE))
import 官方评估工具 as helper

spec = importlib.util.spec_from_file_location("chapter3_record_checks", SHARED_CODE / "07_官方60题批量评估.py")
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
MODES = ("notes", "enhanced_notes", "json_cards", "advanced_json_cards")
RESULTS = EXPERIMENT / "运行结果"
WRITER = SHARED_CODE / "02_官方用例生成记忆与回答.py"
JUDGE = SHARED_CODE / "03_官方用例独立裁判评分.py"
require = checks.require


def configuration():
    # 新批次独立保存配置，四组一致使用原JSON路线；不修改3-1源码或记录。
    return {**checks.configuration(), "memory_format": "json",
            "comparison_script_sha256": helper.sha(__file__)}


def row_config(state, entry):
    return {**state["config"], "mode": entry["mode"]}


def new_state(official, manifest):
    case, source = helper.load_case(helper.DEFAULT_CASE, manifest)
    require(tuple(official.MODES) == MODES, "固定版本的四种模式发生变化")
    return {"stage": "chapter3_four_format_single_case_pilot", "created_at": helper.now().isoformat(),
            "upstream_commit": helper.COMMIT, "config": configuration(),
            "scope": "银行单题四格式预实验；不是60题×四格式完整评估，不与3-1的schema成绩合并",
            "entries": [{"test_id": case["test_id"], "category": case["category"], "mode": mode,
                         "case": case, "source": source, "writer": {"status": "pending"},
                         "judge": {"status": "pending"}} for mode in MODES]}


def inspect(state, entry, stage, path, official):
    config = row_config(state, entry)
    if stage == "judge":
        info = checks.inspect_judge(path, entry, official, config)
        _, record = checks.read_record(path)
        require(record["mode"] == entry["mode"] and record["writer_model"] == config["model"],
                "裁判模式或生成模型不同")
        return info
    info = checks.inspect_writer(path, entry["case"], entry["source"], official, config)
    _, record = checks.read_record(path)
    calls = record["calls"]
    info["observed_request_seconds"] = sum(c.get("elapsed_seconds", 0) for c in calls)
    for name in ("memory", "answer"):
        selected = [c for c in calls if (c["purpose"].startswith("memory_session_") if name == "memory"
                                        else c["purpose"] == "answer")]
        info[name + "_input_tokens"] = sum(c.get("prompt_tokens") or 0 for c in selected)
        info[name + "_output_tokens"] = sum(c.get("completion_tokens") or 0 for c in selected)
    info["last_memory_utf8_bytes"] = (len(json.dumps(record["memory_states"][-1]["memory"],
                                                    ensure_ascii=False).encode("utf-8"))
                                      if record["memory_states"] else None)
    return info


def collect(directory, state, entry, stage, official):
    content = (directory / entry[stage]["log"]).read_text(encoding="utf-8", errors="replace")
    prefix = "记录路径：" if stage == "writer" else "独立评分记录："
    paths = [line.split(prefix, 1)[1].strip() for line in content.splitlines() if line.startswith(prefix)]
    require(paths, "日志没有可核对的原始路径，保留为unresolved，不自动重试")
    return inspect(state, entry, stage, paths[-1], official)


def attach(state, entry, stage, info):
    if stage == "writer" and info.get("model_digest"):
        require(not state.get("model_digest") or state["model_digest"] == info["model_digest"],
                "批次内模型digest变化，停止混用")
        state["model_digest"] = info["model_digest"]
    entry[stage] = info


def summarize(state):
    entries = state["entries"]
    graded = [e["judge"]["result"] for e in entries if e["judge"]["status"] == "scored"]
    finished = all(e["writer"]["status"] in {"saved", "incomplete"} and
                   (e["writer"]["status"] != "saved" or e["judge"]["status"] in {"scored", "incomplete"})
                   for e in entries)
    return {"scope": state["scope"], "planned_cases": 1, "planned_mode_variants": 4,
            "writer_states": dict(Counter(e["writer"]["status"] for e in entries)),
            "judge_states": dict(Counter(e["judge"]["status"] for e in entries)),
            "scored_variants": len(graded), "passed_variants": sum(g["passed"] for g in graded),
            "pilot_all_outcomes_finished": finished, "full_60_case_four_mode_evaluation_completed": False,
            "all_four_variants_scored": len(graded) == 4,
            "writer_calls": sum(e["writer"].get("calls", 0) for e in entries),
            "judge_calls": sum(e["judge"].get("calls", 0) for e in entries),
            "failure_kinds": dict(Counter(e["writer"]["failure_kind"] for e in entries
                                          if e["writer"]["status"] == "incomplete"))}


def save_batch(directory, state):
    helper.dump(directory / "batch.json", state)
    helper.dump(directory / "summary.json", summarize(state))
    lines = ["# 实验3-2：银行单题四格式预实验", "", state["scope"], "",
             "固定qwen3:4b、原JSON输出、推荐采样、seed=37、窗口32768、记忆/答题上限6000/1200。",
             "生成或评分失败无reward，不填0；本表不能确定四种格式的总体优劣。", "",
             "| 模式 | 生成状态 | 评分状态 | 输入token | 输出token | 请求耗时/秒 | passed | reward |",
             "| --- | --- | --- | ---: | ---: | ---: | --- | --- |"]
    for e in state["entries"]:
        w, j = e["writer"], e["judge"]
        g = j.get("result") or {}
        seconds = round(w["observed_request_seconds"], 2) if "observed_request_seconds" in w else "—"
        lines.append(f"| {e['mode']} | {w['status']} | {j['status']} | {w.get('input_tokens', '—')} | "
                     f"{w.get('output_tokens', '—')} | {seconds} | {g.get('passed', '—')} | {g.get('reward', '—')} |")
    lines.extend(["", "token与耗时包含失败请求，来自实际记录；耗时含请求开销，不是纯推理时间。",
                  "生成与评分各自单独留存；未评分的完整回答需后续运行judge。", "", "## 原始记录", ""])
    for e in state["entries"]:
        lines.append(f"- {e['mode']}")
        for stage in ("writer", "judge"):
            item = e[stage]
            if item.get("path"):
                lines.append(f"  - [{stage}原始记录]({Path(item['path']).as_posix()})")
        if e["writer"]["status"] == "saved":
            raw_dir = Path(e["writer"]["path"]).parent
            lines.append(f"  - [模型记忆]({(raw_dir / 'memory.json').as_posix()})；"
                         f"[完整回答]({(raw_dir / 'answer.txt').as_posix()})")
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_state(state, official, manifest):
    require(state["stage"] == "chapter3_four_format_single_case_pilot" and
            state["upstream_commit"] == helper.COMMIT and state["config"] == configuration(),
            "来源、源码或配置变化；不得继续旧批次")
    require([e["mode"] for e in state["entries"]] == list(MODES), "必须保留四组，不能剔除失败组")
    case, source = helper.load_case(helper.DEFAULT_CASE, manifest)
    for entry in state["entries"]:
        require(entry["test_id"] == helper.DEFAULT_CASE and entry["case"] == case and
                entry["source"] == source and entry["category"] == case["category"], "四组用例来源不同")
        for stage in ("writer", "judge"):
            item = entry[stage]
            require(item["status"] in {"pending", "running", "saved", "scored", "incomplete", "unresolved"},
                    "未知状态")
            if "path" in item:
                require(helper.sha(item["path"]) == item["sha256"], "原始记录变化，停止")
                info = inspect(state, entry, stage, item["path"], official)
                require(all(item.get(k) == v for k, v in info.items()), "保存的指标与原始记录不一致")
                attach(state, entry, stage, {**item, **info})
            elif item["status"] in {"saved", "scored", "incomplete"}:
                raise ValueError("已结束状态缺少可核对的原始记录")


def command(stage, entry):
    if stage == "writer":
        return [sys.executable, "-X", "utf8", str(WRITER), "--case", entry["test_id"],
                "--model", "qwen3:4b", "--mode", entry["mode"], "--memory-format", "json",
                "--sampling-profile", "qwen-recommended"]
    return [sys.executable, "-X", "utf8", str(JUDGE), "--record", entry["writer"]["path"],
            "--model", "deepseek-flash"]


def recover(directory, state, official):
    for entry in state["entries"]:
        for stage in ("writer", "judge"):
            if entry[stage]["status"] == "running":
                try:
                    info = collect(directory, state, entry, stage, official)
                    attach(state, entry, stage, {**info, "log": entry[stage]["log"]})
                except (ValueError, KeyError, IndexError, OSError):
                    entry[stage]["status"] = "unresolved"


def run_pending(directory, state, stage, official, limit):
    attempted = 0
    for entry in state["entries"]:
        if entry[stage]["status"] != "pending" or (stage == "judge" and entry["writer"]["status"] != "saved"):
            continue
        if attempted >= limit:
            break
        attempted += 1
        log = f"{entry['mode']}_{stage}.log"
        entry[stage] = {"status": "running", "log": log}
        save_batch(directory, state)
        print(f"{stage} {attempted}：{entry['mode']}……", flush=True)
        interrupted = False
        try:
            with (directory / log).open("x", encoding="utf-8") as stream:
                subprocess.run(command(stage, entry), cwd=helper.PROJECT, stdout=stream,
                               stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False)
        except KeyboardInterrupt:
            interrupted = True
        except OSError:
            pass
        try:
            info = collect(directory, state, entry, stage, official)
            attach(state, entry, stage, {**info, "log": log})
        except (ValueError, KeyError, IndexError, OSError) as error:
            entry[stage] = {"status": "unresolved", "log": log, "error_type": type(error).__name__}
            if "digest" in str(error):
                save_batch(directory, state)
                raise
        save_batch(directory, state)
        print("  状态：", entry[stage]["status"], flush=True)
        if interrupted:
            break


def main():
    helper.configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("writer", "judge", "summary"))
    parser.add_argument("--batch", type=Path, help="恢复、评分或汇总时使用本预实验的既有目录")
    parser.add_argument("--limit", type=int, default=4, help="本次最多处理几组，1至4，默认4")
    parser.add_argument("--preview", action="store_true", help="零网络请求、零子进程，不创建运行目录")
    args = parser.parse_args()
    require(1 <= args.limit <= 4, "limit必须在1至4之间")
    official, manifest = helper.load_official()
    directory = args.batch.resolve() if args.batch else None
    if directory:
        require(directory.is_relative_to(RESULTS.resolve()), "请选择3.2运行结果下的预实验批次")
        state = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
    else:
        require(args.stage == "writer", "judge或summary必须指定已有--batch目录")
        state = new_state(official, manifest)
    validate_state(state, official, manifest)
    pending = [e for e in state["entries"] if args.stage != "summary" and e[args.stage]["status"] == "pending"
               and (args.stage != "judge" or e["writer"]["status"] == "saved")][:args.limit]
    budget = sum(len(e["case"]["conversation_histories"]) + 1 for e in pending) if args.stage == "writer" else len(pending)
    print(f"银行单题×四格式预实验；本次{args.stage}最多处理{len(pending)}组、{budget}次推理请求。")
    if args.stage == "writer":
        print(f"另有最多{len(pending)}次模型列表查询；不请求云端裁判，无自动重试。")
    elif args.stage == "judge":
        print("仅评分完整回答；DeepSeek请求可能计费，无自动重试。")
    if args.preview:
        print("FOUR_FORMAT_PREVIEW_ONLY：来源及计划核验通过，零网络、零子进程，未写入运行记录。")
        print(json.dumps(summarize(state), ensure_ascii=False, indent=2))
        return
    if directory is None:
        directory = RESULTS / ("four_format_pilot_" + helper.now().strftime("%Y%m%d_%H%M%S_%f"))
        directory.mkdir(parents=True, exist_ok=False)
    # 防止同一批次同时运行两个进程，重复产生本机或付费请求。
    lock = directory / ".run.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        # 预读后其他进程可能刚好结束；取得锁后重读，避免使用旧pending状态重复请求。
        if args.batch:
            state = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
            validate_state(state, official, manifest)
        recover(directory, state, official)
        save_batch(directory, state)
        print("预实验目录：", directory, flush=True)
        if args.stage != "summary":
            run_pending(directory, state, args.stage, official, args.limit)
        save_batch(directory, state)
        print("四格式汇总：", directory / "summary.md")
        print(json.dumps(summarize(state), ensure_ascii=False, indent=2))
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
