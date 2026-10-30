"""Pure, JSON-safe due selection and persisted successful-check/retry state.

All instants are timezone-aware and serialized in UTC. The caller owns state
storage, artifact age policy and source operations; no source timestamps imply
a successful check.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path

UTC = timezone.utc
TAIPEI = timezone(timedelta(hours=8), 'Asia/Taipei')
FAST = frozenset(('radar', 'satellite', 'rainfall', 'rainfall_rankings'))
FAST_RETRY = (600, 1200, 2400, 3600)
SLOW_RETRY = (1800, 3600, 7200, 14400, 21600)
SAFE_ERRORS = frozenset(('source_error', 'timeout', 'http_error', 'parse_error',
                         'validation_error', 'write_error', 'network_error'))
TASK_FIELDS = frozenset(('last_attempt_at', 'last_successful_check_at',
    'next_due_at', 'next_retry_at', 'consecutive_failures',
    'completed_occurrence', 'retry_occurrence', 'error_code'))


def _instant(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('An aware UTC-compatible instant is required')
    return value.astimezone(UTC)


def _stamp(value):
    return _instant(value).isoformat().replace('+00:00', 'Z')


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _validate_config(config):
    if config.get('mode') == 'interval':
        if not _positive(config.get('interval_seconds')):
            raise ValueError('interval_seconds must be positive')
    elif config.get('mode') == 'fixed':
        clock = config.get('time')
        if config.get('timezone') != 'Asia/Taipei' or not isinstance(clock, str):
            raise ValueError('Fixed times require Asia/Taipei and HH:MM')
        try:
            parsed = datetime.strptime(clock, '%H:%M')
        except ValueError as exc:
            raise ValueError('Fixed times require HH:MM') from exc
        if parsed.strftime('%H:%M') != clock:
            raise ValueError('Fixed times require HH:MM')
    else:
        raise ValueError('Unknown schedule mode')
    delays = config.get('retry_delays_seconds')
    if not isinstance(delays, (list, tuple)) or not delays or not all(_positive(x) for x in delays):
        raise ValueError('retry_delays_seconds must be explicit and positive')


def _retry_at(config, task):
    """Recompute from attempt and policy; never trust cached retry instants."""
    count = task.get('consecutive_failures', 0)
    attempted = task.get('last_attempt_at')
    if type(count) is not int or count <= 0 or attempted is None:
        return None
    delays = config['retry_delays_seconds']
    return _instant(attempted) + timedelta(seconds=delays[min(count - 1, len(delays) - 1)])


def _valid_schedule_cache(config, task):
    retry = _retry_at(config, task)
    if task['next_retry_at'] != (None if retry is None else _stamp(retry)):
        return False
    last = task['last_successful_check_at']
    due = (_stamp(_instant(last) + timedelta(seconds=config['interval_seconds']))
           if last is not None and config['mode'] == 'interval' else None)
    return task['next_due_at'] == due


def default_tasks():
    """Return fresh copies of the confirmed 13 interval schedules."""
    policy = Path(__file__).resolve().parents[1] / 'policies' / 'due-intervals.json'
    return json.loads(policy.read_text(encoding='utf-8'))['tasks']


def new_state(content_id, now, task_config=None):
    """Create an all-due state; a missing state never assumes source success."""
    if not isinstance(content_id, str) or not content_id:
        raise ValueError('content_id is required')
    config = default_tasks() if task_config is None else task_config
    for task in config.values():
        _validate_config(task)
    return {'schema_version': 1, 'content_id': content_id, 'saved_at': _stamp(now),
        'tasks': {kind: {'last_attempt_at': None, 'last_successful_check_at': None,
            'next_due_at': None, 'next_retry_at': None, 'consecutive_failures': 0,
            'completed_occurrence': None, 'retry_occurrence': None,
            'error_code': None} for kind in config}}


def _valid_task(task, now):
    if not isinstance(task, dict) or set(task) != TASK_FIELDS:
        return False
    count = task['consecutive_failures']
    if type(count) is not int or count < 0:
        return False
    if task['error_code'] is not None and (not isinstance(task['error_code'], str) or task['error_code'] not in SAFE_ERRORS):
        return False
    for field in ('last_attempt_at', 'last_successful_check_at', 'next_due_at', 'next_retry_at'):
        if task[field] is not None:
            if not isinstance(task[field], str):
                return False
            parsed = _instant(task[field])
            if field.startswith('last_') and parsed > now:
                return False
    for field in ('completed_occurrence', 'retry_occurrence'):
        if task[field] is not None:
            if not isinstance(task[field], str) or date.fromisoformat(task[field]).isoformat() != task[field]:
                return False
            if date.fromisoformat(task[field]) > now.astimezone(TAIPEI).date():
                return False
    if count == 0 and (task['next_retry_at'] is not None or task['retry_occurrence'] is not None):
        return False
    if count > 0 and (task['next_retry_at'] is None or task['last_attempt_at'] is None):
        return False
    if task['next_due_at'] is not None and task['last_successful_check_at'] is None:
        return False
    return True


def restore_state(document, content_id, now, task_config, *, ttl_seconds):
    """Validate an untrusted state; on any fault reset all tasks safely to due.

    ttl_seconds is deliberately required. Warning is None, missing, corrupt,
    expired, or content_mismatch. Extra fields are rejected, never persisted.
    """
    now = _instant(now)
    if not _positive(ttl_seconds):
        raise ValueError('ttl_seconds must be explicit and positive')
    empty = new_state(content_id, now, task_config)
    if document is None:
        return empty, 'missing'
    try:
        if isinstance(document, (str, bytes)):
            document = json.loads(document)
        if not isinstance(document, dict) or set(document) != {'schema_version','content_id','saved_at','tasks'}:
            return empty, 'corrupt'
        if type(document['schema_version']) is not int or document['schema_version'] != 1:
            return empty, 'corrupt'
        if document['content_id'] != content_id:
            return empty, 'content_mismatch'
        if not isinstance(document['saved_at'], str):
            return empty, 'corrupt'
        saved = _instant(document['saved_at'])
        if saved > now:
            return empty, 'corrupt'
        if (now - saved).total_seconds() > ttl_seconds:
            return empty, 'expired'
        tasks = document['tasks']
        if not isinstance(tasks, dict) or set(tasks) != set(task_config):
            return empty, 'corrupt'
        if not all(_valid_task(task, now) for task in tasks.values()):
            return empty, 'corrupt'
        if not all(_valid_schedule_cache(task_config[kind], task) for kind, task in tasks.items()):
            return empty, 'corrupt'
        return deepcopy(document), None
    except (TypeError, ValueError, OverflowError):
        return empty, 'corrupt'


def is_due(task_config, task_state, now, fixed_policy=None):
    """Return (due, occurrence YYYY-MM-DD or None, stable reason code)."""
    now = _instant(now)
    _validate_config(task_config)
    occurrence = None
    if task_config['mode'] == 'fixed':
        if not isinstance(fixed_policy, dict) or type(fixed_policy.get('max_lateness_days')) is not int or fixed_policy['max_lateness_days'] < 0:
            raise ValueError('fixed_policy requires explicit nonnegative max_lateness_days')
        local = now.astimezone(TAIPEI)
        hour, minute = map(int, task_config['time'].split(':'))
        latest = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if latest > local:
            latest -= timedelta(days=1)
        day = latest.date()
        occurrence = day.isoformat()
        if (local.date() - day).days > fixed_policy['max_lateness_days']:
            return False, None, 'outside_window'
        if task_state.get('completed_occurrence') == occurrence:
            return False, occurrence, 'completed'
    retry = _retry_at(task_config, task_state)
    if task_config['mode'] == 'fixed' and task_state.get('retry_occurrence') != occurrence:
        # Backoff belongs to one occurrence; a newer slot supersedes it.
        retry = None
    if retry is not None and now < retry:
        return False, occurrence, 'retry_wait'
    if task_config['mode'] == 'fixed':
        return True, occurrence, 'fixed_due'
    if retry is not None:
        return True, None, 'retry_due'
    # Successful check time is authoritative even if a cached next_due differs.
    last = task_state.get('last_successful_check_at')
    if last is None:
        return True, None, 'never_checked'
    due_at = _instant(last) + timedelta(seconds=task_config['interval_seconds'])
    return now >= due_at, None, 'interval_due' if now >= due_at else 'interval_wait'


def record_result(state, kind, now, success, occurrence=None, error_code=None, *, task_config=None):
    """Mutate one task's safe result fields and return state (no raw errors)."""
    now = _instant(now)
    config = default_tasks() if task_config is None else task_config
    schedule = config[kind]
    _validate_config(schedule)
    if occurrence is not None and (not isinstance(occurrence, str) or date.fromisoformat(occurrence).isoformat() != occurrence):
        raise ValueError('occurrence requires YYYY-MM-DD')
    if schedule['mode'] == 'fixed' and occurrence is None:
        raise ValueError('fixed result requires occurrence')
    task = state['tasks'][kind]
    if not _valid_task(task, now):
        raise ValueError('Invalid task state')
    task['last_attempt_at'] = _stamp(now)
    if success:
        task.update(last_successful_check_at=_stamp(now), consecutive_failures=0,
                    next_retry_at=None, retry_occurrence=None, error_code=None)
        task['next_due_at'] = (_stamp(now + timedelta(seconds=schedule['interval_seconds']))
                               if schedule['mode'] == 'interval' else None)
        if occurrence is not None:
            task['completed_occurrence'] = occurrence
    else:
        count = (0 if schedule['mode'] == 'fixed' and task['retry_occurrence'] != occurrence
                 else task['consecutive_failures']) + 1
        delays = schedule['retry_delays_seconds']
        delay = delays[min(count-1, len(delays)-1)]
        task.update(consecutive_failures=count, next_retry_at=_stamp(now+timedelta(seconds=delay)),
                    retry_occurrence=occurrence, error_code=error_code if isinstance(error_code, str) and error_code in SAFE_ERRORS else 'source_error')
    state['saved_at'] = _stamp(now)
    return state
