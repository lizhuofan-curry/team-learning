"""第一步：通过兼容接口向本机Qwen发送两条消息，读取回答。"""

import json
from datetime import datetime
from pathlib import Path

from openai import OpenAI


def main():
    # 请求发往本机Ollama；这里的api_key只是SDK要求的占位值。
    client = OpenAI(
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        timeout=180,
        max_retries=0,
    )

    messages = [
        {"role": "system", "content": "你是一个使用中文回答的助手。"},
        {"role": "user", "content": "你好，请用一句话介绍你自己。"},
    ]

    print("正在请求本机的qwen3:0.6b，首次调用需要加载模型……", flush=True)
    response = client.chat.completions.create(
        model="qwen3:0.6b",
        messages=messages,
        max_tokens=1024,
    )

    answer = response.choices[0].message.content
    print("模型回答：", answer or "（本轮没有返回正文，请检查原始响应）")

    # 保存本次输入和原始响应，便于复习以及记录周报。
    result_dir = Path(__file__).resolve().parents[1] / "运行结果"
    result_dir.mkdir(exist_ok=True)
    result_path = result_dir / f"01_普通对话_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    result_path.write_text(
        json.dumps(
            {"messages": messages, "response": response.model_dump(mode="json")},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("本次记录：", result_path)


if __name__ == "__main__":
    main()
