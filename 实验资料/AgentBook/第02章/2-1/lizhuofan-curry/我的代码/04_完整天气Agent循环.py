"""一次运行走完：请求模型→执行天气工具→回传结果→模型回答。

复用同目录02的工具说明和03的天气函数；不用先单独运行03。
"""

import copy
import json
from datetime import datetime
from importlib import import_module
from pathlib import Path

import requests
from openai import APIError, OpenAI

# 编号文件名用import_module导入，复用已有代码。
tools = import_module("02_让模型提出工具调用").tools
get_current_temperature = import_module("03_Python执行天气工具").get_current_temperature


def main():
    client = OpenAI(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        timeout=180,
        max_retries=0,
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是中文天气助手。查询当前气温必须使用提供的工具。"
                "工具成功后，根据返回的地点、气温、单位和数据时间直接回答，"
                "不要重复查询。工具失败时如实说明，不要猜测气温。"
            ),
        },
        {"role": "user", "content": "请查询北京现在的气温，用摄氏度表示。"},
    ]
    rounds = []
    tool_executions = []
    final_answer = None
    final_finish_reason = None
    final_saw_successful_tool = False
    failure = None
    max_rounds = 4
    max_tool_attempts = 3
    tool_attempts = 0

    try:
        for round_number in range(1, max_rounds + 1):
            print(f"\n第{round_number}轮请求，消息角色：", [m["role"] for m in messages], flush=True)
            # 保存当时的输入，防止后续append改变历史记录。
            request_messages = copy.deepcopy(messages)
            response = client.chat.completions.create(
                model="qwen3:0.6b",
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
                max_tokens=1024,
            )
            assistant_message = response.choices[0].message
            rounds.append({
                "round": round_number,
                "request_messages": request_messages,
                "response": response.model_dump(mode="json"),
            })

            # 保留模型提出调用的assistant消息，再追加对应tool结果。
            messages.append(assistant_message.model_dump(mode="json", exclude_none=True))
            if not assistant_message.tool_calls:
                final_answer = assistant_message.content
                final_finish_reason = response.choices[0].finish_reason
                final_saw_successful_tool = any(t["succeeded"] for t in tool_executions)
                print("\n模型最终回答：", final_answer or "（未返回正文）", flush=True)
                break

            for call in assistant_message.tool_calls:
                print("模型请求工具：", call.function.name, call.function.arguments, flush=True)
                succeeded = False
                full_result = None
                try:
                    if call.function.name != "get_current_temperature":
                        raise ValueError("本实验仅注册get_current_temperature工具")
                    arguments = json.loads(call.function.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("工具参数必须是JSON对象")
                    if tool_attempts >= max_tool_attempts:
                        raise ValueError("已达到工具执行次数上限")
                    tool_attempts += 1
                    full_result = get_current_temperature(**arguments)
                    succeeded = True
                    # 原始天气响应保存在记录中；向模型提供当前任务需要的字段。
                    result = {k: v for k, v in full_result.items()
                              if k not in ("raw_weather", "geocoding_url", "weather_url")}
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    result = {"error_type": type(exc).__name__, "error": str(exc)}

                print("Python工具结果：", json.dumps(result, ensure_ascii=False), flush=True)
                tool_executions.append({
                    "round": round_number,
                    "tool_call_id": call.id,
                    "tool_name": call.function.name,
                    "arguments_string": call.function.arguments,
                    "succeeded": succeeded,
                    "full_result": full_result,
                    "returned_content": result,
                })

                # 核心新增：以tool角色回传，用调用编号对应模型的请求。
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
                print("已追加tool消息，下一轮模型会收到这份结果。", flush=True)
        else:
            failure = "达到模型请求轮数上限，尚未得到最终回答"
    except APIError as exc:
        failure = f"{type(exc).__name__}: {exc}"

    core_loop_completed = bool(
        final_answer and final_finish_reason == "stop" and final_saw_successful_tool
    )
    evidence = {
        "model": "qwen3:0.6b",
        "tools": tools,
        "parameters": {"temperature": 0, "max_tokens": 1024, "tool_choice": "auto"},
        "rounds": rounds,
        "tool_executions": tool_executions,
        "messages": messages,
        "final_answer": final_answer,
        "final_finish_reason": final_finish_reason,
        "core_loop_completed": core_loop_completed,
        "answer_fact_checked": False,
        "failure": failure,
    }
    result_dir = Path(__file__).resolve().parents[1] / "运行结果"
    result_dir.mkdir(exist_ok=True)
    result_path = result_dir / f"04_完整循环_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    result_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n本次记录：", result_path)
    if core_loop_completed:
        print("CORE_LOOP_COMPLETE：工具执行、结果回传和最终回答链路已完成。")
        print("请对照工具结果检查最终回答中的气温、单位和时间。")
    else:
        print("CORE_LOOP_INCOMPLETE：", failure or "尚未形成成功的工具调用与最终回答链路")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
