"""Portable, expiring snapshot input for manual releases; no network or secrets."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import tempfile
from zipfile import ZipFile, BadZipFile, ZIP_DEFLATED

from .snapshots import REQUIRED, allowed_path, exact, instant, read_resources, restore_snapshot


def site_summary(data_root):
    resources, _ = read_resources(data_root)
    if any(name not in resources for name in REQUIRED):
        raise ValueError('Required website resources are missing')
    incomplete = {name for name, content in resources.items()
                  if '/history/' in name and not json.loads(content)['complete']}
    for kind in ('radar', 'satellite', 'rainfall'):
        latest = json.loads(resources[f'images/{kind}/latest.json'])
        history = f'images/{kind}/history/{latest["image_time"][:10]}.json'
        if history not in resources:
            raise ValueError('Latest image has no matching history inventory')
        if instant(json.loads(resources[history])['range_end']) < instant(latest['image_time']):
            incomplete.add(history)
    return {'json_files': len(resources), 'incomplete_history': sorted(incomplete)}


def pack_snapshot(snapshot, archive, *, valid_days=7, now=None):
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() != timedelta(0) or type(valid_days) is not int or not 1 <= valid_days <= 30:
        raise ValueError('Package validity must be 1..30 days in UTC')
    snapshot, archive = Path(snapshot), Path(archive)
    if archive.exists() or archive.resolve().is_relative_to(snapshot.resolve()):
        raise ValueError('Archive must be a new file outside the snapshot')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=archive.parent) as temporary:
        data = Path(temporary) / 'data'
        manifest = restore_snapshot(snapshot, data)
        summary = site_summary(data)
        transport = {'schema_version': 1, 'snapshot_id': manifest['snapshot_id'],
                     'created_at': now.isoformat(), 'expires_at': (now + timedelta(days=valid_days)).isoformat()}
        staged = Path(temporary) / 'input.zip'
        with ZipFile(staged, 'w', ZIP_DEFLATED) as output:
            output.writestr('manifest.json', json.dumps(manifest))
            output.writestr('transport.json', json.dumps(transport))
            for name in sorted(manifest['files']):
                output.write(data / name, 'data/' + name)
        # Exercise exactly the reader used by Actions before issuing a package.
        sha = hashlib.sha256(staged.read_bytes()).hexdigest()
        unpack_snapshot(staged, sha, Path(temporary) / 'check', now=now)
        staged.replace(archive)
    return dict(summary, snapshot_id=manifest['snapshot_id'], sha256=sha,
                expires_at=transport['expires_at'], archive=str(archive.resolve()))


def unpack_snapshot(archive, expected_sha256, destination, *, now=None):
    now = now or datetime.now(timezone.utc)
    archive, destination = Path(archive), Path(destination)
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256) or not archive.is_file():
        raise ValueError('Archive or SHA-256 is missing/invalid')
    if destination.exists() or archive.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Restore destination exists or archive is too large')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('Input archive checksum mismatch')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            root = Path(temporary) / 'snapshot'
            root.mkdir()
            with ZipFile(archive) as package:
                entries = package.infolist()
                names = [entry.filename for entry in entries]
                if (len(entries) > 10000 or len(set(names)) != len(names)
                        or not {'manifest.json', 'transport.json'} <= set(names)
                        or sum(entry.file_size for entry in entries) > 256 * 1024 * 1024):
                    raise ValueError('Invalid package inventory')
                for entry in entries:
                    name = entry.filename
                    if ('\\' in name or stat.S_ISLNK(entry.external_attr >> 16)
                            or entry.file_size > 8 * 1024 * 1024 or entry.flag_bits & 1
                            or not (name in ('manifest.json', 'transport.json')
                                    or name.startswith('data/') and allowed_path(name[5:]))):
                        raise ValueError('Unapproved package entry')
                    output = root / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(package.read(entry))
            transport = json.loads((root / 'transport.json').read_text(encoding='utf-8'))
            exact(transport, {'schema_version', 'snapshot_id', 'created_at', 'expires_at'})
            created, expires = instant(transport['created_at'], utc=True), instant(transport['expires_at'], utc=True)
            if (type(transport['schema_version']) is not int or transport['schema_version'] != 1
                    or not created <= now < expires or not timedelta(0) < expires - created <= timedelta(days=30)):
                raise ValueError('Input package expired or has invalid validity dates')
            manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
            if transport['snapshot_id'] != manifest.get('snapshot_id'):
                raise ValueError('Transport snapshot ID mismatch')
            # Validate cross-file website needs before installing any destination.
            summary = site_summary(root / 'data')
            restore_snapshot(root, destination)
            return dict(summary, snapshot_id=manifest['snapshot_id'], expires_at=transport['expires_at'],
                        files=manifest['files'])
    except (OSError, BadZipFile, KeyError, TypeError, RuntimeError):
        raise ValueError('Snapshot package could not be validated/restored') from None
