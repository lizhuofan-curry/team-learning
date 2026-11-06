"""Read explicitly watched pull-request snapshots; no implicit network access."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

TIMEZONE = dt.timezone(dt.timedelta(hours=8))
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
SHA = re.compile(r'[a-f0-9]{40}')
BAD = frozenset(('failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure'))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def identity(repository, number):
    if (not isinstance(repository, str) or not REPOSITORY.fullmatch(repository)
            or type(number) is not int or number < 1):
        raise ValueError('invalid pull request identity')
    return repository + '#' + str(number)


def snapshot_path(root, repository, number):
    key = hashlib.sha256(identity(repository, number).encode()).hexdigest()[:24]
    return Path(root) / '任务中枢' / 'pr_snapshots' / (key + '.json')


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('missing timestamp')
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timezone required')
    return result


def validate_snapshot(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('invalid snapshot')
    identity(value.get('repository'), value.get('number'))
    if (value.get('state') not in ('open', 'closed') or type(value.get('merged')) is not bool
            or type(value.get('draft')) is not bool or not SHA.fullmatch(value.get('head_sha', ''))
            or not isinstance(value.get('checks'), list) or type(value.get('test_only', False)) is not bool):
        raise ValueError('invalid pull request metadata')
    if value['merged'] and value['state'] != 'closed':
        raise ValueError('inconsistent merged state')
    timestamp(value.get('fetched_at'))
    timestamp(value.get('updated_at'))
    if len(value['checks']) > 100:
        raise ValueError('too many checks')
    for check in value['checks']:
        if (not isinstance(check, dict) or set(check) != {'name', 'status', 'conclusion', 'head_sha'}
                or not isinstance(check['name'], str) or len(check['name']) > 500
                or check['status'] not in ('queued', 'in_progress', 'completed')
                or not SHA.fullmatch(check['head_sha'])):
            raise ValueError('invalid check metadata')
        if check['conclusion'] is not None and check['conclusion'] not in (
                'success', 'failure', 'neutral', 'cancelled', 'skipped', 'timed_out',
                'action_required', 'startup_failure', 'stale'):
            raise ValueError('invalid check conclusion')
    # Whitelist stored fields so PR descriptions or comments do not enter the index.
    allowed = {'version', 'repository', 'number', 'state', 'merged', 'draft', 'head_sha',
               'updated_at', 'fetched_at', 'checks', 'test_only'}
    if set(value) - allowed:
        raise ValueError('snapshot contains unsupported fields')
    return value


def read_json(path):
    if path.is_symlink():
        raise ValueError('symlink not supported')
    with path.open('rb') as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('snapshot too large')
    try:
        return json.loads(raw.decode('utf-8'))
    except RecursionError as error:
        raise ValueError('snapshot nesting too deep') from error


def configured(root):
    path = Path(root) / 'task_center.local.json'
    if not path.exists():
        return []
    config = read_json(path)
    if not isinstance(config, dict):
        raise ValueError('configuration must be an object')
    entries = config.get('pull_requests', [])
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('invalid watched pull requests')
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('invalid watched pull request')
        key = identity(entry.get('repository'), entry.get('number'))
        if key in seen:
            raise ValueError('duplicate watched pull request')
        seen.add(key)
        result.append(entry)
    return result


def save_snapshot(root, snapshot):
    """Caller must obtain current metadata through a connected GitHub tool first."""
    snapshot = validate_snapshot(snapshot)
    key = identity(snapshot['repository'], snapshot['number'])
    if key not in {identity(e['repository'], e['number']) for e in configured(root)}:
        raise ValueError('pull request is not explicitly watched')
    path = snapshot_path(root, snapshot['repository'], snapshot['number'])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import learning_flow as flow
    flow.replace_state(path, snapshot)
    path.chmod(0o600)
    return path


def build_pr_snapshot(root, now=None, include_tests=False):
    root = Path(root)
    current = now or dt.datetime.now(TIMEZONE)
    if current.utcoffset() is None:
        raise ValueError('timezone required')
    result = dict(tasks=[], events=[], observations=[])
    def observe(code, key, path, detail, severity='warning'):
        result['observations'].append(dict(code=code, source='github-pr', external_id=key,
                                           evidence=str(path), detail=detail, severity=severity))
    try:
        entries = configured(root)
    except (OSError, ValueError, TypeError, AttributeError):
        observe('pr_config_invalid', None, root / 'task_center.local.json', 'PR观察配置无法校验，其他来源仍可读取。')
        return result
    for entry in entries:
        key = identity(entry['repository'], entry['number'])
        path = snapshot_path(root, entry['repository'], entry['number'])
        try:
            item = validate_snapshot(read_json(path))
            if identity(item['repository'], item['number']) != key:
                raise ValueError('snapshot identity mismatch')
        except (OSError, ValueError, TypeError, KeyError):
            observe('pr_snapshot_unavailable', key, path, '没有可核实的PR快照；需用已连接的GitHub工具刷新，不凭本地Git缓存认定远端状态。')
            continue
        if item.get('test_only', False) and not include_tests:
            continue
        current_checks = [c for c in item['checks'] if c['head_sha'] == item['head_sha']]
        failed = any(c['conclusion'] in BAD for c in current_checks)
        if item['merged']:
            status, next_action = 'completed', '快照显示已合并；代码效果和本人掌握仍须另行验证。'
        elif item['state'] == 'closed':
            status, next_action = 'waiting', 'PR已关闭未合并，核对是否需继续或调整任务。'
        elif failed:
            status, next_action = 'blocked', '当前提交存在未通过的检查，先读取实际失败日志。'
            observe('pr_checks_failed', key, path, next_action)
        elif any(c['status'] != 'completed' for c in current_checks):
            status, next_action = 'waiting', '当前提交的检查仍在运行，等待实际检查结果。'
        else:
            status = 'awaiting_review'
            next_action = '草稿PR尚未合并，可继续修订或等待实质审阅。' if item['draft'] else 'PR尚未合并，等待实质审阅与项目合并规则。'
            if not current_checks:
                observe('pr_checks_unverified', key, path, '当前提交没有可核实的检查记录。', severity='info')
        age = (current - timestamp(item['fetched_at'])).total_seconds()
        if age > 900 or age < -60:
            observe('pr_snapshot_stale', key, path, 'PR快照已过期或时钟不一致，当前远端状态待刷新核对。')
            status, next_action = 'waiting', '快照仅为历史观察，先刷新GitHub元数据。'
        url = 'https://github.com/' + entry['repository'] + '/pull/' + str(entry['number'])
        result['tasks'].append(dict(source='github-pr', external_id=key, title='PR：' + key,
                                    kind='pull_request', status=status, evidence=[str(path), url],
                                    next_action=next_action, test_only=item.get('test_only', False), scope='read_only'))
        fingerprint = hashlib.sha256(canonical({k: v for k, v in item.items() if k != 'fetched_at'})).hexdigest()
        result['events'].append(dict(source='github-pr', external_id=key + ':' + fingerprint,
                                     payload=dict(reference=str(path), sha256=fingerprint,
                                                  head_sha=item['head_sha'],
                                                  test_only=item.get('test_only', False)), task_ref=key))
    return result
