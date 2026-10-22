"""Current-day inventories and official CWA single-day rainfall products."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from .publication import atomic_write_json, validate_image
from .services.cwa_service import CWAService

CURRENT_PRODUCTS = ('radar', 'satellite', 'rainfall')


def publish_current_history(service, latest, output_root, now=None):
    now = (now or datetime.now(service.satellite_timezone)).astimezone(service.satellite_timezone)
    end = datetime.fromisoformat(latest.image_time).astimezone(service.satellite_timezone)
    if end.date() != now.date():
        return None  # Keep previous latest for the UI, never scan yesterday as today.
    if end > now:
        raise RuntimeError('CWA product time is in the future')
    kind = latest.image_type
    delay = getattr(service, f'{kind}_publish_delay_minutes')
    slots = getattr(service, f'{kind}_time_slots_for_date')(
        end.date(), now=end + timedelta(minutes=delay))
    slots = [slot for slot in slots if slot <= end]
    if not slots:
        raise RuntimeError('No publishable current-day slots')
    build_url = getattr(service, f'build_{kind}_image_url')

    def probe(slot):
        url = build_url(slot)
        try:
            if not service.check_image_url(url):
                return slot, None, 'missing'
            item = asdict(service.build_payload(kind, f'CWA {kind.title()} {slot:%Y-%m-%d %H:%M}',
                         url, getattr(service, f'{kind}_source_url'), slot.isoformat()))
            validate_image(kind, item)
            return slot, item, None
        except Exception:
            return slot, None, 'failed'

    # Independent URL checks only; merge and write once on the calling thread.
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(probe, slots))
    successes = [item for _, item, status in results if status is None]
    if not successes:
        raise RuntimeError(f'{kind}: no verified slots; previous history preserved')
    output = Path(output_root) / kind / 'history' / f'{end.date()}.json'
    existing = []
    if output.exists():
        previous = json.loads(output.read_text(encoding='utf-8'))
        if previous.get('date') != end.date().isoformat() or previous.get('image_type') != kind:
            raise RuntimeError('Existing history date/type is inconsistent')
        existing = previous['items']
        for item in existing:
            validate_image(kind, item)
            if datetime.fromisoformat(item['image_time']).astimezone(service.satellite_timezone).date() != end.date():
                raise RuntimeError('Existing history has a wrong-day item')
    merged = {item['image_time']: item for item in existing}
    # Preserve the original successful metadata for already-known slots.
    for item in successes:
        merged.setdefault(item['image_time'], item)
    missing = [slot.isoformat() for slot, _, status in results if status == 'missing']
    failed = [slot.isoformat() for slot, _, status in results if status == 'failed']
    data = {
        'image_type': kind, 'date': end.date().isoformat(), 'timezone': 'Asia/Taipei',
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'range_start': slots[0].isoformat(), 'range_end': end.isoformat(),
        'expected_count': len(slots), 'complete': not missing and not failed,
        'missing': missing, 'failed': failed,
        'items': sorted(merged.values(), key=lambda item: item['image_time']),
    }
    return atomic_write_json(data, output)


def update_daily_rainfall(service, output_root, now=None):
    now = (now or datetime.now(service.satellite_timezone)).astimezone(service.satellite_timezone)
    script = service.fetch_rainfall_day_script()
    # Only the original normal-colour tab, using the official first entry in
    # each Day group. Do not evaluate upstream JavaScript or guess a filename.
    tab = re.search(r"['\"]Tab0['\"]\s*:\s*\{(?P<body>.*?)(?=['\"]Tab1['\"]|\Z)", script, re.S)
    if tab is None:
        raise RuntimeError('CWA daily rainfall normal-colour tab missing')
    items = []
    for offset, label in enumerate(('今日', '昨日', '前日')):
        match = re.search(r"['\"]Day" + str(offset) + r"['\"]\s*:\s*\{\s*0\s*:\s*\{\s*['\"]img['\"]\s*:\s*['\"](?P<stamp>\d{4}-\d{2}-\d{2}_\d{4})\.QZJ8['\"]", tab['body'])
        if match is None:
            raise RuntimeError('CWA daily rainfall product missing')
        image_time = datetime.strptime(match['stamp'], '%Y-%m-%d_%H%M').replace(tzinfo=service.satellite_timezone)
        represented_date = now.date() - timedelta(days=offset)
        start = datetime.combine(represented_date, datetime.min.time(), tzinfo=service.satellite_timezone)
        if offset == 0:
            if image_time.date() != represented_date or image_time <= start or image_time > now:
                raise RuntimeError('CWA today rainfall product has an inconsistent time')
        elif image_time != start + timedelta(days=1):
            raise RuntimeError('CWA completed daily rainfall product is not its midnight endpoint')
        url = f'{service.rainfall_image_prefix}/{match["stamp"]}.QZJ8.jpg'
        if not service.check_image_url(url):
            raise RuntimeError('CWA daily rainfall image missing')
        item = asdict(service.build_payload('rainfall', f'CWA {label}單日累積雨量', url,
                     service.rainfall_source_url, image_time.isoformat()))
        validate_image('rainfall', item)
        item.update(label=label, represented_date=represented_date.isoformat(),
                    accumulation_start=start.isoformat(), accumulation_end=image_time.isoformat())
        items.append(item)
    return atomic_write_json({'date': now.date().isoformat(), 'timezone': 'Asia/Taipei',
                              'fetched_at': datetime.now(timezone.utc).isoformat(), 'items': items},
                             Path(output_root) / 'rainfall/daily/latest.json')


def _update_latest_and_history(kind, output_root):
    from .publication import publish_image
    service = CWAService()
    items = list(getattr(service, f'fetch_{kind}')())
    if len(items) != 1:
        raise RuntimeError(f'{kind}: latest source unavailable; previous JSON preserved')
    latest = items[0]
    validate_image(kind, asdict(latest))
    time = datetime.fromisoformat(latest.image_time).astimezone(service.satellite_timezone)
    if time > datetime.now(service.satellite_timezone):
        raise RuntimeError('CWA latest image time is in the future')
    if time.minute % (30 if kind == 'rainfall' else 10) or time.second:
        raise RuntimeError('CWA latest image is not on the expected time grid')
    if kind == 'rainfall' and time.hour == 0 and time.minute == 0:
        raise RuntimeError('Rainfall midnight image is a completed daily product, not today history')
    if not service.check_image_url(latest.image_url):
        raise RuntimeError('CWA latest image unavailable')
    output = Path(output_root) / kind / 'latest.json'
    if output.exists():
        previous = json.loads(output.read_text(encoding='utf-8'))
        validate_image(kind, previous)
        if datetime.fromisoformat(previous['image_time']) > time:
            # Upstream may briefly lag; never regress the visible latest product.
            from .services.base import ImagePayload
            latest = ImagePayload(**previous)
    publish_image(kind, [latest], output)
    errors = []
    try:
        history = publish_current_history(service, latest, output_root)
        if history and history['failed']:
            errors.append('some current-day source requests failed')
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        raise RuntimeError('; '.join(errors))
    return asdict(latest)


def update_current_product(kind, output_root):
    errors = []
    data = None
    try:
        data = _update_latest_and_history(kind, output_root)
    except Exception as exc:
        errors.append(str(exc))
    # Daily rain is a separate successful resource, even if latest/history fails.
    if kind == 'rainfall':
        try:
            update_daily_rainfall(CWAService(), output_root)
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError('; '.join(errors))
    return data
