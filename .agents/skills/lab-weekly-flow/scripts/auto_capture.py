#!/usr/bin/env python3
"""Observe the current completed learning turn, without models or history scans."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import time

import learning_flow as flow

LEARNING = re.compile(r'学习|复习|预习|课程|课件|实验|论文|科研|读书|笔记|知识库|周报|工作流|仓库|源码|单位换算|代码|编程|算法|检索|工具调用|模型|计算机网络|数据结构|机器学习|深度学习|脑电|消融|\b(?:git|github|obsidian|deeptutor|hermes|agent|rag|mcp|skill|review|PR|EEG|BCI)\b', re.I)
OPTOUT = re.compile(r'不要记录|别记录|不必记录|不记入周报|不要归档|私人内容|仅闲聊')
SMALL_TALK = re.compile(r'^[\s，。！!~～]*(?:你好|谢谢|好的?|收到|嗯+|哈哈+|早上好|在吗)[\s，。！!~～]*$')
FOLLOWUP = re.compile(r'为什么|怎么理解|没[有]?看懂|不理解|解释一下|再解释|讲解|举[个一]例|具体一点|继续|下一步|这个怎么|那这个|这一步|这具体')
URL = re.compile(r'https?://[^\s<>]+', re.I)
TECH_LINK = re.compile(r'https?://(?:github\.com|arxiv\.org|huggingface\.co|docs\.[^/ ]+|[^/ ]+/(?:blog|docs|papers?)/)', re.I)
SECRET = re.compile(r'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:OPENSSH |RSA )?PRIVATE KEY-----|(?:api[_-]?key|access[_-]?token)\s*[=:]\s*[\"\']?[A-Za-z0-9_\-/+=]{24,})', re.I)


def classify(user, assistant, prior_learning_at=None, timestamp=None):
    if OPTOUT.search(user):
        return None, 'owner_opt_out'
    if SECRET.search(user) or SECRET.search(assistant):
        return None, 'credential_like_text_not_archived'
    if SMALL_TALK.fullmatch(user):
        return None, 'small_talk'
    if LEARNING.search(user):
        reason = 'learning_term_in_current_user_message'
    elif TECH_LINK.search(user):
        reason = 'technical_resource_link'
    elif URL.search(user) and len(LEARNING.findall(assistant)) >= 2:
        reason = 'resource_link_with_learning_related_reply'
    elif prior_learning_at and 0 <= (timestamp or time.time())-prior_learning_at <= 1800 and FOLLOWUP.search(user):
        reason = 'short_followup_to_recent_learning_turn'
    else:
        return None, 'not_matched'
    if URL.search(user):
        return 'resource', reason
    if re.search(r'计划|打算|明天|下周|准备', user) and not re.search(r'完成了|已完成|跑通|解决了|已解决', user):
        return 'plan', reason
    return 'context', reason


def input_record(user):
    # Current Hermes central STT wraps successful transcripts in a quoted
    # prefix; Weixin's fallback has an explicit voice marker. Quoted typed
    # material is conservatively unverified too, because this hook lacks
    # authoritative input-medium metadata. Retain the complete input unchanged.
    value = user.lstrip()
    uncertain = value.startswith('"') or bool(re.match(
        r'\[(?:Voice transcription|The user sent a voice|voice message|User sent audio)', value, re.I))
    if uncertain:
        return 'assistant-summary', '网关输入/可能语音转写（待本人核对；不作为逐字原话归档）。\n原始网关字段完整保留：\n\n'+user
    return 'user-original', user


def same_text(root, date, kind, text):
    sha = flow.digest(text.encode('utf-8'))
    for p in sorted((root/'收件箱'/date).glob('*.json')):
        e = flow.validate_event(flow.read_json(p))
        if e['channel']=='wechat' and e['kind']==kind and e['text_sha256']==sha:
            return e
    return None


def handle(payload, config, timestamp=None):
    if not config.get('enabled'):
        return {'status':'disabled'}
    if payload.get('hook_event_name')!='post_llm_call':
        return {'status':'ignored_event'}
    extra = payload.get('extra') or {}
    platform = extra.get('platform')
    if platform not in config.get('platforms',['weixin']):
        return {'status':'ignored_platform'}
    session = payload.get('session_id')
    user, assistant = extra.get('user_message'), extra.get('assistant_response')
    if not isinstance(session,str) or not session or not isinstance(user,str) or not user.strip() or not isinstance(assistant,str):
        return {'status':'missing_current_turn_fields'}
    # The hook input can contain history/tool data. Only the two current-turn
    # text fields above are inspected or saved; history is deliberately ignored.
    current = timestamp if timestamp is not None else time.time()
    date = dt.datetime.fromtimestamp(current,dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    root = Path(config['workflow_root']).expanduser().resolve()
    key = flow.digest(session.encode())
    state_path = root/'自动采集状态/会话状态'/(key+'.json')
    prior = flow.read_json(state_path) if state_path.exists() else {}
    category, reason = classify(user,assistant,prior.get('last_learning_at'),current)
    turn = str(extra.get('turn_id') or flow.digest(flow.canonical([user,assistant])))
    ledger_id = flow.digest(flow.canonical([session,turn,user,assistant]))
    ledger_path = root/'自动采集状态'/date/(ledger_id+'.json')
    if ledger_path.exists():
        return flow.read_json(ledger_path)
    result = {'version':1,'status':'skipped','date':date,'date_basis':'collection_date; actual occurrence is retained in original wording',
              'session_sha256':key,'turn_sha256':flow.digest(turn.encode()),'reason':reason,'event_ids':[]}
    if category:
        if len(user.encode('utf-8')) > 200000:
            result['reason']='user_message_exceeds_event_limit'
        else:
            input_kind, input_text = input_record(user)
            original = same_text(root,date,input_kind,input_text)
            if original is None:
                p=flow.capture(root,date,input_text,'wechat',input_kind,'hermes-auto:'+ledger_id+':input',category)
                original=flow.read_json(p)
            result['event_ids'].append(original['id'])
            result['input_kind']=input_kind
            if assistant.strip():
                text='AI最终回复存档（未经本人核对，不代表本人掌握或独立验证）。\n关联输入记录编号：'+original['id']+'\n采集日期：'+date+'；实际事项日期以原话为准。\n\n'+assistant
                if len(text.encode('utf-8'))<=200000:
                    summary=same_text(root,date,'assistant-summary',text)
                    if summary is None:
                        p=flow.capture(root,date,text,'wechat','assistant-summary','hermes-auto:'+ledger_id+':assistant',category)
                        summary=flow.read_json(p)
                    result['event_ids'].append(summary['id'])
                else:
                    result['assistant_status']='too_large_not_truncated'
            result['status']='captured'
            state_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            flow.replace_state(state_path,{'version':1,'last_learning_at':current})
            state_path.chmod(0o600)
    elif reason in ('not_matched','owner_opt_out','credential_like_text_not_archived'):
        # Unrelated/private/credential turns end the short follow-up window.
        state_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        flow.replace_state(state_path,{'version':1,'last_learning_at':None})
        state_path.chmod(0o600)
    ledger_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    flow.store(ledger_path,flow.canonical(result)+b'\n')
    ledger_path.chmod(0o600)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True)
    args=p.parse_args()
    raw=sys.stdin.buffer.read(8_000_001)
    if len(raw)>8_000_000:
        raise ValueError('HOOK_INPUT_TOO_LARGE')
    handle(json.loads(raw),flow.read_json(args.config))
    # Observer hook: no model-context changes, user messages or automatic replies.
    print('{}')


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('LEARNING_CAPTURE_ERROR:'+type(error).__name__,file=sys.stderr)
        sys.exit(1)
