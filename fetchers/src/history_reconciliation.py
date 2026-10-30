"""Bounded current-day reconciliation, isolated from latest-check scheduling.

Gap state contains only kind/date/HH:MM, counters, UTC instants and a fixed
classification vocabulary. The caller stores this state separately from data.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from threading import RLock

_CONTEXT = ContextVar('current_history_context', default=None)
KINDS = frozenset(('radar','satellite','rainfall'))
CLASSES = frozenset(('pending','missing','failed','success','official_missing','stopped'))
TAIPEI = timezone(timedelta(hours=8))


def _time(value):
    if isinstance(value,str): value = datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Aware instant required')
    return value.astimezone(timezone.utc)


def _stamp(value):
    return _time(value).isoformat().replace('+00:00','Z')


def _policy(policy):
    for key in ('interval_seconds','max_rechecks','max_slots_per_run'):
        if type(policy.get(key)) is not int or policy[key] < (0 if key == 'max_rechecks' else 1):
            raise ValueError('Explicit bounded history policy required')
    if policy.get('current_day_only') is not True:
        raise ValueError('Only current-day reconciliation is supported')
    return dict(policy)


def _safe_gaps(document, now=None):
    """Return bounded operational state, never a permanent history archive.

    Keep today's grid slots and yesterday's unresolved stopped slots only.
    Without a clock (schema validation), the newest supplied valid day anchors
    the same two-day bound. Public history JSON remains the historical record.
    """
    result = {}
    if not isinstance(document,dict): return result
    days_seen = []
    for kind in KINDS:
        days = document.get(kind)
        if not isinstance(days,dict): continue
        for day in days:
            try:
                parsed = date.fromisoformat(day)
                if parsed.isoformat() == day: days_seen.append(parsed)
            except (TypeError,ValueError): continue
    if not days_seen: return result
    anchor = _time(now).astimezone(TAIPEI).date() if now is not None else max(days_seen)
    yesterday = anchor-timedelta(days=1)
    for kind, days in document.items():
        if kind not in KINDS or not isinstance(days,dict): continue
        for day, slots in days.items():
            try:
                parsed = date.fromisoformat(day)
                if parsed.isoformat() != day or parsed not in (anchor,yesterday) or not isinstance(slots,dict): continue
            except (TypeError,ValueError): continue
            for slot, gap in slots.items():
                try:
                    clock = datetime.strptime(slot,'%H:%M')
                    if clock.strftime('%H:%M') != slot or not isinstance(gap,dict): continue
                    if clock.minute % (30 if kind == 'rainfall' else 10): continue
                    classification = gap.get('classification')
                    if not isinstance(classification,str) or classification not in CLASSES: continue
                    if parsed == yesterday and classification == 'success': continue
                    attempts = gap.get('attempts')
                    if type(attempts) is not int or not 0 <= attempts <= 100: continue
                    safe = {'classification':classification,'attempts':attempts}
                    for key in ('last_attempt_at','next_retry_at'):
                        value = gap.get(key)
                        safe[key] = None if value is None else _stamp(value)
                    if now is not None and safe['last_attempt_at'] is not None and _time(safe['last_attempt_at']) > _time(now):
                        continue
                    if parsed == yesterday:
                        safe.update(classification='stopped',next_retry_at=None)
                    result.setdefault(kind,{}).setdefault(day,{})[slot] = safe
                except (TypeError,ValueError,OverflowError): continue
    return result


def _eligible(gap, now, policy):
    if gap['classification'] in ('success','official_missing','stopped'): return False
    if gap['attempts'] >= 1 + policy['max_rechecks']: return False
    # Retry timestamps are a cache, not authority. Recompute from the actual
    # attempt so corrupt cached values cannot suppress or accelerate probes.
    attempted = gap.get('last_attempt_at')
    return attempted is None or _time(attempted) + timedelta(seconds=policy['interval_seconds']) <= now


def history_due(kind, gap_state, now, policy):
    """True only for known, unresolved current-day gaps that can be attempted."""
    now = _time(now)
    policy = _policy(policy)
    gaps = _safe_gaps(gap_state,now).get(kind,{}).get(now.astimezone(TAIPEI).date().isoformat(),{})
    return any(_eligible(gap,now,policy) for gap in gaps.values())


class HistoryContext:
    def __init__(self, policy, gap_state, now):
        self.policy = _policy(policy)
        self.now = _time(now)
        self.gaps = _safe_gaps(gap_state,self.now)
        self.outcomes = {}
        self._spent = {}
        self._lock = RLock()

    def outcome(self, kind, **values):
        with self._lock:
            self.outcomes.setdefault(kind,{}).update(values)

    def reconcile(self, kind, slots, existing, latest, probe):
        """Reuse validated inventory/latest; probe only budgeted eligible slots."""
        with self._lock:
            day = slots[0].date().isoformat()
            records = self.gaps.setdefault(kind,{}).setdefault(day,{})
            merged = {datetime.fromisoformat(item['image_time']).astimezone(TAIPEI).isoformat():item for item in existing}
            merged.setdefault(datetime.fromisoformat(latest['image_time']).astimezone(TAIPEI).isoformat(),latest)
            missing, failed = [], []
            for slot in slots:
                key = slot.strftime('%H:%M')
                stamp = slot.isoformat()
                gap = records.setdefault(key,{'classification':'pending','attempts':0,'last_attempt_at':None,'next_retry_at':None})
                if stamp in merged:
                    gap.update(classification='success',next_retry_at=None)
                    continue
                # Official CWA O-B0028_B0032 product schedule excludes 10:40
                # and 22:40; keep them publicly missing without repeat probes.
                if kind == 'satellite' and key in ('10:40','22:40'):
                    gap.update(classification='official_missing',next_retry_at=None)
                elif _eligible(gap,self.now,self.policy) and self._spent.get(kind,0) < self.policy['max_slots_per_run']:
                    self._spent[kind] = self._spent.get(kind,0) + 1
                    _, item, status = probe(slot)
                    gap.update(attempts=gap['attempts']+1,last_attempt_at=_stamp(self.now),
                               classification=status or 'success',
                               next_retry_at=None if status is None else _stamp(self.now+timedelta(seconds=self.policy['interval_seconds'])))
                    if item is not None:
                        merged[stamp] = item
                        continue
                # Pending means unobserved, so expose as failed (unknown),
                # never invent a source 404 in the public missing array.
                (missing if gap['classification'] in ('missing','official_missing') else failed).append(stamp)
            state = 'complete' if not missing and not failed else 'incomplete'
            self.outcome(kind,history_state=state)
            return list(merged.values()), missing, failed


@contextmanager
def history_scope(policy, gap_state, now):
    """Share one per-kind probe budget across all calls in a due batch."""
    context = HistoryContext(policy,gap_state,now)
    token = _CONTEXT.set(context)
    try:
        yield context
    finally:
        _CONTEXT.reset(token)


def current_history_context():
    return _CONTEXT.get()
