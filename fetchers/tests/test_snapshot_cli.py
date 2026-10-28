from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_snapshot


class SnapshotCliTests(unittest.TestCase):
    def test_corrupt_selected_snapshot_stops_before_fetch_and_records_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory)
            (base / 'bad').mkdir()
            (base / 'bad/manifest.json').write_text('{}')
            with patch('dotenv.load_dotenv'), patch('update_snapshot.update_image') as update, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = update_snapshot.main(['--previous-snapshot', str(base / 'bad'), '--store', str(base / 'store')])
            self.assertEqual(result, 1)
            update.assert_not_called()
            self.assertFalse((base / 'store/current.json').exists())
            self.assertTrue(list((base / 'store/reports').glob('failure-*.json')))

    def test_restore_explicit_location_and_next_run_uses_saved_snapshot(self):
        import shutil
        from src.snapshots import export_snapshot
        from src.snapshot_runner import current_snapshot
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory)
            shutil.copytree(source, base / 'seed')
            export_snapshot(base / 'seed', base / 'previous')
            def update(kind, output):
                p = output / kind / 'latest.json'
                data = json.loads(p.read_text(encoding='utf-8'))
                data['fetched_at'] = '2026-10-27T23:00:00+00:00'
                p.write_text(json.dumps(data), encoding='utf-8')
                return data
            logs = io.StringIO()
            with patch('dotenv.load_dotenv'), patch('update_snapshot.update_image', side_effect=update), \
                    redirect_stdout(logs), redirect_stderr(io.StringIO()):
                result = update_snapshot.main(['radar', '--previous-snapshot', str(base / 'previous'), '--store', str(base / 'store')])
            # Real seed history can already have known gaps. Exit 1 may report
            # those warnings while the newly validated snapshot is publishable.
            self.assertIn(result, (0, 1))
            self.assertTrue(json.loads(logs.getvalue())['publishable'])
            snapshot = current_snapshot(base / 'store')
            self.assertTrue((snapshot / 'manifest.json').exists())
            pointer_before = (base / 'store/current.json').read_bytes()
            with patch('dotenv.load_dotenv'), patch('update_snapshot.update_image', side_effect=RuntimeError('offline')), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = update_snapshot.main(['radar', '--store', str(base / 'store')])
            self.assertEqual(result, 1)
            self.assertEqual((base / 'store/current.json').read_bytes(), pointer_before)

    def test_default_public_seed_cannot_contain_private_store(self):
        with patch('dotenv.load_dotenv'), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                update_snapshot.main(['--store', str(update_snapshot.ROOT / 'frontend/public/data/private-store')])

    def test_direct_runner_rejects_overlapping_paths_before_writing(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                run_candidate(['radar'], root, root / 'private-store', lambda *a: {})
            self.assertFalse((root / 'private-store').exists())
