"""用户运行：固定60题×四格式、原JSON、4B、6000/4096预算；默认仅处理12组。"""

from collections import Counter
from copy import deepcopy
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

import requests


EXPERIMENT = Path(__file__).resolve().parents[1]
SHARED = EXPERIMENT.parent / "3.1用户记忆评估" / "我的代码"
sys.path.insert(0, str(SHARED))
import 官方评估工具 as helper

spec = importlib.util.spec_from_file_location("campaign_judge_tools", SHARED / "03_官方用例独立裁判评分.py")
judge_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge_tools)
RESULTS = EXPERIMENT / "运行结果"
MODES = ("notes", "enhanced_notes", "json_cards", "advanced_json_cards")
MODEL_DIGEST = "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
MEMORY_MAX, ANSWER_MAX = 6000, 4096


def require(condition, message):
    if not condition:
        raise ValueError(message)


def configuration():
    return {"model": "qwen3:4b", "model_digest": MODEL_DIGEST, "memory_format": "json",
            "sampling_profile": "qwen-recommended", "sampling_options": helper.sampling_options("qwen-recommended"),
            "seed": helper.SEED, "num_ctx": helper.NUM_CTX, "memory_max": MEMORY_MAX, "answer_max": ANSWER_MAX,
            "judge_model": "deepseek-flash", "code_fingerprints":
            {str(p): helper.sha(p) for p in (Path(__file__), Path(helper.__file__), Path(judge_tools.__file__))}}


def load_cases(manifest):
    index = json.loads((helper.SOURCES / "用例清单.json").read_text(encoding="utf-8"))
    require(index["commit"] == helper.COMMIT and len(index["cases"]) == 60
            and Counter(c["category"] for c in index["cases"]) == {"layer1": 20, "layer2": 20, "layer3": 20},
            "固定官方用例须为三层各20题")
    ids = [row["test_id"] for row in index["cases"]]
    first = [next(row["test_id"] for row in index["cases"] if row["category"] == layer)
             for layer in ("layer1", "layer2", "layer3")]
    ordered = first + [test_id for test_id in ids if test_id not in first]
    require(len(set(ordered)) == 60, "用例重复")
    return {test_id: helper.load_case(test_id, manifest) for test_id in ordered}


def new_state(cases):
    return {"stage": "chapter3_four_format_campaign_4096", "created_at": helper.now().isoformat(),
            "upstream_commit": helper.COMMIT, "config": configuration(),
            "scope": "本地固定配置60题×四格式评估；不导入原1200、Schema或冻结记忆诊断成绩",
            "entries": [{"test_id": test_id, "category": case["category"], "mode": mode,
                         "writer": {"status": "pending"}, "judge": {"status": "pending"}}
                        for test_id, (case, _) in cases.items() for mode in MODES]}


def payload(messages, limit, as_json):
    return helper.local_payload(messages, limit, as_json, "json", "qwen-recommended", "qwen3:4b")


def read_record(path, directory):
    path = Path(path).resolve()
    require(path.is_relative_to(directory.resolve()), "原始记录必须位于本批次目录")
    return path, json.loads(path.read_text(encoding="utf-8"))


def inspect_writer(path, entry, directory, official, cases):
    path, record = read_record(path, directory)
    case, source = cases[entry["test_id"]]
    require(record["stage"] == "four_format_writer_4096" and record["config"] == configuration()
            and record["upstream_commit"] == helper.COMMIT and record["case_source"] == source
            and record["test_id"] == entry["test_id"] and record["mode"] == entry["mode"]
            and record["model"] == "qwen3:4b" and record["memory_format"] == "json"
            and record["sampling_profile"] == "qwen-recommended", "生成来源或配置不同")
    require(record["status"] in {"saved", "incomplete"}, "原始生成尚未结束")
    calls, states, histories = record["calls"], record["memory_states"], case["conversation_histories"]
    require(len(calls) <= len(histories) + 1, "调用数超过协议")
    memory, count = official.initial_memory(entry["mode"]), 0
    for i, call in enumerate(calls):
        is_memory = i < len(histories)
        messages = (official.memory_prompt(entry["mode"], memory, histories[i], i + 1) if is_memory else
                    official.answer_prompt(entry["mode"], memory, case["user_question"]))
        require(call["request"] == payload(messages, MEMORY_MAX if is_memory else ANSWER_MAX, is_memory)
                and call["purpose"] == (f"memory_session_{i + 1}" if is_memory else "answer"),
                "请求顺序、预算或材料隔离不一致")
        if "raw_response" in call:
            require(helper.strict_json(call["raw_http_body"]) == call["raw_response"], "HTTP原文与解析响应不同")
        if not call.get("ok"):
            require(record["status"] == "incomplete" and i == len(calls) - 1, "失败后不应继续请求")
            break
        content = helper.verified_content(call)
        if is_memory:
            try:
                new_memory = helper.validate_memory(content, entry["mode"])
            except ValueError:
                require(record["status"] == "incomplete" and i == len(calls) - 1, "格式错误后不应继续")
                break
            state = states[count]
            require(state == {"session_index": i + 1, "conversation_id": histories[i]["conversation_id"],
                              "memory": new_memory, "prior_raw_histories_supplied": 0}, "记忆检查点与响应不同")
            memory, count = new_memory, count + 1
        else:
            require(record.get("answer") == content, "保存回答与原始正文不同")
    require(len(states) == count, "记忆检查点数量不一致")
    digest = record.get("model_metadata", {}).get("digest")
    require(not digest or digest == MODEL_DIGEST, "模型digest不一致")
    saved = record["status"] == "saved"
    if saved:
        require(digest == MODEL_DIGEST and len(calls) == len(histories) + 1 and count == len(histories)
                and set(record["artifacts"]) == {"memory.json", "answer.txt"}, "完整记录缺少调用或产物")
        for name, sha in record["artifacts"].items():
            require(helper.sha(path.parent / name) == sha, "产物哈希变化")
        require(json.loads((path.parent / "memory.json").read_text(encoding="utf-8")) ==
                {"mode": entry["mode"], "memory": memory}
                and (path.parent / "answer.txt").read_text(encoding="utf-8") == record["answer"], "产物正文不同")
    else:
        require(bool(record.get("error")), "失败记录缺少原因")
    info = {"status": "saved" if saved else "incomplete", "path": str(path), "sha256": helper.sha(path),
            "calls": len(calls), "tag_queries": int(record.get("model_preflight", {}).get("attempted", False)),
            "input_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
            "output_tokens": sum(c.get("completion_tokens") or 0 for c in calls),
            "request_seconds": sum(c.get("elapsed_seconds", 0) for c in calls),
            "last_memory_utf8_bytes": len(json.dumps(memory, ensure_ascii=False).encode("utf-8")) if count else None,
            "failure_kind": None if saved else "truncated" if calls and calls[-1].get("done_reason") == "length" else "generation_error",
            "error": record.get("error")}
    for name in ("memory", "answer"):
        group = [c for c in calls if c["purpose"].startswith("memory_session_") == (name == "memory")]
        info[name + "_input_tokens"] = sum(c.get("prompt_tokens") or 0 for c in group)
        info[name + "_output_tokens"] = sum(c.get("completion_tokens") or 0 for c in group)
    return info


def inspect_judge(path, entry, directory, official, cases):
    path, record = read_record(path, directory)
    writer_path, writer = read_record(entry["writer"]["path"], directory)
    require(helper.sha(writer_path) == entry["writer"]["sha256"] and entry["writer"]["status"] == "saved",
            "评分关联的生成记录变化或未完成")
    expected = judge_tools.build_judge_request(official, cases[entry["test_id"]][0], writer["answer"], "deepseek-flash")
    require(record["stage"] == "four_format_judge_4096" and record["config"] == configuration()
            and record["upstream_commit"] == helper.COMMIT and record["test_id"] == entry["test_id"]
            and record["mode"] == entry["mode"] and Path(record["writer_record"]).resolve() == writer_path
            and record["writer_record_sha256"] == helper.sha(writer_path) and record["request"] == expected
            and record["request_attempts"] in {0, 1} and record["judge_model"] == "deepseek-flash"
            and record["judge_provider"] == "deepseek"
            and record["judge_endpoint"] in {"https://api.deepseek.com", "https://api.deepseek.com/v1"},
            "裁判来源、原始回答或请求不同")
    require(record["status"] in {"scored", "incomplete"}, "评分尚未结束")
    result = None
    if record["status"] == "scored":
        choices = record["raw_response"]["choices"]
        require(record["request_attempts"] == 1 and len(choices) == 1 and choices[0]["finish_reason"] == "stop",
                "裁判响应不完整")
        raw = helper.validate_judge(choices[0]["message"]["content"])
        result = official.judge_summary(raw)
        require(raw == record["judge_raw"] and result == record["judge_summary"], "评分重算不同")
    return {"status": record["status"], "path": str(path), "sha256": helper.sha(path),
            "calls": record["request_attempts"], "result": result}


def writer(entry, directory, official, cases):
    case, source = cases[entry["test_id"]]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "writer.json"
    record = {"stage": "four_format_writer_4096", "status": "prepared", "created_at": helper.now().isoformat(),
              "config": configuration(), "upstream_commit": helper.COMMIT, "case_source": source,
              "test_id": entry["test_id"], "mode": entry["mode"], "model": "qwen3:4b",
              "memory_format": "json", "sampling_profile": "qwen-recommended", "calls": [], "memory_states": []}

    def save():
        helper.dump(path, record)

    save()
    try:
        with requests.Session() as session:
            session.trust_env = False
            record["model_preflight"] = {"attempted": True, "endpoint": helper.LOCAL_URL + "/api/tags"}
            save()
            response = session.get(record["model_preflight"]["endpoint"], timeout=(10, 30), allow_redirects=False)
            record["model_preflight"].update(http_status=response.status_code, raw_http_body=response.text)
            save()
            require(response.status_code == 200, "模型列表查询失败")
            models = [m for m in response.json().get("models", []) if m.get("name") == "qwen3:4b"]
            require(len(models) == 1 and models[0].get("digest") == MODEL_DIGEST, "model_digest不匹配；停止混用")
            record.update(model_metadata=models[0], status="running")
            save()
            recorder = helper.LocalRecorder(session, record, save)
            memory = official.initial_memory(entry["mode"])
            for i, history in enumerate(case["conversation_histories"], 1):
                content = recorder.call(official.memory_prompt(entry["mode"], memory, history, i),
                                        f"memory_session_{i}", MEMORY_MAX, as_json=True)
                try:
                    memory = helper.validate_memory(content, entry["mode"])
                except ValueError as error:
                    record["calls"][-1]["memory_validation"] = {"passed": False, "error": str(error)}
                    raise
                record["calls"][-1]["memory_validation"] = {"passed": True}
                record["memory_states"].append({"session_index": i, "conversation_id": history["conversation_id"],
                                                "memory": deepcopy(memory), "prior_raw_histories_supplied": 0})
                save()
            answer = recorder.call(official.answer_prompt(entry["mode"], memory, case["user_question"]), "answer", ANSWER_MAX)
        helper.dump(directory / "memory.json", {"mode": entry["mode"], "memory": memory})
        (directory / "answer.txt").write_text(answer, encoding="utf-8")
        record.update(status="saved", answer=answer,
                      artifacts={name: helper.sha(directory / name) for name in ("memory.json", "answer.txt")})
    except (Exception, KeyboardInterrupt) as error:
        record.update(status="incomplete", error={"type": type(error).__name__, "message": str(error)})
    finally:
        record["finished_at"] = helper.now().isoformat()
        save()
    return path


def judge(entry, directory, official, cases):
    writer_path, source = read_record(entry["writer"]["path"], directory.parents[1])
    request = judge_tools.build_judge_request(official, cases[entry["test_id"]][0], source["answer"], "deepseek-flash")
    config = judge_tools.judge_config(judge_tools.dotenv_values(helper.PROJECT / ".env"), os.environ, "deepseek-flash")
    path = directory / "judge.json"
    record = {"stage": "four_format_judge_4096", "status": "prepared", "created_at": helper.now().isoformat(),
              "config": configuration(), "upstream_commit": helper.COMMIT, "test_id": entry["test_id"],
              "mode": entry["mode"], "writer_record": str(writer_path), "writer_record_sha256": helper.sha(writer_path),
              "request": request, "request_attempts": 0, "judge_model": "deepseek-flash", "judge_provider": "deepseek",
              "judge_endpoint": config["endpoint"]}

    def save():
        helper.dump(path, judge_tools.redact(record, config["api_key"]))

    save()
    try:
        require(bool(config["api_key"]), "缺少已有DEEPSEEK_API_KEY，未发起请求")
        record.update(status="requesting", request_attempts=1)
        save()
        with judge_tools.OpenAI(api_key=config["api_key"], base_url=config["endpoint"], timeout=config["timeout"], max_retries=0) as client:
            response = client.chat.completions.create(**request)
        record["raw_response"] = response.model_dump(mode="json")
        save()
        require(len(response.choices) == 1 and response.choices[0].finish_reason == "stop", "裁判未正常结束")
        raw = helper.validate_judge(response.choices[0].message.content)
        record.update(status="scored", judge_raw=raw, judge_summary=official.judge_summary(raw))
    except (Exception, KeyboardInterrupt) as error:
        record.update(status="incomplete", error={"type": type(error).__name__, "message": str(error)})
    finally:
        record["finished_at"] = helper.now().isoformat()
        save()
    return path


def stats(entries):
    scores = [e["judge"]["result"] for e in entries if e["judge"]["status"] == "scored"]
    finished = all(e["writer"]["status"] in {"saved", "incomplete"} and
                   (e["writer"]["status"] != "saved" or e["judge"]["status"] in {"scored", "incomplete"}) for e in entries)
    passed = sum(s["passed"] for s in scores)
    return {"planned_variants": len(entries), "writer_states": dict(Counter(e["writer"]["status"] for e in entries)),
            "judge_states": dict(Counter(e["judge"]["status"] for e in entries)), "scored_variants": len(scores),
            "passed_variants": passed, "all_attempts_and_outcomes_finished": finished,
            "pipeline_pass_rate_all_variants": passed / len(entries) if finished else None,
            "pass_rate_scored_only": passed / len(scores) if scores else None,
            "mean_reward_scored_only": sum(s["reward"] for s in scores) / len(scores) if scores else None,
            "writer_calls": sum(e["writer"].get("calls", 0) for e in entries),
            "judge_calls": sum(e["judge"].get("calls", 0) for e in entries),
            "generation_failure_kinds": dict(Counter(e["writer"].get("failure_kind") for e in entries
                                                      if e["writer"]["status"] == "incomplete")),
            **{name: sum(e["writer"].get(name, 0) for e in entries)
               for name in ("input_tokens", "output_tokens", "memory_input_tokens", "memory_output_tokens",
                            "answer_input_tokens", "answer_output_tokens", "request_seconds", "tag_queries")}}


def summarize(state):
    rows = state["entries"]
    return {"planned_cases": 60, **stats(rows), "full_240_judge_scores_available":
            sum(e["judge"]["status"] == "scored" for e in rows) == 240,
            "by_mode": {mode: stats([e for e in rows if e["mode"] == mode]) for mode in MODES},
            "by_layer": {layer: stats([e for e in rows if e["category"] == layer])
                         for layer in ("layer1", "layer2", "layer3")},
            "note": "技术失败无裁判分数，不填0；已评分均分与通过率只对应已评分子集。"}


def save_batch(directory, state):
    helper.dump(directory / "batch.json", state)
    report = summarize(state)
    helper.dump(directory / "summary.json", report)
    lines = ["# 实验3-2：固定配置四格式评估", "", state["scope"], "",
             "qwen3:4b，四组原JSON，推荐采样，seed=37，窗口32768，记忆/答题上限6000/4096。", "",
             f"计划60题×四模式=240组；已评分{report['scored_variants']}组，通过{report['passed_variants']}组。",
             "技术失败单列，无分数不填0；模式排名需检查相同用例上的评分覆盖。", "",
             "| 模式 | 计划 | 生成完整 | 生成失败 | 已评分 | 通过 | 仅已评分均分 | 输入token | 输出token | 请求秒数 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |"]
    for mode, value in report["by_mode"].items():
        lines.append(f"| {mode} | 60 | {value['writer_states'].get('saved', 0)} | "
                     f"{value['writer_states'].get('incomplete', 0)} | {value['scored_variants']} | "
                     f"{value['passed_variants']} | {value['mean_reward_scored_only']} | {value['input_tokens']} | "
                     f"{value['output_tokens']} | {value['request_seconds']:.2f} |")
    lines.extend(["", "| 用例 | 模式 | 生成 | 评分 | passed | reward |", "| --- | --- | --- | --- | --- | --- |"])
    for e in state["entries"]:
        score = e["judge"].get("result") or {}
        lines.append(f"| {e['test_id']} | {e['mode']} | {e['writer']['status']} | {e['judge']['status']} | "
                     f"{score.get('passed', '—')} | {score.get('reward', '—')} |")
    lines.extend(["", "原始记录位于本批次的用例/模式目录；token含失败请求，请求耗时含网络与加载开销，不是稳定速度排名。"])
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_state(state, directory, official, cases, recover=False):
    expected = new_state(cases)
    require(state["stage"] == expected["stage"] and state["upstream_commit"] == helper.COMMIT
            and state["config"] == configuration(), "来源或源码配置发生变化，请另建协议批次")
    keys = lambda rows: [(e["test_id"], e["category"], e["mode"]) for e in rows]
    require(keys(state["entries"]) == keys(expected["entries"]), "必须保留完整240组及固定顺序")
    for entry in state["entries"]:
        for stage, inspect_fn in (("writer", inspect_writer), ("judge", inspect_judge)):
            item = entry[stage]
            if "sha256" in item:
                require(helper.sha(item["path"]) == item["sha256"], "原始记录已变化")
                info = inspect_fn(item["path"], entry, directory, official, cases)
                require(all(item.get(k) == v for k, v in info.items()), "汇总指标与原始记录不一致")
            elif item["status"] == "running" and recover:
                try:
                    entry[stage] = inspect_fn(item["path"], entry, directory, official, cases)
                except (ValueError, KeyError, IndexError, OSError):
                    entry[stage] = {**item, "status": "unresolved"}
            else:
                require(item["status"] in {"pending", "running", "unresolved"}, "状态缺少原始证据")


def run_pending(directory, state, stage, official, cases, limit):
    attempted = 0
    for entry in state["entries"]:
        if entry[stage]["status"] != "pending" or (stage == "judge" and entry["writer"]["status"] != "saved"):
            continue
        if attempted >= limit:
            break
        attempted += 1
        group_dir = directory / entry["test_id"] / entry["mode"]
        entry[stage] = {"status": "running", "path": str(group_dir / ("writer.json" if stage == "writer" else "judge.json"))}
        save_batch(directory, state)
        print(f"{stage} {attempted}/{limit}：{entry['test_id']} / {entry['mode']}……", flush=True)
        interrupted = False
        try:
            path = (writer if stage == "writer" else judge)(entry, group_dir, official, cases)
            info = (inspect_writer if stage == "writer" else inspect_judge)(path, entry, directory, official, cases)
            entry[stage] = info
            _, raw = read_record(path, directory)
            interrupted = raw.get("error", {}).get("type") == "KeyboardInterrupt"
            if "model_digest" in raw.get("error", {}).get("message", ""):
                interrupted = True
        except (ValueError, KeyError, IndexError, OSError) as error:
            entry[stage] = {**entry[stage], "status": "unresolved", "error_type": type(error).__name__}
            # 证据核验失败需先检查，不继续消耗后续请求。
            interrupted = True
        save_batch(directory, state)
        print("  状态：", entry[stage]["status"], flush=True)
        if interrupted:
            break


def main():
    helper.configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("writer", "judge", "summary"))
    parser.add_argument("--batch", type=Path, help="恢复、评分、汇总须使用同一批次目录")
    parser.add_argument("--limit", type=int, default=12, help="本次最多处理多少组合，默认12，范围1至240")
    parser.add_argument("--preview", action="store_true", help="仅核对来源与计划，零网络、零运行目录")
    args = parser.parse_args()
    require(1 <= args.limit <= 240, "limit必须在1至240之间")
    official, manifest = helper.load_official()
    cases = load_cases(manifest)
    directory = args.batch.resolve() if args.batch else None
    if directory:
        require(directory.is_relative_to(RESULTS.resolve()), "批次须位于3.2运行结果目录")
        state = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        validate_state(state, directory, official, cases)
    else:
        require(args.stage == "writer", "评分和汇总须指定已有--batch")
        state = new_state(cases)
    selected = [e for e in state["entries"] if args.stage != "summary" and e[args.stage]["status"] == "pending"
                and (args.stage != "judge" or e["writer"]["status"] == "saved")][:args.limit]
    budget = sum(len(cases[e["test_id"]][0]["conversation_histories"]) + 1 for e in selected) if args.stage == "writer" else len(selected)
    print(f"计划60题×四格式=240组；本次{args.stage}最多处理{len(selected)}组，最多{budget}次推理请求。")
    print("本次用例：", ", ".join(dict.fromkeys(e["test_id"] for e in selected)))
    if args.stage == "writer":
        print(f"另有最多{len(selected)}次模型列表查询；不调用云端裁判，无自动重试。")
    elif args.stage == "judge":
        print("仅评分完整答案；DeepSeek请求可能计费，无自动重试。")
    if args.preview:
        print("FOUR_MODE_CAMPAIGN_PREVIEW_ONLY：零网络请求，不创建运行目录。")
        return
    if directory is None:
        directory = RESULTS / ("four_mode_campaign_" + helper.now().strftime("%Y%m%d_%H%M%S_%f"))
        directory.mkdir(parents=True, exist_ok=False)
    lock = directory / ".run.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        if args.batch:
            state = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        validate_state(state, directory, official, cases, recover=True)
        save_batch(directory, state)
        print("四格式批次：", directory, flush=True)
        if args.stage != "summary":
            run_pending(directory, state, args.stage, official, cases, args.limit)
        save_batch(directory, state)
        print("批次汇总：", directory / "summary.md")
        report = summarize(state)
        print(json.dumps({k: v for k, v in report.items() if k not in {"by_mode", "by_layer"}}, ensure_ascii=False, indent=2))
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
