"""读取02保存的调用请求，由Python执行真实天气查询；暂不再请求模型。"""

import json
from datetime import datetime
from pathlib import Path

import requests


def get_current_temperature(location, unit):
    """先把城市名称转换为经纬度，再请求Open-Meteo的当前气温。"""
    if not isinstance(location, str) or not location.strip():
        raise ValueError("location必须是非空城市名称")
    if unit not in ("celsius", "fahrenheit"):
        raise ValueError("unit必须是celsius或fahrenheit")

    geo_response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1, "language": "en"},
        timeout=20,
    )
    geo_response.raise_for_status()
    places = geo_response.json().get("results", [])
    if not places:
        raise ValueError(f"天气服务没有找到城市：{location}")
    place = places[0]

    weather_response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m",
            "temperature_unit": unit,
            "timezone": "auto",
        },
        timeout=20,
    )
    weather_response.raise_for_status()
    weather = weather_response.json()

    return {
        "location": place["name"],
        "country": place.get("country"),
        "temperature": weather["current"]["temperature_2m"],
        "unit": weather["current_units"]["temperature_2m"],
        "data_time": weather["current"]["time"],
        "timezone": weather["timezone"],
        "source": "Open-Meteo",
        "geocoding_url": geo_response.url,
        "weather_url": weather_response.url,
        "raw_weather": weather,
    }


def main():
    result_dir = Path(__file__).resolve().parents[1] / "运行结果"
    previous_runs = sorted(result_dir.glob("02_工具调用请求_*.json"))
    if not previous_runs:
        raise FileNotFoundError("请先运行02，保存一份工具调用请求")
    source_path = previous_runs[-1]
    previous = json.loads(source_path.read_text(encoding="utf-8"))
    calls = previous["response"]["choices"][0]["message"].get("tool_calls")
    if not calls or len(calls) != 1:
        raise ValueError("本步骤只处理一条工具调用，请检查02的实际输出")
    call = calls[0]
    if call["function"]["name"] != "get_current_temperature":
        raise ValueError("工具名不匹配，本步骤只执行天气工具")

    # 模型返回的是JSON字符串，需要先转换为Python字典。
    arguments = json.loads(call["function"]["arguments"])
    print("读取调用记录：", source_path, flush=True)
    print("模型提供的参数：", arguments, flush=True)
    print("Python正在请求天气服务……", flush=True)

    try:
        # **把字典中的location和unit展开成函数的两个关键字参数。
        result = get_current_temperature(**arguments)
        succeeded = True
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        result = {"error_type": type(exc).__name__, "error": str(exc)}
        succeeded = False

    if succeeded:
        print("城市：", result["location"], result["country"])
        print("工具返回气温：", result["temperature"], result["unit"])
        print("数据时间：", result["data_time"], result["timezone"])
        print("数据来源：", result["source"])
        print("工具已执行；本步骤尚未把结果交回模型。")
    else:
        print("工具执行失败：", result)

    result_path = result_dir / f"03_天气工具执行_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    result_path.write_text(
        json.dumps(
            {
                "source_request": str(source_path),
                "tool_call_id": call["id"],
                "tool_name": call["function"]["name"],
                "arguments": arguments,
                "tool_attempted": True,
                "tool_succeeded": succeeded,
                "returned_to_model": False,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("本次记录：", result_path)
    if not succeeded:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
