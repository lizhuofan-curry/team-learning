"""Read only explicitly configured experiment records and log metadata.

An experiment's own record remains the authority. This adapter never executes
source code, reads paths named by a record, or turns a reported success into a
verified research result or a claim of personal mastery.
"""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import stat


TIMEZONE = dt.timezone(dt.timedelta(hours=8))
MAX_CONFIG_BYTES = 1_000_000
MAX_RECORD_BYTES = 4_000_000
MAX_LOG_BYTES = 16_000_000
MAX_EXPERIMENTS = 100
COMPLETE = frozenset(('completed', 'success', 'done', 'succeeded'))
FAILED = frozenset(('failed', 'error'))
RUNNING = frozenset(('running', 'working', 'processing'))
QUEUED = frozenset(('pending', 'queued'))
CANCELLED = frozenset(('cancelled', 'canceled', 'stopped'))
EVIDENCE_FIELDS = ('result', 'results', 'metrics', 'artifacts', 'output_files',
                   'artifact_verification', 'completion_checks')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _observation(code, key, path, detail, severity='warning'):
    return dict(code=code, severity=severity, source='experiment',
                external_id=key, evidence=str(path), detail=detail)


def _json_file(path, limit):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('experiment record must be a regular file')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('record exceeds size limit')
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except RecursionError as error:
        raise ValueError('record nesting too deep') from error
    if not isinstance(data, dict):
        raise ValueError('record must be a JSON object')
    return data, dict(reference=str(path), sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))


def _file_metadata(path, limit):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('experiment log must be a regular file')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        before = path.stat()
        if before.st_size > limit:
            raise ValueError('log exceeds size limit')
        while True:
            chunk = stream.read(min(65536, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('log exceeds size limit')
            digest.update(chunk)
        after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError('log changed while being observed')
    return dict(reference=str(path), sha256=digest.hexdigest(), size=size), after.st_mtime


def _path(root, value):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError('a configured file path is required')
    path = Path(value).expanduser()
    # Do not resolve the final file here: _json_file/_file_metadata reject a
    # symlink instead of silently following a different file.
    return path if path.is_absolute() else root / path


def _entry(root, entry):
    if not isinstance(entry, dict):
        raise ValueError('experiment entry must be an object')
    key, title = entry.get('key'), entry.get('title')
    if (not isinstance(key, str) or not 0 < len(key.strip()) <= 200
            or not isinstance(title, str) or not 0 < len(title.strip()) <= 500):
        raise ValueError('invalid experiment identity')
    test_only = entry.get('test_only', False)
    stale = entry.get('stale_seconds', 3600)
    if (not isinstance(test_only, bool) or isinstance(stale, bool)
            or not isinstance(stale, (int, float)) or not math.isfinite(stale) or stale <= 0):
        raise ValueError('invalid test marker or freshness interval')
    return dict(key=key, title=title, record_path=_path(root, entry.get('record_path')),
                log_path=_path(root, entry['log_path']) if 'log_path' in entry else None,
                test_only=test_only, stale_seconds=stale)


def _nonempty(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (dict, list, str)):
        return bool(value)
    return isinstance(value, (int, float)) and math.isfinite(value)


def _completion_evidence(record):
    fields = [key for key in EVIDENCE_FIELDS if _nonempty(record.get(key))]
    artifact = record.get('artifact_verification')
    checks = record.get('completion_checks')
    contradiction = (isinstance(artifact, dict) and artifact.get('passed') is False)
    if isinstance(checks, dict) and any(value is False for value in checks.values()):
        contradiction = True
    return fields, contradiction


def _project(record):
    raw_status = record.get('status')
    status = raw_status.lower().strip() if isinstance(raw_status, str) else ''
    fields, contradiction = _completion_evidence(record)
    if status in COMPLETE and fields and not contradiction:
        return ('awaiting_review', 'reported_complete', fields,
                '记录报告完成并包含结果字段；读取原结果核对，不据此认定研究结论或本人学习完成。')
    if status in COMPLETE:
        return ('waiting', 'completion_unverified', fields,
                '记录报告完成，但结果字段缺失或检查相互矛盾；先核对原始结果。')
    if status in FAILED:
        return ('blocked', 'reported_failed', fields,
                '实验记录报告失败；核对原始错误与执行范围，不自动重新运行实验。')
    if status in RUNNING:
        return ('working', 'reported_running', fields,
                '实验记录报告执行中；结合指定日志核对进展，不把记录状态当作进程存活证明。')
    if status in QUEUED:
        return ('queued', 'reported_queued', fields, '记录报告待执行；是否启动仍由原实验流程决定。')
    if status in CANCELLED:
        return ('cancelled', 'reported_cancelled', fields, '记录报告已停止；不自动重启。')
    return ('waiting', 'unrecognized', fields,
            '没有可识别的顶层完成状态；需核对原记录，不能从嵌套模型响应或文件时间推定完成。')


def build_experiment_snapshot(root, now=None, include_tests=False):
    """Return task projections, immutable metadata events and observations.

    Configuration: ``task_center.local.json`` ``experiments`` is an explicit
    list of ``key/title/record_path`` and optional ``log_path/stale_seconds/
    test_only``. No paths found inside records or logs are opened. Observation
    time is not written into event payloads, so repeated unchanged reads retain
    identical IDs and payloads.
    """
    root = Path(root).resolve()
    current = now if now is not None else dt.datetime.now(TIMEZONE)
    if not isinstance(current, dt.datetime) or current.utcoffset() is None:
        raise ValueError('now must be a timezone-aware datetime')
    if not isinstance(include_tests, bool):
        raise ValueError('include_tests must be boolean')
    result = dict(tasks=[], events=[], observations=[])
    observations = result['observations']
    config_path = root / 'task_center.local.json'
    if not config_path.exists():
        return result
    try:
        config, _ = _json_file(config_path, MAX_CONFIG_BYTES)
        entries = config.get('experiments', [])
        if not isinstance(entries, list) or len(entries) > MAX_EXPERIMENTS:
            raise ValueError('invalid configured experiment list')
    except (OSError, ValueError, TypeError):
        observations.append(_observation('experiment_config_invalid', None, config_path,
                                         '实验来源配置无法校验；未扫描实验目录或读取其他来源。'))
        return result
    seen = set()
    for raw in entries:
        try:
            item = _entry(root, raw)
            if item['key'] in seen:
                raise ValueError('duplicate configured experiment key')
            seen.add(item['key'])
        except (ValueError, TypeError, OverflowError):
            observations.append(_observation('experiment_config_invalid', None, config_path,
                                             '一条实验配置缺少有效路径/编号或编号重复；已跳过。'))
            continue
        if item['test_only'] and not include_tests:
            continue
        key, path = item['key'], item['record_path']
        try:
            record, metadata = _json_file(path, MAX_RECORD_BYTES)
            source_test = record.get('test_only', item['test_only'])
            if not isinstance(source_test, bool) or source_test != item['test_only']:
                raise ValueError('configured and source test markers differ')
            status, summary, evidence_fields, action = _project(record)
        except (OSError, ValueError, TypeError, OverflowError):
            observations.append(_observation('experiment_record_unavailable', key, path,
                                             '配置的实验记录缺失、过大或无法校验；未读取未配置文件。'))
            continue
        evidence = [str(path)]
        payload = dict(record=metadata, status_summary=summary,
                       evidence_fields=evidence_fields, test_only=item['test_only'])
        if item['log_path'] is not None:
            log_path = item['log_path']
            try:
                log, log_mtime = _file_metadata(log_path, MAX_LOG_BYTES)
                payload['log'] = log
                evidence.append(str(log_path))
                if status == 'working' and current.timestamp() - log_mtime > item['stale_seconds']:
                    observations.append(_observation('experiment_log_stale', key, log_path,
                        '指定日志的最近修改时间已超过配置间隔；需核对进程和进展，不能仅据此诊断失败。'))
            except (OSError, ValueError, TypeError):
                payload['log'] = dict(reference=str(log_path), available=False)
                observations.append(_observation('experiment_log_unavailable', key, log_path,
                    '配置的日志缺失、过大或读取期间变化；保留记录状态，需核对日志覆盖。'))
        if status == 'working' and item['log_path'] is None:
            observations.append(_observation('experiment_liveness_unverified', key, path,
                '执行中记录没有配置日志；本次不能验证进程存活或持续进展。', severity='info'))
            try:
                stale_record = current.timestamp() - path.stat().st_mtime > item['stale_seconds']
            except OSError:
                stale_record = False
            if stale_record:
                observations.append(_observation('experiment_record_stale', key, path,
                    '执行中记录的最近修改时间已超过配置间隔；需核对实际进程，文件时间不代表实验发生日期或失败。'))
        if summary in ('unrecognized', 'completion_unverified', 'reported_failed'):
            observations.append(_observation('experiment_' + summary, key, path, action))
        result['tasks'].append(dict(source='experiment', external_id=key, title=item['title'],
            kind='experiment', status=status, evidence=evidence, next_action=action,
            test_only=item['test_only'], scope='read_only'))
        fingerprint = hashlib.sha256(_canonical(payload)).hexdigest()
        result['events'].append(dict(source='experiment', external_id=key + ':' + fingerprint,
                                     payload=payload, task_ref=key))
    return result
