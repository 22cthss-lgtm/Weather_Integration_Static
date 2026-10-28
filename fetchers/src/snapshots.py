"""Strict public JSON snapshots. Manifests contain hashes, never private reports."""

from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from uuid import uuid4

from .publication import GROUPS, validate_image, atomic_write_json
from .rainfall_rankings import METRICS

IMAGE_TYPES = ('sst', 'temperature', 'weather_chart', '850hpa', 'tchp',
               *GROUPS, 'radar', 'satellite', 'rainfall')
REQUIRED = tuple(f'images/{kind}/latest.json' for kind in IMAGE_TYPES) + (
    'images/rainfall/daily/latest.json', 'rainfall/rankings/latest.json')
IMAGE_FIELDS = {'image_type', 'source', 'title', 'image_url', 'source_url', 'image_time', 'fetched_at'}


def allowed_path(name):
    return name in REQUIRED or bool(re.fullmatch(
        r'images/(radar|satellite|rainfall)/history/\d{4}-\d{2}-\d{2}\.json', name))


def install_directory(staged, destination):
    for attempt in range(4):
        try:
            os.replace(staged, destination)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(.02 * (2 ** attempt))


def exact(data, fields):
    if not isinstance(data, dict) or set(data) != set(fields):
        raise ValueError('Unexpected public resource fields')


def instant(value, utc=False):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None or (utc and parsed.utcoffset() != timedelta(0)):
        raise ValueError('Invalid timezone')
    return parsed


def image(kind, data, extra=()):
    exact(data, IMAGE_FIELDS | set(extra))
    validate_image(kind, data)
    if kind in ('radar', 'satellite', 'rainfall'):
        stamp = instant(data['image_time'])
        step = 30 if kind == 'rainfall' else 10
        if stamp.utcoffset() != timedelta(hours=8) or stamp.minute % step or stamp.second or stamp.microsecond:
            raise ValueError('Invalid current-image time grid')
        if kind == 'rainfall' and stamp.hour == 0 and stamp.minute == 0 and not extra:
            raise ValueError('Rainfall midnight is a daily product')
    # No request credentials in the only public URL fields. Whitelisted keys
    # below prevent arbitrary source payloads/private status being exported.
    from urllib.parse import urlsplit, parse_qsl
    for field in ('image_url', 'source_url'):
        url = urlsplit(data[field])
        if url.username or url.password or any(k.lower() in ('authorization', 'api_key', 'key', 'token')
                                              for k, _ in parse_qsl(url.query)):
            raise ValueError('Credentials are not public snapshot data')


def validate_resource(path, data):
    """Validate exact schemas as well as path, dates, ordering and timezones."""
    try:
        if path in (f'images/{kind}/latest.json' for kind in IMAGE_TYPES):
            kind = path.split('/')[1]
            if kind in GROUPS:
                exact(data, IMAGE_FIELDS | {'images'})
                if [i['image_type'] for i in data['images']] != list(GROUPS[kind]):
                    raise ValueError('Invalid group ordering')
                for child in data['images']:
                    image(child['image_type'], child)
                first = dict(data['images'][0], image_type=kind, images=data['images'])
                if data != first:
                    raise ValueError('Invalid representative image')
            else:
                image(kind, data)
        elif re.fullmatch(r'images/(radar|satellite|rainfall)/history/\d{4}-\d{2}-\d{2}\.json', path):
            kind, day = path.split('/')[1], Path(path).stem
            date.fromisoformat(day)
            exact(data, {'image_type', 'date', 'timezone', 'updated_at', 'range_start', 'range_end',
                         'expected_count', 'complete', 'missing', 'failed', 'items'})
            if data['image_type'] != kind or data['date'] != day or data['timezone'] != 'Asia/Taipei':
                raise ValueError('History path/date mismatch')
            instant(data['updated_at'], utc=True)
            start, end = instant(data['range_start']), instant(data['range_end'])
            step = 30 if kind == 'rainfall' else 10
            expected_start = f'{day}T00:{"30" if kind == "rainfall" else "00"}:00+08:00'
            if (start.isoformat() != expected_start or end < start or end.date().isoformat() != day
                    or end.utcoffset() != timedelta(hours=8) or end.minute % step or end.second or end.microsecond):
                raise ValueError('Invalid history range')
            expected = int((end - start).total_seconds() / (step * 60)) + 1
            slots = {(start + timedelta(minutes=i * step)).isoformat() for i in range(expected)}
            if type(data['expected_count']) is not int or data['expected_count'] != expected:
                raise ValueError('Invalid history expected count')
            times = []
            for item in data['items']:
                image(kind, item)
                stamp = instant(item['image_time'])
                if stamp.utcoffset() != timedelta(hours=8) or item['image_time'] not in slots:
                    raise ValueError('History item outside time grid')
                times.append(item['image_time'])
            missing, failed = data['missing'], data['failed']
            if not times or times != sorted(set(times)):
                raise ValueError('Invalid history ordering')
            if not isinstance(missing, list) or not isinstance(failed, list) or any(t not in slots for t in missing + failed):
                raise ValueError('Invalid history gaps')
            if len(set(missing)) != len(missing) or len(set(failed)) != len(failed):
                raise ValueError('Duplicate history gaps')
            if set(times) | set(missing) | set(failed) != slots or set(missing) & set(failed):
                raise ValueError('History inventory does not account for every slot')
            if type(data['complete']) is not bool or data['complete'] != (not missing and not failed):
                raise ValueError('Invalid history completeness')
        elif path == 'images/rainfall/daily/latest.json':
            exact(data, {'date', 'timezone', 'fetched_at', 'items'})
            day = date.fromisoformat(data['date'])
            instant(data['fetched_at'], utc=True)
            if data['timezone'] != 'Asia/Taipei' or len(data['items']) != 3:
                raise ValueError('Invalid daily rainfall')
            for offset, item in enumerate(data['items']):
                image('rainfall', item, ('label', 'represented_date', 'accumulation_start', 'accumulation_end'))
                represented = day - timedelta(days=offset)
                start, end = instant(item['accumulation_start']), instant(item['accumulation_end'])
                if (item['label'] != ('今日', '昨日', '前日')[offset]
                        or item['represented_date'] != represented.isoformat()
                        or start.isoformat() != f'{represented}T00:00:00+08:00'
                        or item['image_time'] != item['accumulation_end']
                        or not start < end <= start + timedelta(days=1)
                        or (offset and end != start + timedelta(days=1))):
                    raise ValueError('Invalid rainfall accumulation period')
        elif path == 'rainfall/rankings/latest.json':
            exact(data, {'source', 'dataset_id', 'fetched_at', 'rankings'})
            fetched = instant(data['fetched_at'], utc=True)
            if data['source'] != 'CWA' or data['dataset_id'] != 'O-A0002-001' or set(data['rankings']) != set(METRICS):
                raise ValueError('Invalid ranking source/metrics')
            for metric, ranking in data['rankings'].items():
                exact(ranking, {'metric', 'fetched_at', 'unit', 'items'})
                if ranking['metric'] != metric or ranking['unit'] != 'mm' or ranking['fetched_at'] != data['fetched_at']:
                    raise ValueError('Invalid ranking metadata')
                if not 1 <= len(ranking['items']) <= 10:
                    raise ValueError('Invalid ranking size')
                values, stations = [], []
                for rank, item in enumerate(ranking['items'], 1):
                    exact(item, {'rank', 'station_id', 'station_name', 'county', 'town', 'rainfall', 'observed_at', 'fetched_at'})
                    value = item['rainfall']
                    if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                            or type(item['rank']) is not int or item['rank'] != rank
                            or any(not isinstance(item[f], str) for f in ('station_id', 'station_name', 'county', 'town'))
                            or not item['station_id']
                            or item['fetched_at'] != data['fetched_at'] or instant(item['observed_at']) > fetched):
                        raise ValueError('Invalid ranking observation')
                    values.append(value)
                    stations.append(item['station_id'])
                if values != sorted(values, reverse=True) or len(set(stations)) != len(stations):
                    raise ValueError('Invalid ranking order')
        else:
            raise ValueError('Unapproved public resource path')
    except (KeyError, TypeError, RuntimeError, OverflowError, AttributeError) as exc:
        raise ValueError('Invalid public JSON resource') from None
    return data


def read_resources(root, *, strict=True):
    root = Path(root)
    valid, invalid = {}, []
    if root.is_symlink():
        raise ValueError('Snapshot data root cannot be a symlink')
    if not root.exists():
        return valid, invalid
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks are not permitted in snapshots')
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        try:
            if not allowed_path(name):
                raise ValueError('Unapproved public resource path')
            content = path.read_bytes()
            validate_resource(name, json.loads(content))
            valid[name] = content
        except (ValueError, OSError):
            if strict:
                raise ValueError('Invalid snapshot resource') from None
            invalid.append(name)
    return valid, invalid


def export_snapshot(data_root, destination, *, snapshot_id=None):
    destination = Path(destination)
    data_root = Path(data_root)
    if destination.resolve().is_relative_to(data_root.resolve()) or data_root.resolve().is_relative_to(destination.resolve()):
        raise ValueError('Snapshot and source directories must not overlap')
    resources, _ = read_resources(data_root)
    if not resources or any(path not in resources for path in REQUIRED):
        raise ValueError('Snapshot is missing required public resources')
    if destination.exists():
        raise ValueError('Snapshot destinations must be new immutable directories')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / 'snapshot'
        staged.mkdir()
        for name, content in resources.items():
            p = staged / 'data' / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        manifest = {'schema_version': 1, 'snapshot_id': snapshot_id or uuid4().hex,
                    'files': {name: hashlib.sha256(content).hexdigest() for name, content in resources.items()}}
        atomic_write_json(manifest, staged / 'manifest.json')
        install_directory(staged, destination)
    return manifest


def restore_snapshot(snapshot, destination):
    snapshot, destination = Path(snapshot), Path(destination)
    if destination.resolve().is_relative_to(snapshot.resolve()) or snapshot.resolve().is_relative_to(destination.resolve()):
        raise ValueError('Snapshot and restore directories must not overlap')
    if snapshot.is_symlink() or (snapshot / 'data').is_symlink() or (snapshot / 'manifest.json').is_symlink():
        raise ValueError('Snapshot symlinks are not permitted')
    try:
        manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
        exact(manifest, {'schema_version', 'snapshot_id', 'files'})
        if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or not re.fullmatch('[0-9a-f]{32}', manifest['snapshot_id']):
            raise ValueError('Invalid snapshot manifest')
        resources, _ = read_resources(snapshot / 'data')
        hashes = {name: hashlib.sha256(content).hexdigest() for name, content in resources.items()}
        if hashes != manifest['files'] or any(p not in resources for p in REQUIRED):
            raise ValueError('Snapshot is corrupt or incomplete')
    except (OSError, TypeError):
        raise ValueError('Snapshot cannot be restored') from None
    if destination.exists():
        raise ValueError('Restore destination must not exist')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / 'data'
        shutil.copytree(snapshot / 'data', staged)
        copied, _ = read_resources(staged)
        if copied != resources:
            raise ValueError('Snapshot changed during restore')
        install_directory(staged, destination)
    return manifest
