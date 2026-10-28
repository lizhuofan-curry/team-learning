"""1次预热+两组各3次请求：观察流式正文、客户端延迟和服务报告的缓存字段。

本地学习对照，不调用天气工具；正文首块延迟近似TTFT，输出速率按总耗时计算。
"""

import json
import random
import statistics
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from openai import APIError, OpenAI

MODEL = "qwen3:0.6b"
REPEATS = 3
# 两组使用相同背景，只改变最开头的等长编号。
# 这里是重复了 40 次的背景文字，marker是一个 16 位编号
'''
stable 组，每次都用同一个编号：

1111111111111111 + 相同背景 + 相同问题
1111111111111111 + 相同背景 + 相同问题
1111111111111111 + 相同背景 + 相同问题


changed 组，每次换一个编号：

2222222222222222 + 相同背景 + 相同问题
3333333333333333 + 相同背景 + 相同问题
4444444444444444 + 相同背景 + 相同问题
'''

BACKGROUND = (
    "Reference: an agent receives messages, selects available tools, reads tool results, "
    "and uses evidence to answer the user. Preserve earlier decisions and keep the "
    "system instructions stable across requests.\n"
) * 40
QUESTION = "请用两句简短中文说明Agent为什么需要工具。"


def new_marker():
    return f"{uuid4().int % 10**16:016d}"


def measure(client, group, marker):
    messages = [
        {"role": "system", "content": marker + "\n你是中文助手。\n" + BACKGROUND},
        {"role": "user", "content": QUESTION},
    ]
    print(f"\n[{group}] 流式回答：", end="", flush=True)
    started = time.perf_counter()
    first_content_at = None
    fragments = []
    chunks = []
    usage = None
    finish_reason = None

    # 关闭思考，只观察正文；两组设置完全相同。
    with client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        reasoning_effort="none",
        temperature=0,
        max_tokens=128,
    ) as stream:
        for chunk in stream:
            chunks.append(chunk.model_dump(mode="json"))
            if chunk.usage is not None:
                usage = chunk.usage.model_dump(mode="json")
            for choice in chunk.choices:
                if choice.finish_reason is not None:
                    finish_reason = choice.finish_reason
                text = choice.delta.content
                if text:
                    if first_content_at is None:
                        first_content_at = time.perf_counter()
                    fragments.append(text)
                    print(text, end="", flush=True)

    elapsed = time.perf_counter() - started
    first_content_seconds = None if first_content_at is None else first_content_at - started
    prompt_tokens = usage.get("prompt_tokens") if usage else None
    completion_tokens = usage.get("completion_tokens") if usage else None
    details = (usage.get("prompt_tokens_details") or {}) if usage else {}
    cached_tokens = details.get("cached_tokens")
    rate = completion_tokens / elapsed if completion_tokens is not None else None
    answer = "".join(fragments)
    row = {
        "group": group,
        "marker": marker,
        "request_messages": messages,
        "answer": answer,
        "finish_reason": finish_reason,
        "first_content_seconds": first_content_seconds,
        "total_seconds": elapsed,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "completion_tokens_per_total_second": rate,
        "usage": usage,
        "raw_chunks": chunks,
    }
    print()
    print(
        "首段正文延迟：", display(first_content_seconds), "秒；",
        "总耗时：", display(elapsed), "秒；",
        "prompt_tokens：", prompt_tokens,
        "cached_tokens：", cached_tokens if cached_tokens is not None else "服务未返回",
        flush=True,
    )
    return row


def display(value):
    return "未返回" if value is None else f"{value:.4f}"


def summarize(rows):
    summary = {}
    for group in ("stable", "changed"):
        group_rows = [row for row in rows if row["group"] == group]
        latencies = [r["first_content_seconds"] for r in group_rows
                     if r["first_content_seconds"] is not None]
        rates = [r["completion_tokens_per_total_second"] for r in group_rows
                 if r["completion_tokens_per_total_second"] is not None]
        all_reported = bool(group_rows) and all(
            r["cached_tokens"] is not None and r["prompt_tokens"] is not None for r in group_rows
        )
        total_prompt = sum(r["prompt_tokens"] for r in group_rows) if all_reported else None
        cached_fraction = (
            sum(r["cached_tokens"] for r in group_rows) / total_prompt
            if total_prompt else None
        )
        summary[group] = {
            "samples": len(group_rows),
            "median_first_content_seconds": statistics.median(latencies) if latencies else None,
            "median_completion_tokens_per_total_second": statistics.median(rates) if rates else None,
            "reported_cached_token_fraction": cached_fraction,
        }
        print(
            group,
            "样本数：", len(group_rows),
            "首段正文延迟中位数：", display(summary[group]["median_first_content_seconds"]), "秒；",
            "端到端输出速率中位数：", display(summary[group]["median_completion_tokens_per_total_second"]),
            "token/s；服务报告缓存token比例：", display(cached_fraction),
        )
    return summary


def main():
    client = OpenAI(
        base_url="http://127.0.0.1:11434/v1", api_key="ollama", timeout=180, max_retries=0,
    )
    stable_marker = new_marker()
    rows = []
    warmup = None
    failure = None
    print("共7次本机请求：预热1次不计入比较，稳定前缀与变化前缀各3次。", flush=True)
    try:
        # 第一次请求用了 18.7 秒，可能包含模型加载等启动开销，所以排除，不参与比较
        # 它同时也为固定前缀建立了缓存
        warmup = measure(client, "warmup", stable_marker)
        schedule = ["stable"] * REPEATS + ["changed"] * REPEATS
        random.Random(42).shuffle(schedule)
        for group in schedule:
            # 属于 stable 就拿固定编号，属于 changed 就生成新编号
            # 模型处理输入时，可以缓存已计算过的前缀对应的 KV 状态
            # stable：输入和此前一样，可以复用大量已有计算
            # changed：从开头就变了，即使后面的文字相同，也会破坏连续前缀的匹配，后面需要重新计算
            marker = stable_marker if group == "stable" else new_marker()
            rows.append(measure(client, group, marker))
    except APIError as exc:
        failure = f"{type(exc).__name__}: {exc}"
        print("请求失败：", failure)

    print("\n对照汇总（不包含预热）：")
    summary = summarize(rows)
    completed = (
        failure is None and len(rows) == 2 * REPEATS
        and all(r["answer"] and r["finish_reason"] == "stop" for r in rows)
    )
    result = {
        "model": MODEL,
        "parameters": {"reasoning_effort": "none", "temperature": 0, "max_tokens": 128},
        "repeats_per_group": REPEATS,
        "warmup_excluded_from_summary": True,
        "warmup": warmup,
        "rows": rows,
        "summary": summary,
        "observation_completed": completed,
        "failure": failure,
        "metric_notes": [
            "首段正文延迟是客户端到达首个非空正文块的时间，近似TTFT。",
            "端到端输出速率=completion_tokens/请求总耗时，包含prefill和传输，不是纯解码吞吐。",
            "缓存比例仅使用服务实际报告的cached_tokens；字段缺失不按0处理。",
            "各组3次为本机探索性观察，不能由一次耗时差异或有限样本推断普遍性能结论。",
            "等长开头编号不保证token数完全相同，以服务返回prompt_tokens为准。",
            "本观察不是实验2-3中多种错误上下文管理模式的完整复现。",
        ],
    }
    result_dir = Path(__file__).resolve().parents[1] / "运行结果"
    result_dir.mkdir(exist_ok=True)
    path = result_dir / f"05_流式与缓存观察_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("本次记录：", path)
    print("延迟与速率仅按本次实测解释；缓存字段缺失时保留未知。")
    if completed:
        print("OBSERVATION_COMPLETE：流式输出与两组观测完成，具体差异请看汇总。")
    else:
        print("OBSERVATION_INCOMPLETE：请求失败、输出截断或样本不足，请反馈实际输出。")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
