import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SnapshotTests(unittest.TestCase):
    def test_transient_directory_promotion_error_is_retried(self):
        import os
        from unittest.mock import patch
        from src.snapshots import export_snapshot
        original = os.replace
        attempts = []
        def replace(source, target):
            if Path(target).name == 'snap':
                attempts.append(target)
                if len(attempts) == 1:
                    raise PermissionError('temporary reader')
            return original(source, target)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory)
            self.seed(base / 'data')
            with patch('src.snapshots.os.replace', side_effect=replace):
                export_snapshot(base / 'data', base / 'snap')
            self.assertEqual(len(attempts), 2)
            self.assertTrue((base / 'snap/manifest.json').exists())

    def test_empty_first_run_reports_absence_without_creating_public_json(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            base = Path(directory)
            def fail(*args): raise RuntimeError('offline')
            report = run_candidate(['radar', 'rainfall_rankings'], base / 'absent', base / 'store', fail)
            self.assertTrue(all(r['state'] == 'no_data' for r in report['resources'].values()))
            self.assertEqual(report['updated_count'], 0)
            self.assertFalse(report['publishable'])
            self.assertFalse((base / 'absent').exists())
            self.assertFalse((base / 'store/snapshots').exists())

    def test_malformed_ranking_and_history_are_rejected(self):
        import copy
        from src.snapshots import validate_resource
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
        ranking = json.loads((source / 'rainfall/rankings/latest.json').read_text(encoding='utf-8'))
        for field, bad in (('rank', True), ('station_name', {}), ('county', []), ('town', None)):
            data = copy.deepcopy(ranking)
            data['rankings']['10min']['items'][0][field] = bad
            with self.assertRaises(ValueError):
                validate_resource('rainfall/rankings/latest.json', data)
        p = next((source / 'images/radar/history').glob('*.json'))
        data = json.loads(p.read_text(encoding='utf-8'))
        data['range_end'] = data['range_end'][:14] + '11:00+08:00'
        with self.assertRaises(ValueError):
            validate_resource(p.relative_to(source).as_posix(), data)
    def test_unchanged_resources_are_not_successful_updates(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'old')
            report = run_candidate(['radar'], base / 'old', base / 'store', lambda *a: {})
            self.assertEqual(report['updated_count'], 0)
            self.assertFalse(report['publishable'])
            self.assertTrue(all(not r['updated'] for r in report['resources'].values()))

    def test_history_cannot_hide_unreported_slots(self):
        from src.snapshots import validate_resource
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
        p = next((source / 'images/radar/history').glob('*.json'))
        data = json.loads(p.read_text(encoding='utf-8'))
        data.update(items=data['items'][:1], missing=[], failed=[], complete=True)
        with self.assertRaises(ValueError):
            validate_resource(p.relative_to(source).as_posix(), data)

    def test_invalid_new_payload_restores_old_bytes_and_times(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'old')
            old = json.loads((base / 'old/images/radar/latest.json').read_text(encoding='utf-8'))
            def bad(kind, output):
                (output / kind / 'latest.json').write_text('{}')
                raise RuntimeError('secret')
            report = run_candidate(['radar'], base / 'old', base / 'store', bad)
            entry = report['resources']['images/radar/latest.json']
            self.assertEqual(entry['state'], 'retained')
            self.assertEqual(entry['image_time'], old['image_time'])
            self.assertEqual(entry['fetched_at'], old['fetched_at'])
            self.assertEqual(entry['error_code'], 'invalid_output')

    def test_history_partial_failure_remains_visible_and_preserves_old_items(self):
        from datetime import datetime, timedelta
        from src.snapshot_runner import run_candidate
        from src.snapshots import validate_resource
        for existing_gap in ('missing', 'failed'):
            with self.subTest(existing_gap=existing_gap), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
                base = Path(d)
                self.seed(base / 'old')
                history = next((base / 'old/images/radar/history').glob('*.json'))
                relative = history.relative_to(base / 'old')
                previous = json.loads(history.read_text(encoding='utf-8'))
                slot = previous['items'][0]['image_time']
                previous.update(complete=False,
                                missing=[t for t in previous['missing'] if t != slot],
                                failed=[t for t in previous['failed'] if t != slot])
                previous[existing_gap].append(slot)
                validate_resource(relative.as_posix(), previous)
                history.write_text(json.dumps(previous), encoding='utf-8')
                def partial(kind, output):
                    p = output / kind / 'history' / history.name
                    data = json.loads(p.read_text(encoding='utf-8'))
                    # A valid partial write must be both different and valid
                    # regardless of the selected snapshot's existing gaps.
                    data.update(complete=False,
                                missing=[t for t in data['missing'] if t != slot],
                                failed=sorted(set(data['failed']) | {slot}),
                                updated_at=(datetime.fromisoformat(data['updated_at']) + timedelta(seconds=1)).isoformat())
                    validate_resource(relative.as_posix(), data)
                    p.write_text(json.dumps(data), encoding='utf-8')
                    raise RuntimeError('source')
                report = run_candidate(['radar'], base / 'old', base / 'store', partial)
                entry = report['resources'][relative.as_posix()]
                self.assertEqual(entry['state'], 'incomplete_history')
                self.assertTrue(entry['updated'])
                self.assertEqual(entry['error_code'], 'product_incomplete')
                self.assertTrue(report['publishable'])
                published = base / 'store/snapshots' / report['snapshot_id'] / 'data' / relative
                self.assertEqual(json.loads(published.read_text(encoding='utf-8'))['items'], previous['items'])

    def test_snapshot_save_failure_leaves_previous_pointer(self):
        from unittest.mock import patch
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'old')
            (base / 'store').mkdir()
            pointer = base / 'store/current.json'
            pointer.write_text('{"snapshot_id":"previous"}')
            def update(kind, output):
                p = output / kind / 'latest.json'
                data = json.loads(p.read_text(encoding='utf-8'))
                data['fetched_at'] = '2026-10-27T23:00:00+00:00'
                p.write_text(json.dumps(data), encoding='utf-8')
            with patch('src.snapshot_runner.export_snapshot', side_effect=OSError('disk')):
                with self.assertRaises(OSError):
                    run_candidate(['radar'], base / 'old', base / 'store', update)
            self.assertEqual(pointer.read_text(), '{"snapshot_id":"previous"}')

    def test_latest_success_with_history_failure_marks_lag(self):
        from datetime import datetime, timedelta
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'old')
            def update(kind, output):
                p = output / kind / 'latest.json'
                data = json.loads(p.read_text(encoding='utf-8'))
                data['image_time'] = (datetime.fromisoformat(data['image_time']) + timedelta(minutes=10)).isoformat()
                p.write_text(json.dumps(data), encoding='utf-8')
                raise RuntimeError('history failed')
            report = run_candidate(['radar'], base / 'old', base / 'store', update)
            self.assertTrue(any(r['state'] == 'incomplete_history' and r['error_code'] == 'history_lag'
                                for r in report['resources'].values()))

    def test_private_fields_and_credentials_cannot_enter_public_snapshot(self):
        from src.snapshots import validate_resource
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data/images/radar/latest.json'
        data = json.loads(source.read_text(encoding='utf-8'))
        for invalid in (dict(data, api_key='secret'), dict(data, image_url='https://example.com/a?Authorization=secret')):
            with self.assertRaises(ValueError):
                validate_resource('images/radar/latest.json', invalid)

    def seed(self, root):
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
        import shutil
        shutil.copytree(source, root, dirs_exist_ok=True)

    def test_roundtrip_and_corruption_never_touch_destination(self):
        from src.snapshots import export_snapshot, restore_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'data')
            export_snapshot(base / 'data', base / 'snap')
            restore_snapshot(base / 'snap', base / 'restored')
            original = (base / 'restored/images/radar/latest.json').read_bytes()
            (base / 'snap/data/images/radar/latest.json').write_text('{}')
            with self.assertRaises(ValueError):
                restore_snapshot(base / 'snap', base / 'restored')
            self.assertEqual((base / 'restored/images/radar/latest.json').read_bytes(), original)

    def test_unknown_private_file_is_rejected(self):
        from src.snapshots import export_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'data')
            (base / 'data/private.json').write_text('{"key":"secret"}')
            with self.assertRaises(ValueError):
                export_snapshot(base / 'data', base / 'snap')
            self.assertFalse((base / 'snap').exists())

    def test_partial_failure_retains_bytes_and_classifies_every_resource(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'old')
            old = (base / 'old/images/radar/latest.json').read_bytes()
            def update(kind, output):
                if kind == 'radar': raise RuntimeError('private-secret')
                p = output / kind / 'latest.json'
                data = json.loads(p.read_text(encoding='utf-8'))
                data['fetched_at'] = '2026-10-27T23:00:00+00:00'
                p.write_text(json.dumps(data), encoding='utf-8')
                return data
            report = run_candidate(['radar', 'satellite'], base / 'old', base / 'store', update)
            self.assertTrue(report['publishable'])
            self.assertEqual(report['resources']['images/radar/latest.json']['state'], 'retained')
            self.assertEqual(report['resources']['images/satellite/latest.json']['state'], 'updated')
            self.assertNotIn('private-secret', json.dumps(report))
            snap = base / 'store/snapshots' / report['snapshot_id']
            self.assertEqual((snap / 'data/images/radar/latest.json').read_bytes(), old)

    def test_all_failed_does_not_advance_snapshot_pointer(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'old')
            def fail(*args): raise RuntimeError('offline')
            report = run_candidate(['radar'], base / 'old', base / 'store', fail)
            self.assertFalse(report['publishable'])
            self.assertFalse((base / 'store/current.json').exists())

    def test_first_run_and_corrupt_seed_are_reported_without_fake_json(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            (base / 'old/images/radar').mkdir(parents=True)
            (base / 'old/images/radar/latest.json').write_text('{}')
            def fail(*args): raise RuntimeError('offline')
            report = run_candidate(['radar'], base / 'old', base / 'store', fail)
            self.assertEqual(report['resources']['images/radar/latest.json']['state'], 'no_data')
            self.assertFalse(report['complete'])
            self.assertFalse((base / 'store/current.json').exists())

    def test_subresource_success_is_kept_when_product_reports_failure(self):
        from src.snapshot_runner import run_candidate
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            self.seed(base / 'old')
            def partial(kind, output):
                p = output / kind / 'latest.json'
                data = json.loads(p.read_text(encoding='utf-8'))
                data['fetched_at'] = '2026-10-27T23:00:00+00:00'
                p.write_text(json.dumps(data), encoding='utf-8')
                raise RuntimeError('history failed')
            report = run_candidate(['radar'], base / 'old', base / 'store', partial)
            self.assertEqual(report['resources']['images/radar/latest.json']['state'], 'updated')
            self.assertTrue(report['publishable'])
            self.assertEqual(report['products']['radar'], 'failed')
