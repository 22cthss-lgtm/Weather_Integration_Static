import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class VersionedPackageTests(unittest.TestCase):
    def test_versioned_roundtrip_has_content_identity_and_independent_transport_expiry(self):
        from datetime import datetime, timezone, timedelta
        from src.content_versions import content_metadata
        from src.pages_package import pack_snapshot, unpack_snapshot
        from src.snapshots import export_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory)
            data = Path(__file__).resolve().parents[2] / 'frontend/public/data'
            export_snapshot(data, base / 'snapshot')
            now = datetime(2026, 10, 29, tzinfo=timezone.utc)
            content = content_metadata(data, {}, '2026-10-20T00:00:00+00:00')
            result = pack_snapshot(base / 'snapshot', base / 'data.zip', valid_days=7, now=now, content=content)
            restored = unpack_snapshot(base / 'data.zip', result['sha256'], base / 'restored', now=now)
            self.assertEqual(restored['content_id'], content['content_id'])
            self.assertEqual(restored['content_created_at'], content['content_created_at'])
            self.assertEqual(restored['content'], content)
            with self.assertRaises(ValueError):
                unpack_snapshot(base / 'data.zip', result['sha256'], base / 'expired', now=now+timedelta(days=8))

    def test_modified_content_metadata_fails_even_with_correct_outer_hash(self):
        from src.pages_package import pack_snapshot, unpack_snapshot
        from src.content_versions import content_metadata
        from src.snapshots import export_snapshot
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory)
            data = Path(__file__).resolve().parents[2] / 'frontend/public/data'
            export_snapshot(data, base / 'snapshot')
            content = content_metadata(data, {}, '2026-10-20T00:00:00+00:00')
            pack_snapshot(base / 'snapshot', base / 'original.zip', valid_days=7, content=content)
            with ZipFile(base / 'original.zip') as original, ZipFile(base / 'bad.zip', 'w') as bad:
                for name in original.namelist():
                    payload = original.read(name)
                    if name == 'content.json':
                        changed = json.loads(payload)
                        changed['content_id'] = '0' * 64
                        payload = json.dumps(changed)
                    bad.writestr(name, payload)
            sha = hashlib.sha256((base / 'bad.zip').read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                unpack_snapshot(base / 'bad.zip', sha, base / 'rejected')
