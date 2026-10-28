"""用户运行：固定4B配置批量生成、另行评分；失败留存，断点恢复不自动重试。"""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

import 官方评估工具 as helper


CODE = Path(__file__).resolve().parent
RESULTS = helper.EXPERIMENT / "运行结果"
WRITER = CODE / "02_官方用例生成记忆与回答.py"
JUDGE = CODE / "03_官方用例独立裁判评分.py"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def configuration():
    return {"model": "qwen3:4b", "mode": "notes", "memory_format": "schema",
            "sampling_profile": "qwen-recommended", "judge_model": "deepseek-flash",
            "num_ctx": helper.NUM_CTX, "memory_max": helper.MEMORY_MAX,
            "answer_max": helper.ANSWER_MAX, "seed": helper.SEED,
            "sampling_options": helper.sampling_options("qwen-recommended"),
            "writer_script_sha256": helper.sha(WRITER), "judge_script_sha256": helper.sha(JUDGE),
            "helper_sha256": helper.sha(Path(helper.__file__)),
            "batch_script_sha256": helper.sha(__file__)}


def read_record(path):
    path = Path(path).resolve()
    require(path.name == "record.json" and path.is_relative_to(RESULTS.resolve()), "记录必须位于本实验运行结果目录")
    return path, json.loads(path.read_text(encoding="utf-8"))


def inspect_writer(path, case, source, official, config):
    path, record = read_record(path)
    require(record.get("stage") == "official_case_local_memory_and_answer", "并非02生成记录")
    require(record.get("upstream_commit") == helper.COMMIT and record.get("case_source") == source
            and record.get("test_id") == case["test_id"], "生成记录来源不匹配")
    require(all(record.get(k) == config[k] for k in ("model", "mode", "memory_format", "sampling_profile")),
            "生成记录与批次配置不同")
    require(record.get("status") in {"memory_and_answer_saved", "incomplete"}, "生成记录仍未结束")
    histories, calls, states = case["conversation_histories"], record["calls"], record["memory_states"]
    require(len(calls) <= len(histories) + 1, "生成调用数异常")
    memory, state_count = official.initial_memory(config["mode"]), 0
    for index, call in enumerate(calls):
        is_memory = index < len(histories)
        messages = (helper.memory_messages(official, config["mode"], memory, histories[index],
                                           index + 1, config["memory_format"]) if is_memory else
                    official.answer_prompt(config["mode"], memory, case["user_question"]))
        expected = helper.local_payload(messages, config["memory_max"] if is_memory else config["answer_max"],
                                        is_memory, config["memory_format"], config["sampling_profile"], config["model"])
        require(call["request"] == expected, "生成请求或材料隔离不匹配")
        require(call["purpose"] == (f"memory_session_{index + 1}" if is_memory else "answer"), "请求顺序异常")
        if "raw_response" in call:
            require(helper.strict_json(call["raw_http_body"]) == call["raw_response"], "原始HTTP正文不一致")
        if not call.get("ok"):
            require(record["status"] == "incomplete" and index == len(calls) - 1, "失败后不应继续请求")
            break
        content = helper.verified_content(call)
        if is_memory:
            try:
                memory = helper.validate_memory(content, config["mode"])
            except ValueError:
                require(record["status"] == "incomplete" and index == len(calls) - 1, "格式失败后不应继续")
                break
            state = states[state_count]
            require(state["memory"] == memory and state["session_index"] == index + 1
                    and state["conversation_id"] == histories[index]["conversation_id"]
                    and state["prior_raw_histories_supplied"] == 0, "记忆检查点不一致")
            state_count += 1
    require(len(states) == state_count, "记忆检查点数量异常")
    saved = record["status"] == "memory_and_answer_saved"
    if saved:
        memory, answer = helper.verify_writer_record(record, official, case, source)
        require(set(record["artifacts"]) == {"memory.json", "answer.txt"}, "产物不完整")
        for name, digest in record["artifacts"].items():
            require(helper.sha(path.parent / name) == digest, "产物哈希变化")
        require(json.loads((path.parent / "memory.json").read_text(encoding="utf-8")) ==
                {"mode": config["mode"], "memory": memory}, "记忆产物不一致")
        require((path.parent / "answer.txt").read_text(encoding="utf-8") == answer, "回答产物不一致")
    failure_kind = None if saved else ("truncated" if calls and calls[-1].get("done_reason") == "length" else "generation_error")
    return {"status": "saved" if saved else "incomplete", "path": str(path), "sha256": helper.sha(path),
            "calls": len(calls), "input_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
            "output_tokens": sum(c.get("completion_tokens") or 0 for c in calls),
            "model_digest": record.get("model_metadata", {}).get("digest"), "error": record.get("error"),
            "failure_kind": failure_kind}


def inspect_judge(path, entry, official, config):
    path, record = read_record(path)
    require(record.get("stage") == "official_case_independent_judge", "并非03裁判记录")
    writer_path, writer_record = read_record(entry["writer"]["path"])
    require(helper.sha(writer_path) == entry["writer"]["sha256"], "生成记录哈希变化")
    require(record.get("upstream_commit") == helper.COMMIT and record.get("test_id") == entry["test_id"]
            and Path(record["writer_record"]).resolve() == writer_path
            and record["writer_record_sha256"] == helper.sha(writer_path), "裁判关联来源不匹配")
    require(record.get("judge_model") == config["judge_model"] and record.get("judge_provider") == "deepseek"
            and record.get("judge_endpoint") in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}, "裁判配置不同")
    expected = {"model": config["judge_model"], "messages": official.judge_prompt(entry["case"], writer_record["answer"]),
                "temperature": 0, "max_tokens": 4096, "response_format": {"type": "json_object"},
                "stream": False, "extra_body": {"thinking": {"type": "disabled"}}}
    require(record["request"] == expected and record.get("request_attempts") in (0, 1), "裁判请求异常")
    require(record["status"] in {"single_case_scored", "incomplete"}, "裁判记录尚未结束")
    result = None
    if record["status"] == "single_case_scored":
        choices = record["raw_response"]["choices"]
        require(len(choices) == 1 and choices[0]["finish_reason"] == "stop", "裁判响应不完整")
        raw = helper.validate_judge(choices[0]["message"]["content"])
        result = official.judge_summary(raw)
        require(raw == record["judge_raw"] and result == record["judge_summary"], "裁判评分重算不一致")
    return {"status": "scored" if result else "incomplete", "path": str(path), "sha256": helper.sha(path),
            "calls": record["request_attempts"], "result": result}


def attach(state, entry, stage, info, imported=False):
    if stage == "writer" and info.get("model_digest"):
        digest = state.get("model_digest")
        require(not digest or digest == info["model_digest"], "批次内模型digest发生变化；停止混用")
        state["model_digest"] = info["model_digest"]
    entry[stage] = {**info, "imported": imported}


def summarize(state):
    rows = state["entries"]
    wc = Counter(e["writer"]["status"] for e in rows)
    jc = Counter(e["judge"]["status"] for e in rows)
    scores = [e["judge"]["result"] for e in rows if e["judge"]["status"] == "scored"]
    finished = all(e["writer"]["status"] in {"saved", "incomplete"} and
                   (e["writer"]["status"] != "saved" or e["judge"]["status"] in {"scored", "incomplete"}) for e in rows)
    passed = sum(s["passed"] for s in scores)
    layers = {}
    for layer in sorted({e["category"] for e in rows}):
        subset = [e for e in rows if e["category"] == layer]
        graded = [e["judge"]["result"] for e in subset if e["judge"]["status"] == "scored"]
        layers[layer] = {"planned": len(subset), "writer_saved": sum(e["writer"]["status"] == "saved" for e in subset),
                         "generation_failures": sum(e["writer"]["status"] == "incomplete" for e in subset),
                         "scored": len(graded), "passed": sum(s["passed"] for s in graded),
                         "mean_reward_scored_cases_only": sum(s["reward"] for s in graded) / len(graded) if graded else None}
    return {"planned_cases": len(rows), "writer_states": dict(wc), "judge_states": dict(jc),
            "scored_cases": len(scores), "passed_cases": passed,
            "unscored_cases": len(rows) - len(scores), "all_case_attempts_and_outcomes_finished": finished,
            "full_60_judge_scores_available": len(rows) == 60 and len(scores) == 60,
            "pipeline_pass_rate_over_all_cases": passed / len(rows) if finished else None,
            "pass_rate_scored_cases_only": passed / len(scores) if scores else None,
            "mean_reward_scored_cases_only": sum(s["reward"] for s in scores) / len(scores) if scores else None,
            "writer_calls_including_imported": sum(e["writer"].get("calls", 0) for e in rows),
            "new_writer_calls": sum(e["writer"].get("calls", 0) for e in rows if not e["writer"].get("imported")),
            "judge_calls_including_imported": sum(e["judge"].get("calls", 0) for e in rows),
            "generation_failure_kinds": dict(Counter(e["writer"].get("failure_kind", "unknown") for e in rows
                                                      if e["writer"]["status"] == "incomplete")),
            "by_layer": layers,
            "note": "生成或评分失败单列，无裁判分数不填0；已评分均分不代表60题均分。"}


def save_batch(directory, state):
    helper.dump(directory / "batch.json", state)
    report = summarize(state)
    helper.dump(directory / "summary.json", report)
    lines = ["# 官方60题批量评估进度", "", f"配置：{state['config']['model']} / schema / qwen-recommended / notes。",
             "", f"已评分{report['scored_cases']}/60，已通过{report['passed_cases']}题，未评分{report['unscored_cases']}题。",
             "", report["note"], "", f"仅已评分用例的平均reward：{report['mean_reward_scored_cases_only']}。",
             "", "| 层次 | 计划 | 生成完成 | 生成失败 | 已评分 | 通过 | 已评分均分 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for layer, info in report["by_layer"].items():
        lines.append(f"| {layer} | {info['planned']} | {info['writer_saved']} | {info['generation_failures']} | "
                     f"{info['scored']} | {info['passed']} | {info['mean_reward_scored_cases_only']} |")
    lines.extend(["", "| 用例 | 生成 | 裁判 | passed | reward |", "| --- | --- | --- | --- | --- |"])
    for entry in state["entries"]:
        result = entry["judge"].get("result") or {}
        lines.append(f"| {entry['test_id']} | {entry['writer']['status']} | {entry['judge']['status']} | "
                     f"{result.get('passed', '—')} | {result.get('reward', '—')} |")
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def command(stage, entry):
    if stage == "writer":
        return [sys.executable, "-X", "utf8", str(WRITER), "--case", entry["test_id"],
                "--model", "qwen3:4b", "--memory-format", "schema", "--sampling-profile", "qwen-recommended"]
    return [sys.executable, "-X", "utf8", str(JUDGE), "--record", entry["writer"]["path"], "--model", "deepseek-flash"]


def reusable_records(config):
    """每题固定选最早的同配置已结束记录，失败也保留，不挑选最高分。"""
    writers = {}
    for path in sorted(RESULTS.glob("official_writer_*/record.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if (record.get("status") in {"memory_and_answer_saved", "incomplete"}
                and all(record.get(k) == config[k] for k in ("model", "mode", "memory_format", "sampling_profile"))):
            writers.setdefault(record["test_id"], path)
    hashes = {helper.sha(p) for p in writers.values()}
    judges = {}
    for path in sorted(RESULTS.glob("official_judge_*/record.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if (record.get("status") in {"single_case_scored", "incomplete"}
                and record.get("writer_record_sha256") in hashes and record.get("judge_model") == config["judge_model"]):
            judges.setdefault(record["test_id"], path)
    return [*writers.values(), *judges.values()]


def collect_log(directory, entry, stage, official, config):
    text = (directory / entry[stage]["log"]).read_text(encoding="utf-8", errors="replace")
    prefix = "记录路径：" if stage == "writer" else "独立评分记录："
    paths = [line.split(prefix, 1)[1].strip() for line in text.splitlines() if line.startswith(prefix)]
    require(paths, "子进程未留下可核对的record.json路径；保留日志，不自动重试")
    return (inspect_writer(paths[-1], entry["case"], entry["source"], official, config) if stage == "writer" else
            inspect_judge(paths[-1], entry, official, config))


def run_pending(directory, state, stage, official, limit):
    count = 0
    for entry in state["entries"]:
        if entry[stage]["status"] != "pending" or (stage == "judge" and entry["writer"]["status"] != "saved"):
            continue
        if count >= limit:
            break
        count += 1
        log = f"{entry['test_id']}_{stage}.log"
        entry[stage] = {"status": "running", "log": log}
        save_batch(directory, state)
        print(f"{stage} {count}/{limit}：{entry['test_id']}……", flush=True)
        interrupted = False
        try:
            with (directory / log).open("x", encoding="utf-8") as stream:
                subprocess.run(command(stage, entry), cwd=helper.PROJECT, stdout=stream, stderr=subprocess.STDOUT,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False)
        except KeyboardInterrupt:
            interrupted = True
        except OSError:
            pass
        try:
            info = collect_log(directory, entry, stage, official, state["config"])
            attach(state, entry, stage, {**info, "log": log})
        except (ValueError, KeyError, IndexError, OSError) as error:
            entry[stage] = {"status": "unresolved", "log": log, "error_type": type(error).__name__}
            save_batch(directory, state)
            if "digest" in str(error):
                raise
        save_batch(directory, state)
        print(f"  {entry[stage]['status']}；记录已保留", flush=True)
        if interrupted:
            print("已停止；恢复时只处理未尝试的题，不重试本题。")
            break


def main():
    helper.configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("writer", "judge", "summary"))
    parser.add_argument("--batch", type=Path, help="已有批次目录，用于恢复、评分或汇总")
    parser.add_argument("--import-record", type=Path, action="append", default=[], help="新批次复用同配置原记录，可重复指定")
    parser.add_argument("--reuse-existing", action="store_true", help="新批次复用每题最早的同配置记录，包含失败，不挑选成功")
    parser.add_argument("--limit", type=int, default=60, help="本次最多尝试多少道未处理用例，默认60")
    parser.add_argument("--preview", action="store_true", help="仅检查计划与来源；零网络请求、不创建目录")
    args = parser.parse_args()
    require(1 <= args.limit <= 60, "limit必须在1至60之间")
    official, manifest = helper.load_official()
    index = json.loads((helper.SOURCES / "用例清单.json").read_text(encoding="utf-8"))
    cases = index["cases"]
    require(len(cases) == 60 and Counter(c["category"] for c in cases) == {"layer1": 20, "layer2": 20, "layer3": 20},
            "必须使用固定官方三层各20题")
    config = configuration()
    directory = args.batch.resolve() if args.batch else None
    if directory:
        require(directory.is_relative_to(RESULTS.resolve()), "批次须位于本实验运行结果目录")
        require(not args.import_record and not args.reuse_existing, "已有批次不能追加或替换原结果")
        state = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        require(state["upstream_commit"] == helper.COMMIT and state["config"] == config, "源码或配置变化；请另建批次")
        require([e["test_id"] for e in state["entries"]] == [c["test_id"] for c in cases], "批次用例集合不一致")
    else:
        require(args.stage == "writer", "评分和汇总必须指定已有--batch目录")
        entries = []
        for item in cases:
            case, source = helper.load_case(item["test_id"], manifest)
            entries.append({"test_id": case["test_id"], "category": case["category"], "case": case, "source": source,
                            "writer": {"status": "pending"}, "judge": {"status": "pending"}})
        state = {"created_at": helper.now().isoformat(), "upstream_commit": helper.COMMIT, "config": config, "entries": entries}
        import_paths = args.import_record + (reusable_records(config) if args.reuse_existing else [])
        imports = [read_record(p) for p in import_paths]
        for path, record in sorted(imports, key=lambda x: x[1]["stage"] == "official_case_independent_judge"):
            entry = next(e for e in entries if e["test_id"] == record["test_id"])
            stage = "judge" if record["stage"] == "official_case_independent_judge" else "writer"
            require(entry[stage]["status"] == "pending", "同一用例同一阶段不能导入多份记录或挑选结果")
            if stage == "judge":
                require(entry["writer"]["status"] == "saved", "须先导入对应完整生成记录")
                info = inspect_judge(path, entry, official, config)
            else:
                info = inspect_writer(path, entry["case"], entry["source"], official, config)
            attach(state, entry, stage, info, imported=True)
    for entry in state["entries"]:
        case, source = helper.load_case(entry["test_id"], manifest)
        require(entry["case"] == case and entry["source"] == source, "批次材料与固定原件不同")
        for stage in ("writer", "judge"):
            item = entry[stage]
            if "path" in item:
                require(helper.sha(item["path"]) == item["sha256"], "已保存原记录发生变化")
                info = (inspect_writer(item["path"], case, source, official, config) if stage == "writer" else
                        inspect_judge(item["path"], entry, official, config))
                require(item["status"] == info["status"], "批次状态与原记录不一致")
                attach(state, entry, stage, {**item, **info}, imported=item.get("imported", False))
            elif item["status"] == "running" and not args.preview:
                try:
                    info = collect_log(directory, entry, stage, official, config)
                    attach(state, entry, stage, {**item, **info})
                except (ValueError, KeyError, IndexError, OSError):
                    entry[stage] = {**item, "status": "unresolved"}
    pending = [e for e in state["entries"] if e[args.stage]["status"] == "pending"] if args.stage != "summary" else []
    if args.stage == "judge":
        pending = [e for e in pending if e["writer"]["status"] == "saved"]
    selected = pending[:args.limit]
    budget = sum(len(e["case"]["conversation_histories"]) + 1 for e in selected) if args.stage == "writer" else len(selected)
    print(f"固定60题；本次{args.stage}最多处理{len(selected)}题、最多{budget}次推理请求。")
    if args.stage == "writer":
        print(f"另有最多{len(selected)}次模型列表查询；无自动重试，不调用云端裁判。")
    elif args.stage == "judge":
        print("DeepSeek请求可能计费；仅评分完整回答，无自动重试。")
    if args.preview:
        print("BATCH_PREVIEW_ONLY：来源及计划已核验，零网络请求，未创建批次。")
        print(json.dumps(summarize(state), ensure_ascii=False, indent=2))
        return
    if directory is None:
        directory = RESULTS / ("official_batch_" + helper.now().strftime("%Y%m%d_%H%M%S_%f"))
        directory.mkdir(parents=True, exist_ok=False)
    save_batch(directory, state)
    print("批次目录：", directory, flush=True)
    if args.stage != "summary":
        run_pending(directory, state, args.stage, official, args.limit)
    save_batch(directory, state)
    print("批次汇总：", directory / "summary.md")
    print(json.dumps(summarize(state), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
