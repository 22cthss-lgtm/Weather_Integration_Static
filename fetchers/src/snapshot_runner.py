"""Build isolated candidates and promote only complete, validated snapshots."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .http_client import http_scope
from .publication import atomic_write_json
from .snapshots import REQUIRED, read_resources, export_snapshot
from .update_runner import FileLock


def belongs(name, product):
    prefix = 'rainfall/rankings/' if product == 'rainfall_rankings' else f'images/{product}/'
    return name.startswith(prefix)


CURRENT_KINDS = ('radar', 'satellite', 'rainfall')
HISTORY_FILE = re.compile(r'images/(radar|satellite|rainfall)/history/(\d{4}-\d{2}-\d{2})\.json')


def _prune_past_history(candidate, today):
    """Remove day inventories other than Taipei ``today`` and each product's latest date.

    The latest image's own day stays, because the snapshot contract requires it
    (shortly after midnight the latest can still be yesterday 23:xx). Only exact
    ``images/{radar,satellite,rainfall}/history/YYYY-MM-DD.json`` paths are touched.
    """
    keep = {kind: {today.isoformat()} for kind in CURRENT_KINDS}
    for kind in CURRENT_KINDS:
        latest = candidate / 'images' / kind / 'latest.json'
        if latest.is_file():
            keep[kind].add(json.loads(latest.read_text(encoding='utf-8'))['image_time'][:10])
    pruned = []
    for kind in CURRENT_KINDS:
        folder = candidate / 'images' / kind / 'history'
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            name = path.relative_to(candidate).as_posix()
            match = HISTORY_FILE.fullmatch(name)
            if match and path.is_file() and match[2] not in keep[kind]:
                path.unlink()
                pruned.append(name)
    return pruned


def run_candidate(products, seed_data, store, update, *, allow_empty=False, history_today=None):
    """Never edit the seed/public directory; all mutations happen in a temp tree.

    With ``history_today`` (an Asia/Taipei date), past-day history inventories are
    removed after all updates; see ``_prune_past_history``. Default keeps them.
    """
    products = list(dict.fromkeys(products))
    if not products and not allow_empty:
        raise ValueError('At least one product is required')
    store = Path(store)
    seed_data = Path(seed_data)
    if store.resolve().is_relative_to(seed_data.resolve()) or seed_data.resolve().is_relative_to(store.resolve()):
        raise ValueError('Seed data and snapshot store must not overlap')
    store.mkdir(parents=True, exist_ok=True)
    with FileLock(store / 'snapshot.lock'), http_scope():
        before, invalid = read_resources(seed_data, strict=False)
        run_id = uuid4().hex
        started = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory(dir=store) as temporary:
            candidate = Path(temporary) / 'data'
            candidate.mkdir()
            for name, content in before.items():
                p = candidate / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
            products_report, invalid_outputs = {}, set()
            for product in products:
                # Service failures are isolated, including partially published
                # latest/history/daily resources. Do not serialize exceptions.
                try:
                    update(product, candidate / 'images')
                except Exception:
                    products_report[product] = 'failed'
                else:
                    products_report[product] = 'success'
                valid, bad = read_resources(candidate, strict=False)
                # A malformed write cannot destroy the validated fallback.
                for name in bad:
                    invalid_outputs.add(name)
                    p = candidate / name
                    if name in before:
                        p.write_bytes(before[name])
                    else:
                        p.unlink()
                # Updates may never delete a validated prior resource.
                for name, content in before.items():
                    if name not in valid and name not in bad:
                        p = candidate / name
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(content)
                        invalid_outputs.add(name)
            pruned = _prune_past_history(candidate, history_today) if history_today is not None else []
            after, _ = read_resources(candidate)
            expected = set(REQUIRED) | (set(before) - set(pruned)) | set(after)
            # Each current-image latest must have its corresponding day inventory.
            for kind in ('radar', 'satellite', 'rainfall'):
                latest = after.get(f'images/{kind}/latest.json')
                if latest:
                    day = json.loads(latest)['image_time'][:10]
                    expected.add(f'images/{kind}/history/{day}.json')
            resources = {}
            latest_times = {f'images/{kind}/history/{json.loads(after[f"images/{kind}/latest.json"])["image_time"][:10]}.json':
                            json.loads(after[f'images/{kind}/latest.json'])['image_time']
                            for kind in ('radar', 'satellite', 'rainfall') if f'images/{kind}/latest.json' in after}
            for name in sorted(expected):
                selected = [p for p in products if belongs(name, p)]
                attempted = bool(selected)
                exists = name in after
                changed = exists and before.get(name) != after[name]
                successful = changed and attempted and name not in invalid_outputs
                state = 'updated' if successful and exists else 'retained' if exists else 'no_data'
                data = json.loads(after[name]) if exists else {}
                history_lag = name in latest_times and exists and data['range_end'] < latest_times[name]
                if '/history/' in name and exists and (not data['complete'] or history_lag):
                    state = 'incomplete_history'
                failed = name in invalid_outputs or any(products_report[p] == 'failed' for p in selected)
                resources[name] = {
                    'state': state, 'updated': bool(successful and exists), 'attempted': attempted,
                    'error_code': 'invalid_output' if name in invalid_outputs else 'history_lag' if history_lag else 'product_incomplete' if failed else None,
                    # Original times remain facts from the data, separate from attempts.
                    'image_time': data.get('image_time'), 'fetched_at': data.get('fetched_at'),
                }
            complete = all(r['state'] != 'no_data' for r in resources.values())
            updated = sum(r['updated'] for r in resources.values())
            report = {
                'schema_version': 1, 'run_id': run_id, 'started_at': started,
                'finished_at': datetime.now(timezone.utc).isoformat(),
                'invalid_seed_count': len(invalid), 'products': products_report, 'resources': resources,
                'updated_count': updated, 'complete': complete, 'pruned_history': pruned,
                'publishable': complete and updated > 0, 'snapshot_id': None,
            }
            # Only report removals that actually ship; an unpublished candidate is discarded.
            report['pruned_history'] = pruned if report['publishable'] else []
            if report['publishable']:
                snapshot = store / 'snapshots' / run_id
                manifest = export_snapshot(candidate, snapshot, snapshot_id=run_id)
                report['snapshot_id'] = run_id
                report['manifest_id'] = manifest['snapshot_id']
            # The report is private. Report/save failure never changes current.
            atomic_write_json(report, store / 'reports' / f'{run_id}.json')
            if report['publishable']:
                atomic_write_json({'snapshot_id': run_id}, store / 'current.json')
            return report


def current_snapshot(store):
    store = Path(store)
    pointer = store / 'current.json'
    if not pointer.exists():
        return None
    import re
    try:
        data = json.loads(pointer.read_text(encoding='utf-8'))
        snapshot_id = data['snapshot_id']
        if set(data) != {'snapshot_id'} or not re.fullmatch('[0-9a-f]{32}', snapshot_id):
            raise ValueError('Invalid snapshot pointer')
    except (KeyError, TypeError, OSError):
        raise ValueError('Invalid snapshot pointer') from None
    return store / 'snapshots' / snapshot_id
