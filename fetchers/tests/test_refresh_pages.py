import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RefreshPagesTests(unittest.TestCase):
    def seed(self, root):
        from src.snapshots import export_snapshot
        from src.pages_package import pack_snapshot
        export_snapshot(Path(__file__).resolve().parents[2] / 'frontend/public/data', root / 'snapshot')
        return pack_snapshot(root / 'snapshot', root / 'input.zip')

    def test_policy_requires_explicit_retention_and_exact_source(self):
        from src.pages_refresh import validate_inputs
        valid = dict(mode='refresh', run_id='123', tag='', asset='', sha256='a' * 64, days='7')
        self.assertEqual(validate_inputs(**valid), 7)
        for change in ({'days': ''}, {'days': '0'}, {'days': '31'}, {'days': '7.5'},
                       {'run_id': '../12'}, {'tag': 'also-release'}, {'sha256': 'x'}, {'mode': 'auto'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_inputs(**(valid | change))

    def test_run_origin_must_be_completed_manual_default_branch_workflow(self):
        from src.pages_refresh import validate_run
        run = dict(id=123, path='.github/workflows/pages-manual.yml', event='workflow_dispatch',
                   status='completed', head_branch='main')
        validate_run(run, '123', 'main')
        for suffix in ('@main', '@refs/heads/main'):
            validate_run(run | {'path': run['path'] + suffix}, '123', 'main')
        for field, value in [('id', 124), ('path', 'other.yml'), ('event', 'pull_request'),
                             ('status', 'in_progress'), ('head_branch', 'other'),
                             ('path', run['path'] + '@other')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_run(run | {field: value}, '123', 'main')

    def test_all_failures_skip_without_export_or_rewriting_seed(self):
        from src.pages_refresh import prepare
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            original = (root / 'input.zip').read_bytes()
            def fail(*args):
                raise RuntimeError('private exception must not be included')
            result = prepare(root / 'input.zip', package['sha256'], root / 'work',
                             mode='refresh', days=3, products=['sst', 'tchp'], update=fail)
            self.assertFalse(result['deploy'])
            self.assertEqual(result['reason'], 'no_successful_update')
            self.assertFalse((root / 'work/output/weather-snapshot.zip').exists())
            self.assertEqual((root / 'input.zip').read_bytes(), original)
            self.assertNotIn('private exception', json.dumps(result))

    def test_partial_failure_preserves_exact_old_bytes_and_records_incomplete_histories(self):
        from src.pages_refresh import prepare, summary_markdown
        from src.pages_package import unpack_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            previous = (root / 'snapshot/data/images/tchp/latest.json').read_bytes()
            def update(product, images):
                if product == 'tchp':
                    raise RuntimeError('offline')
                path = images / product / 'latest.json'
                data = json.loads(path.read_bytes())
                data['fetched_at'] = '2026-10-29T00:00:00+00:00'
                path.write_text(json.dumps(data), encoding='utf-8')
            result = prepare(root / 'input.zip', package['sha256'], root / 'work',
                             mode='refresh', days=3, products=['sst', 'tchp'], update=update)
            self.assertTrue(result['deploy'])
            self.assertEqual((root / 'work/site-data/images/tchp/latest.json').read_bytes(), previous)
            archive = root / 'work/output/weather-snapshot.zip'
            restored = unpack_snapshot(archive, result['sha256'], root / 'restored')
            self.assertEqual(restored['files'], result['files'])
            self.assertIn('tchp: failed', summary_markdown(result))
            self.assertIn('incomplete_history', summary_markdown(result))
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), result['sha256'])

    def test_corrupt_source_stops_before_fetching(self):
        from src.pages_refresh import prepare
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.seed(root)
            def forbidden(*args):
                self.fail('must validate source before contacting sources')
            with self.assertRaises(ValueError):
                prepare(root / 'input.zip', '0' * 64, root / 'work', mode='refresh', days=3,
                        products=['sst'], update=forbidden)

    def test_expired_source_stops_before_fetching(self):
        from datetime import datetime, timedelta, timezone
        from src.pages_package import pack_snapshot
        from src.pages_refresh import prepare
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.seed(root)
            package = pack_snapshot(root / 'snapshot', root / 'expired.zip', valid_days=1,
                                    now=datetime.now(timezone.utc) - timedelta(days=2))
            def forbidden(*args):
                self.fail('must reject expired package before fetching')
            with self.assertRaises(ValueError):
                prepare(root / 'expired.zip', package['sha256'], root / 'work', mode='refresh',
                        days=3, products=['sst'], update=forbidden)

    def test_snapshot_save_failure_has_no_deployable_output(self):
        from unittest.mock import patch
        from src.pages_refresh import prepare
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            def update(product, images):
                path = images / product / 'latest.json'
                data = json.loads(path.read_bytes())
                data['fetched_at'] = '2026-10-29T00:00:00+00:00'
                path.write_text(json.dumps(data), encoding='utf-8')
            with patch('src.pages_refresh.pack_snapshot', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    prepare(root / 'input.zip', package['sha256'], root / 'work', mode='refresh',
                            days=3, products=['sst'], update=update)
            self.assertFalse((root / 'work/site-data').exists())
            self.assertFalse((root / 'work/output/weather-snapshot.zip').exists())

    def test_publish_reuses_selected_package_without_renewing_expiry(self):
        from src.pages_refresh import prepare
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            result = prepare(root / 'input.zip', package['sha256'], root / 'work', mode='publish', days=3)
            self.assertTrue(result['deploy'])
            self.assertEqual(result['expires_at'], package['expires_at'])
            self.assertEqual((root / 'work/output/weather-snapshot.zip').read_bytes(), (root / 'input.zip').read_bytes())

    def test_missing_new_day_inventory_blocks_candidate_and_reports_no_data(self):
        from src.pages_refresh import prepare, summary_markdown
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            def update(product, images):
                path = images / product / 'latest.json'
                data = json.loads(path.read_bytes())
                data['image_time'] = '2099-01-01T00:10:00+08:00'
                path.write_text(json.dumps(data), encoding='utf-8')
            result = prepare(root / 'input.zip', package['sha256'], root / 'work', mode='refresh',
                             days=3, products=['radar'], update=update)
            self.assertFalse(result['deploy'])
            self.assertEqual(result['reason'], 'candidate_not_publishable')
            self.assertEqual(result['resources']['images/radar/history/2099-01-01.json']['state'], 'no_data')
            self.assertIn('no_data', summary_markdown(result))
            self.assertFalse((root / 'work/output/weather-snapshot.zip').exists())

    def test_failure_after_partial_writes_still_skips_when_all_products_fail(self):
        from src.pages_refresh import prepare
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            def update(product, images):
                path = images / product / 'latest.json'
                data = json.loads(path.read_bytes())
                data['fetched_at'] = '2026-10-29T00:00:00+00:00'
                path.write_text(json.dumps(data), encoding='utf-8')
                raise RuntimeError('partial source failure')
            result = prepare(root / 'input.zip', package['sha256'], root / 'work', mode='refresh',
                             days=3, products=['sst'], update=update)
            self.assertGreater(result['updated_count'], 0)
            self.assertFalse(result['deploy'])
            self.assertFalse((root / 'work/output/weather-snapshot.zip').exists())
