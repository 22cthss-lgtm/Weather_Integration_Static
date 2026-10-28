from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PagesPackageTests(unittest.TestCase):
    def test_summary_warns_when_latest_is_ahead_of_history(self):
        from datetime import datetime, timedelta
        from src.pages_package import site_summary
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            snapshot = self.snapshot(base)
            latest_path = snapshot / 'data/images/radar/latest.json'
            latest = json.loads(latest_path.read_text(encoding='utf-8'))
            name = 'images/radar/history/' + latest['image_time'][:10] + '.json'
            history = json.loads((snapshot / 'data' / name).read_text(encoding='utf-8'))
            latest['image_time'] = (datetime.fromisoformat(history['range_end']) + timedelta(minutes=10)).isoformat()
            latest_path.write_text(json.dumps(latest), encoding='utf-8')
            self.assertIn(name, site_summary(snapshot / 'data')['incomplete_history'])

    def test_unsafe_entries_duplicates_symlinks_and_private_files_are_rejected(self):
        import stat
        import warnings
        from zipfile import ZipInfo
        from src.pages_package import pack_snapshot, unpack_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            original = base / 'original.zip'
            pack_snapshot(self.snapshot(base), original)
            for index, name in enumerate(('private/status.json', '/absolute', 'data/images/../escape',
                                          'data\\images\\escape', 'manifest.json', 'data/images/radar/history/2020-01-01.json')):
                target = base / f'bad-{index}.zip'
                target.write_bytes(original.read_bytes())
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with ZipFile(target, 'a') as package:
                        if index == 5:
                            entry = ZipInfo(name)
                            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                            package.writestr(entry, 'target')
                        else:
                            package.writestr(name, '{}')
                with self.assertRaises(ValueError):
                    unpack_snapshot(target, hashlib.sha256(target.read_bytes()).hexdigest(), base / f'output-{index}')
                self.assertFalse((base / f'output-{index}').exists())

    def snapshot(self, base):
        from src.snapshots import export_snapshot
        export_snapshot(Path(__file__).resolve().parents[2] / 'frontend/public/data', base / 'snapshot')
        return base / 'snapshot'

    def test_roundtrip_verified_explicit_snapshot_and_expiration(self):
        from src.pages_package import pack_snapshot, unpack_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            now = datetime(2026, 10, 28, tzinfo=timezone.utc)
            archive = base / 'input.zip'
            result = pack_snapshot(self.snapshot(base), archive, now=now)
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(result['sha256'], sha)
            unpack_snapshot(archive, sha, base / 'restored', now=now)
            self.assertTrue((base / 'restored/images/radar/latest.json').exists())
            with self.assertRaises(ValueError):
                unpack_snapshot(archive, sha, base / 'expired', now=now + timedelta(days=7))
            self.assertFalse((base / 'expired').exists())

    def test_corruption_missing_and_unknown_files_fail_before_destination_write(self):
        from src.pages_package import pack_snapshot, unpack_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            archive = base / 'input.zip'
            result = pack_snapshot(self.snapshot(base), archive)
            with self.assertRaises(ValueError):
                unpack_snapshot(archive, '0' * 64, base / 'bad-hash')
            with ZipFile(archive, 'a') as z:
                z.writestr('../escape', 'bad')
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                unpack_snapshot(archive, sha, base / 'unsafe')
            self.assertFalse((base / 'unsafe').exists())
            with self.assertRaises(ValueError):
                unpack_snapshot(base / 'missing.zip', result['sha256'], base / 'missing')

    def test_incomplete_current_history_path_cannot_be_packed(self):
        from src.pages_package import pack_snapshot
        from src.publication import atomic_write_json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            snapshot = self.snapshot(base)
            manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
            radar = json.loads((snapshot / 'data/images/radar/latest.json').read_text(encoding='utf-8'))
            name = 'images/radar/history/' + radar['image_time'][:10] + '.json'
            (snapshot / 'data' / name).unlink()
            del manifest['files'][name]
            atomic_write_json(manifest, snapshot / 'manifest.json')
            with self.assertRaises(ValueError):
                pack_snapshot(snapshot, base / 'missing-history.zip')
