"""用户运行：使用已有DeepSeek配置，复测03相同的三个基础任务。

复用03任务提示、工具、模拟世界和评分，只替换请求适配与保存记录。
最多6次云端模型请求，可能计费；无预热/自动重试，不重跑原15任务。
"""

import copy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

from dotenv import dotenv_values
from openai import OpenAI


CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
PROJECT = CODE_DIR.parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = load_module('original_basic_tool_diagnostic', CODE_DIR / '03_基础工具链检查.py')
WRITER_PATH = ROOT.parent / '2.10上下文压缩策略对比' / '我的代码' / 'safe_records.py'
atomic_json_dump = load_module('status_atomic_records', WRITER_PATH).atomic_json_dump


def sha(data):
    return hashlib.sha256(data).hexdigest()


def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, '[REDACTED]') if secret else value
    if isinstance(value, dict):
        return {key: redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    return value


def total_usage(record, field):
    turns = [turn for row in record['rows'] for turn in row['turns']]
    if not turns or any(not isinstance((turn.get('usage') or {}).get(field), int) for turn in turns):
        return None
    return sum(turn['usage'][field] for turn in turns)


def cloud_request(client, messages, tools, row, checkpoint, record):
    attempts = sum(len(item['turns']) for item in record['rows'])
    if attempts >= 6:
        raise ValueError('达到6次模型请求上限。')
    kwargs = {'model': record['model'], 'messages': copy.deepcopy(messages),
              'tools': copy.deepcopy(tools), 'tool_choice': 'auto', 'temperature': 0,
              'max_tokens': 512, 'stream': False,
              'extra_body': {'thinking': {'type': 'disabled'}}}
    wire = {key: value for key, value in kwargs.items() if key != 'extra_body'}
    wire.update(kwargs['extra_body'])
    turn = {'request_messages': copy.deepcopy(messages), 'tools': copy.deepcopy(tools),
            'actual_request_body': wire}
    row['turns'].append(turn)
    checkpoint()
    print(f'  云端请求 {attempts + 1}/6……', flush=True)
    started = time.perf_counter()
    response = client.chat.completions.create(**kwargs)
    turn['elapsed_seconds'] = time.perf_counter() - started
    turn['response'] = response.model_dump(mode='json')
    turn['usage'] = response.usage.model_dump(mode='json') if response.usage else None
    # 收到响应即保存，后续协议检查出错也不丢失实际响应。
    checkpoint()
    if len(response.choices) != 1:
        raise ValueError('需且仅需一份choice。')
    choice = response.choices[0]
    # 复用的03不处理思考历史；本阶段关闭思考，意外收到则停止，不悄悄丢弃。
    if getattr(choice.message, 'reasoning_content', None):
        raise ValueError('意外返回非空reasoning_content；已保留原响应，需要单独检查思考模式。')
    calls = choice.message.tool_calls or []
    if choice.finish_reason not in ('stop', 'tool_calls', 'length'):
        raise ValueError('未知finish_reason；保留响应，不执行工具。')
    if choice.finish_reason == 'length':
        return choice  # 由03记录为截断；不执行不完整动作。
    identifiers = [call.id for call in calls]
    seen_ids = row.setdefault('seen_call_ids', [call['id'] for message in messages
                                              for call in message.get('tool_calls', [])])
    if (len(calls) > 4 or any(not isinstance(identifier, str) or not identifier for identifier in identifiers)
            or len(set(identifiers)) != len(identifiers) or any(identifier in seen_ids for identifier in identifiers)):
        raise ValueError('工具数量超限或ID无效/重复；不伪造ID或执行部分动作。')
    seen_ids.extend(identifiers)
    return choice


def run_checks(client, record, checkpoint):
    # 注入请求函数；03的三个任务输入、工具执行与评分逻辑原样复用。
    original_request = legacy.request
    legacy.request = lambda client_, messages, tools, row, save: cloud_request(
        client_, messages, tools, row, save, record)
    try:
        for kind, title in [('read', '单次读取'), ('submit', '提交已提供的读取结果'), ('loop', '先读后提交再回复')]:
            row = {'kind': kind, 'turns': []}
            record['rows'].append(row)
            checkpoint()
            print('\n检查：', title, flush=True)
            if kind == 'loop':
                legacy.loop_check(client, row, checkpoint)
            else:
                legacy.single_check(client, kind, row, checkpoint)
            print('判定：', '通过' if row['passed'] else '未通过', flush=True)
            print('实际模拟动作：', [(event['tool'], event['ok']) for event in row['events']], flush=True)
            print('正文：', row.get('body') or '（无正文）', flush=True)
    finally:
        legacy.request = original_request


def write_report(record, directory):
    lines = ['# DeepSeek基础工具链检查', '',
             '复用03三个任务的提示、工具与评分；改变模型/服务与请求适配，独立诊断，不覆盖旧结果。', '',
             '| 检查 | 通过 | 请求数 | 实际新动作 |', '| --- | --- | ---: | --- |']
    for row in record['rows']:
        actions = ', '.join(event['tool'] + ':' + str(event['ok']) for event in row.get('events', []))
        lines.append(f'| {row["kind"]} | {row.get("passed", "未测完")} | {len(row["turns"])} | {actions or "无"} |')
    lines += ['', f'全部基础检查通过：{record["basic_chain_ready"]}',
              f'测量完整：{record["complete"]}', f'输入token：{record["prompt_tokens"]}；输出token：{record["completion_tokens"]}', '',
              '单次提交检查的原文已由程序提供；只有loop检查验证模型自行读取、处理结果、提交、最终回复的完整推进。',
              '若三项通过，下一步再准备同一新模型下的15任务对照；不能据此修改原Qwen成绩或宣称状态栏有效。']
    (directory / '诊断汇总.md').write_bytes('\n'.join(lines).encode('utf-8'))


def main():
    config = dotenv_values(PROJECT / '.env')

    def setting(name, default=''):
        return (os.environ.get(name) or config.get(name) or default).strip()

    key = setting('DEEPSEEK_API_KEY')
    if not key:
        raise ValueError('项目根目录.env缺少DEEPSEEK_API_KEY。')
    timeout = float(setting('DEEPSEEK_TIMEOUT', '180'))
    if not 1 <= timeout <= 300:
        raise ValueError('DEEPSEEK_TIMEOUT须在1～300秒之间。')
    directory = ROOT / '诊断结果' / ('deepseek_basic_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    directory.mkdir(parents=True)
    record = {'stage': 'deepseek_basic_tool_diagnostic', 'created_at': datetime.now().astimezone().isoformat(),
              'model': setting('DEEPSEEK_MODEL', 'deepseek-flash'),
              'base_url': setting('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
              'parameters': {'temperature': 0, 'max_tokens': 512, 'thinking': {'type': 'disabled'}, 'tool_choice': 'auto'},
              'max_retries': 0, 'max_requests': 6, 'warmup_requests': 0,
              'rows': [], 'error': None, 'complete': False, 'basic_chain_ready': False,
              'source_sha256': {path.name: sha(path.read_bytes()) for path in
                                [Path(__file__), CODE_DIR / '03_基础工具链检查.py', CODE_DIR / 'status_tools.py', WRITER_PATH]},
              'scope': '不同模型/服务的独立基础诊断；不唯一定位Qwen权重、Ollama模板或解析器，也不是15任务的新成绩'}

    def checkpoint():
        atomic_json_dump(directory / 'record.json', redact(record, key))

    client = OpenAI(api_key=key, base_url=record['base_url'], timeout=timeout, max_retries=0)
    checkpoint()
    print('使用已有DeepSeek API，可能计费；三个基础任务，最多6次模型请求，无预热、搜索或自动重试。', flush=True)
    print('模型：', record['model'], '；本次目录：', directory, flush=True)
    try:
        run_checks(client, record, checkpoint)
        record['complete'] = len(record['rows']) == 3 and all('passed' in row for row in record['rows'])
        record['basic_chain_ready'] = record['complete'] and all(row['passed'] for row in record['rows'])
    except Exception as error:
        record['error'] = {'type': type(error).__name__, 'message': redact(str(error), key)}
        print('检查中断：', record['error'], flush=True)
    finally:
        record['model_request_attempts'] = sum(len(row['turns']) for row in record['rows'])
        record['model_responses'] = sum('response' in turn for row in record['rows'] for turn in row['turns'])
        record['prompt_tokens'] = total_usage(record, 'prompt_tokens')
        record['completion_tokens'] = total_usage(record, 'completion_tokens')
        checkpoint()
        write_report(record, directory)
        client.close()
    print('基础链路：', '全部通过' if record['basic_chain_ready'] else '未全部通过')
    print('实际模型请求：', record['model_request_attempts'], '；记录：', directory / 'record.json')
    if not record['complete']:
        raise SystemExit(1)
    print('DEEPSEEK_BASIC_TOOL_DIAGNOSTIC_COMPLETE：测量完成；基础链路是否通过看上方判定。')


if __name__ == '__main__':
    main()
