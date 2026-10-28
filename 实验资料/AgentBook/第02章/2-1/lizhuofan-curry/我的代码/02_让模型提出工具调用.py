"""提供天气工具说明，观察模型的调用请求；本步骤不执行天气查询。"""

import json
from datetime import datetime
from pathlib import Path

from openai import OpenAI


# 保留官方实验的工具名、location和unit参数，补充中文说明。
# 这份字典是工具的使用说明，不是查询天气的Python函数。
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_temperature",
            "description": "查询指定城市当前的气温。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "城市英文名称，例如Beijing或Tokyo。",
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "celsius表示摄氏度，fahrenheit表示华氏度。",
                    },
                },
                "required": ["location", "unit"],
            },
        },
    }
]


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
            "content": "你是中文助手。查询实时气温时必须使用提供的工具，不要编造气温。",
        },
        {"role": "user", "content": "请查询北京现在的气温，用摄氏度表示。"},
    ]

    print("正在让模型选择工具和参数……", flush=True)
    response = client.chat.completions.create(
        model="qwen3:0.6b",
        messages=messages,
        tools=tools,  # 新增：把工具说明与消息一起发给模型。
        tool_choice="auto",  # 不在API层面强制选择某个工具。
        temperature=0,
        max_tokens=1024,
    )
    assistant_message = response.choices[0].message

    if assistant_message.tool_calls:
        for call in assistant_message.tool_calls:
            print("调用编号：", call.id)
            print("工具名称：", call.function.name)
            print("参数字符串：", call.function.arguments)
        print("本步骤到此停止：模型已提出调用请求，Python还没有执行工具。")
    else:
        print("本轮未返回结构化tool_calls。模型正文：", assistant_message.content)

    result_dir = Path(__file__).resolve().parents[1] / "运行结果"
    result_dir.mkdir(exist_ok=True)
    result_path = result_dir / f"02_工具调用请求_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    result_path.write_text(
        json.dumps(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0,
                "max_tokens": 1024,
                "tool_executed": False,
                "response": response.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("本次记录：", result_path)


if __name__ == "__main__":
    main()
