"""用户运行：通过基础检查后，使用DeepSeek复测五类任务×三种状态提醒。

复用01的任务、初始状态、状态栏构造、工具执行、评分与排列；独立保存。
不预热、不搜索，最多90次云端模型请求，可能计费，无自动重试。
"""

import copy
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import random
import time
from types import SimpleNamespace

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


basic = load_module('deepseek_basic_helper', CODE_DIR / '05_DeepSeek基础工具链检查.py')
original = load_module('original_status_episodes', CODE_DIR / '01_五种状态栏任务对照.py')
PARAMETERS = {'temperature': 0, 'max_tokens': 512, 'tool_choice': 'auto',
              'thinking': {'type': 'disabled'}}


def load_passed_diagnostic():
    for path in sorted((ROOT / '诊断结果').glob('deepseek_basic_*/record.json'), reverse=True):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('stage') != 'deepseek_basic_tool_diagnostic' or not data.get('complete'):
            continue
        if not data.get('basic_chain_ready') or len(data['rows']) != 3 or not all(row.get('passed') for row in data['rows']):
            raise ValueError('最近完整DeepSeek基础检查未全部通过，请先检查05结果。')
        files = [CODE_DIR / '05_DeepSeek基础工具链检查.py', CODE_DIR / '03_基础工具链检查.py',
                 CODE_DIR / 'status_tools.py', basic.WRITER_PATH]
        for file in files:
            if basic.sha(file.read_bytes()) != data['source_sha256'][file.name]:
                raise ValueError('基础检查后相关脚本已变化，需要先重新确认05。')
        return path.resolve(), data
    raise ValueError('未找到完整通过的05记录，请先运行05。')


def usage_total(calls, field):
    if not calls or any(not isinstance((call.get('usage') or {}).get(field), int) for call in calls):
        return None
    return sum(call['usage'][field] for call in calls)


class CloudAdapter:
    """仅替换请求适配；不改01的模型决策或任务执行逻辑。"""

    def __init__(self, client, record, checkpoint):
        self.client, self.record, self.checkpoint = client, record, checkpoint

    def create(self, **legacy_kwargs):
        row = self.record['rows'][-1]
        if len(self.record['api_calls']) >= 90:
            raise ValueError('达到90次云端请求上限。')
        kwargs = {'model': self.record['model'], 'messages': copy.deepcopy(legacy_kwargs['messages']),
                  'tools': copy.deepcopy(legacy_kwargs['tools']), 'tool_choice': 'auto',
                  'temperature': 0, 'max_tokens': 512, 'stream': False,
                  'extra_body': {'thinking': {'type': 'disabled'}}}
        wire = {key: value for key, value in kwargs.items() if key != 'extra_body'}
        wire.update(kwargs['extra_body'])
        call = {'number': len(self.record['api_calls']) + 1, 'case': row['case'], 'arm': row['arm'],
                'round': len(row['rounds']), 'request': wire, 'status': 'requesting'}
        self.record['api_calls'].append(call)
        self.checkpoint()
        started = time.perf_counter()
        response = self.client.chat.completions.create(**kwargs)
        call.update({'response': response.model_dump(mode='json'), 'status': 'response_received',
                     'elapsed_seconds': time.perf_counter() - started,
                     'usage': response.usage.model_dump(mode='json') if response.usage else None})
        self.checkpoint()  # 先存原始响应，再检查或执行工具。
        if len(response.choices) != 1:
            raise ValueError('需要单一choice；未执行工具。')
        choice = response.choices[0]
        if getattr(choice.message, 'reasoning_content', None):
            raise ValueError('本阶段关闭思考，意外收到思考正文；保留原响应后停止，不丢弃协议字段。')
        if choice.finish_reason not in ('stop', 'tool_calls', 'length'):
            raise ValueError('未知finish_reason；未执行工具。')
        if choice.finish_reason != 'length':
            identifiers = [call.id for call in (choice.message.tool_calls or [])]
            history_ids = {call['id'] for message in kwargs['messages'] for call in message.get('tool_calls', [])}
            if (any(not isinstance(identifier, str) or not identifier for identifier in identifiers)
                    or len(set(identifiers)) != len(identifiers) or any(identifier in history_ids for identifier in identifiers)):
                raise ValueError('工具ID无效或与当前/历史重复；未执行工具。')
        # 01处理截断、轮数及工具数上限，禁止正文JSON代替tool_calls。
        return response


def make_schedule():
    cases = list(original.CASES)
    random.Random(42).shuffle(cases)
    return [(case, arm) for index, case in enumerate(cases)
            for arm in (original.ARMS if index % 2 == 0 else tuple(reversed(original.ARMS)))]


def run_comparison(client, record, checkpoint):
    adapter = CloudAdapter(client, record, checkpoint)
    episode_client = SimpleNamespace(chat=SimpleNamespace(completions=adapter))
    for index, (case, arm) in enumerate(record['schedule'], 1):
        print(f'\n[{index}/15] {original.TITLES[case]} / {original.ARM_TITLES[arm]}', flush=True)
        row = {'case': case, 'arm': arm}
        record['rows'].append(row)
        original.run_episode(episode_client, case, arm, row, checkpoint)
        print('  判定：', '通过' if row['evaluation']['task_success'] else '未通过',
              '；状态：', row['status'], flush=True)


def main():
    diagnostic_path, diagnostic = load_passed_diagnostic()
    config = dotenv_values(PROJECT / '.env')

    def setting(name, default=''):
        return (os.environ.get(name) or config.get(name) or default).strip()

    key = setting('DEEPSEEK_API_KEY')
    if not key:
        raise ValueError('项目根目录.env缺少DEEPSEEK_API_KEY。')
    model = setting('DEEPSEEK_MODEL', 'deepseek-flash')
    base_url = setting('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    if model != diagnostic['model'] or base_url != diagnostic['base_url']:
        raise ValueError('当前模型/地址与通过的05不同，请先用当前配置检查基础链路。')
    timeout = float(setting('DEEPSEEK_TIMEOUT', '180'))
    if not 1 <= timeout <= 300:
        raise ValueError('DEEPSEEK_TIMEOUT须在1～300秒之间。')
    directory = ROOT / '运行结果' / ('deepseek_status_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    directory.mkdir(parents=True)
    record = {'experiment': '2-9', 'stage': 'deepseek_five_status_techniques',
              'model': model, 'base_url': base_url, 'parameters': PARAMETERS,
              'features': list(original.FEATURES), 'tools': original.TOOLS,
              'max_rounds_per_task': original.MAX_ROUNDS, 'max_new_tools_per_task': original.MAX_NEW_CALLS,
              'max_model_requests': 90, 'warmup_requests': 0, 'max_retries': 0,
              'schedule': make_schedule(), 'rows': [], 'api_calls': [], 'failure': None,
              'observation_completed': False, 'started_at': datetime.now().astimezone().isoformat(),
              'passed_basic_record': str(diagnostic_path), 'passed_basic_record_sha256': basic.sha(diagnostic_path.read_bytes()),
              'source_sha256': {path.name: basic.sha(path.read_bytes()) for path in
                               [Path(__file__), CODE_DIR / '01_五种状态栏任务对照.py', CODE_DIR / 'status_tools.py',
                                CODE_DIR / '05_DeepSeek基础工具链检查.py', CODE_DIR / '03_基础工具链检查.py', basic.WRITER_PATH]},
              'scope': 'DeepSeek独立15任务对照；组内仅切换提醒，原Qwen失败保留，不作跨模型速度或单一根因归因'}

    def checkpoint():
        basic.atomic_json_dump(directory / 'record.json', basic.redact(record, key))

    client = OpenAI(api_key=key, base_url=base_url, timeout=timeout, max_retries=0)
    checkpoint()
    print('2-9 DeepSeek：五类任务×三配置=15个多轮任务，使用项目根目录.env。', flush=True)
    print('可能计费；无预热、搜索或网页请求；每任务最多6轮/12个新工具动作，总计最多90次模型请求，无自动重试。', flush=True)
    print('复用原任务、状态栏、模拟工具和评分；不强制工具或替模型修正动作。', flush=True)
    print('模型：', model, '；基础检查已通过；本次目录：', directory, flush=True)
    try:
        run_comparison(client, record, checkpoint)
        record['observation_completed'] = len(record['rows']) == 15 and all('evaluation' in row for row in record['rows'])
    except Exception as error:
        record['failure'] = {'type': type(error).__name__, 'message': basic.redact(str(error), key)}
        print('运行中断：', record['failure'], flush=True)
    finally:
        record['model_request_attempts'] = len(record['api_calls'])
        record['actual_model_responses'] = sum('response' in call for call in record['api_calls'])
        record['all_prompt_tokens'] = usage_total(record['api_calls'], 'prompt_tokens')
        record['all_completion_tokens'] = usage_total(record['api_calls'], 'completion_tokens')
        record['finished_at'] = datetime.now().astimezone().isoformat()
        checkpoint()
        report = original.make_summary(record['rows']).replace('# 2-9本机任务结果', '# 2-9 DeepSeek任务结果').replace(
            '模型请求是真实本机调用', '模型请求为DeepSeek云端API调用')
        report += ('\n本轮独立记录，旧Qwen结果不变；无预热，最多90次云端请求，失败也计为请求尝试。\n'
                   f'实际请求：{record["model_request_attempts"]}；输入token：{record["all_prompt_tokens"]}；'
                   f'输出token：{record["all_completion_tokens"]}。\n')
        (directory / '对照汇总.md').write_bytes(report.encode('utf-8'))
        client.close()
    print('\n三种配置汇总：')
    for arm in original.ARMS:
        rows = [row for row in record['rows'] if row['arm'] == arm and 'evaluation' in row]
        print(original.ARM_TITLES[arm], '通过', sum(row['evaluation']['task_success'] for row in rows), '/', len(rows),
              '（计划5项，未测完不补成绩）')
    print('实际模型请求：', record['model_request_attempts'], '；记录：', directory / 'record.json')
    print('对照表：', directory / '对照汇总.md')
    if not record['observation_completed']:
        raise SystemExit(1)
    print('DEEPSEEK_STATUS_OBSERVATION_COMPLETE：15任务测量完成；任务正确性与提醒效果以实际结果为准。')


if __name__ == '__main__':
    main()
