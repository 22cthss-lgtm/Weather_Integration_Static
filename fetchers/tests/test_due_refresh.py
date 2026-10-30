from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DueRefreshTests(unittest.TestCase):
    def test_invalid_latest_cannot_claim_success_from_service_outcome(self):
        from src.due_refresh import prepare_due, load_policy
        from src.history_reconciliation import current_history_context
        from src.scheduling import default_tasks
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            def update(kind, images):
                (images/kind/'latest.json').write_text('{}', encoding='utf-8')
                current_history_context().outcome(kind, latest_ok=True)
            result = prepare_due(root/'input.zip', package['sha256'], root/'work', mode='refresh',
                                 task_config={'radar': default_tasks()['radar']}, update=update,
                                 policy=load_policy())
            self.assertFalse(result['deploy'])
            self.assertEqual(result['checks']['radar']['state'], 'retained_after_failure')
            self.assertEqual(result['scheduler_state']['scheduler']['tasks']['radar']['consecutive_failures'], 1)

    def test_daily_rain_success_survives_latest_failure_but_invalid_daily_does_not(self):
        from src.due_refresh import prepare_due, load_policy
        from src.history_reconciliation import current_history_context
        from src.scheduling import default_tasks
        for valid_daily in (True, False):
            with self.subTest(valid_daily=valid_daily), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                root = Path(directory)
                package = self.seed(root)
                latest_before = (root/'seed/data/images/rainfall/latest.json').read_bytes()
                daily_before = (root/'seed/data/images/rainfall/daily/latest.json').read_bytes()
                def update(kind, images):
                    path = images/'rainfall/daily/latest.json'
                    daily = json.loads(path.read_bytes())
                    if valid_daily:
                        daily['items'][1]['title'] += ' verified update'
                    else:
                        daily['items'] = []
                    path.write_text(json.dumps(daily), encoding='utf-8')
                    latest = images/'rainfall/latest.json'
                    data = json.loads(latest.read_bytes())
                    data['title'] = 'Unverified partial latest'
                    latest.write_text(json.dumps(data), encoding='utf-8')
                    current_history_context().outcome(kind, latest_ok=False, daily_ok=True)
                    raise RuntimeError('latest failed')
                result = prepare_due(root/'input.zip', package['sha256'], root/'work', mode='refresh',
                                     task_config={'rainfall': default_tasks()['rainfall']}, update=update,
                                     policy=load_policy())
                self.assertEqual(result['deploy'], valid_daily)
                self.assertEqual(result['checks']['rainfall']['state'], 'retained_after_failure')
                self.assertEqual(result['scheduler_state']['scheduler']['tasks']['rainfall']['consecutive_failures'], 1)
                self.assertEqual(result['resources']['images/rainfall/daily/latest.json']['updated'], valid_daily)
                if valid_daily:
                    self.assertEqual((root/'work/site-data/images/rainfall/latest.json').read_bytes(), latest_before)
                    self.assertNotEqual((root/'work/site-data/images/rainfall/daily/latest.json').read_bytes(), daily_before)

    def test_fixed_url_body_change_with_identical_json_still_creates_version(self):
        from src.due_refresh import prepare_due, load_policy
        from src.scheduling import default_tasks
        from src.content_versions import canonical_url, content_metadata
        from src.pages_package import pack_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.seed(root)
            data = root/'seed/data'
            payload = json.loads((data/'images/weather_chart/latest.json').read_bytes())
            key = canonical_url(payload['image_url'])
            now = datetime.now(timezone.utc)
            content = content_metadata(data, {key:'a'*64}, now.isoformat())
            package = pack_snapshot(root/'seed', root/'versioned.zip', content=content, now=now)
            result = prepare_due(root/'versioned.zip', package['sha256'], root/'check', mode='refresh',
                                 policy=load_policy(), now=now, task_config={'weather_chart':default_tasks()['weather_chart']},
                                 update=lambda *args:None, image_hasher=lambda resources, prior:dict(prior, **{key:'b'*64}))
            self.assertTrue(result['deploy'])
            self.assertNotEqual(result['content_id'], content['content_id'])

    def seed(self, root):
        from src.pages_package import pack_snapshot
        from src.snapshots import export_snapshot
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
        export_snapshot(source, root / 'seed')
        return pack_snapshot(root / 'seed', root / 'input.zip')

    def test_unchanged_check_is_saved_and_next_run_skips_without_new_package(self):
        from src.due_refresh import prepare_due, load_policy
        from src.scheduling import new_state, default_tasks
        from src.pages_package import unpack_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            selected = unpack_snapshot(root/'input.zip', package['sha256'], root/'unpacked')
            now = datetime.now(timezone.utc)
            tasks = {'sst': default_tasks()['sst']}
            calls = []
            def update(kind, images):
                calls.append(kind)
                path = images/kind/'latest.json'
                data = json.loads(path.read_bytes())
                data['fetched_at'] = now.isoformat()
                path.write_text(json.dumps(data), encoding='utf-8')
            result = prepare_due(root/'input.zip', package['sha256'], root/'first', mode='refresh',
                                 task_config=tasks, update=update, policy=load_policy(), now=now)
            self.assertFalse(result['deploy'])
            self.assertEqual(result['checks']['sst']['state'], 'checked_unchanged')
            self.assertEqual(calls, ['sst'])
            self.assertFalse((root/'first/output/weather-snapshot.zip').exists())
            self.assertIsNotNone(result['scheduler_state']['scheduler']['tasks']['sst']['last_successful_check_at'])
            again = prepare_due(root/'input.zip', package['sha256'], root/'second', mode='refresh',
                                task_config=tasks, update=update, policy=load_policy(), now=now+timedelta(minutes=10),
                                state_document=result['scheduler_state'])
            self.assertEqual(calls, ['sst'])
            self.assertEqual(again['checks']['sst']['state'], 'not_due')

    def test_failure_keeps_old_data_and_retry_not_bypassed_by_normal_due(self):
        from src.due_refresh import prepare_due, load_policy
        from src.scheduling import default_tasks
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            now = datetime.now(timezone.utc)
            tasks = {'radar': default_tasks()['radar']}
            calls = []
            def fail(*args):
                calls.append(1)
                raise RuntimeError('private source failure')
            one = prepare_due(root/'input.zip', package['sha256'], root/'one', mode='refresh',
                              task_config=tasks, update=fail, policy=load_policy(), now=now)
            self.assertFalse(one['deploy'])
            self.assertEqual(one['checks']['radar']['state'], 'retained_after_failure')
            two = prepare_due(root/'input.zip', package['sha256'], root/'two', mode='refresh',
                              task_config=tasks, update=fail, policy=load_policy(), now=now+timedelta(minutes=5),
                              state_document=one['scheduler_state'])
            self.assertEqual(len(calls), 1)
            self.assertEqual(two['checks']['radar']['reason'], 'retry_wait')
            self.assertNotIn('private source failure', json.dumps(two))

    def test_real_content_change_creates_version_and_publish_keeps_bytes(self):
        from src.due_refresh import prepare_due, load_policy
        from src.scheduling import default_tasks
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            package = self.seed(root)
            now = datetime.now(timezone.utc)
            def update(kind, images):
                path = images/kind/'latest.json'
                data = json.loads(path.read_bytes())
                data['image_time'] = '2026-10-30'
                data['title'] = 'New product 2026-10-30'
                path.write_text(json.dumps(data), encoding='utf-8')
            result = prepare_due(root/'input.zip', package['sha256'], root/'refresh', mode='refresh',
                                 task_config={'sst':default_tasks()['sst']}, update=update,
                                 policy=load_policy(), now=now)
            self.assertTrue(result['deploy'])
            self.assertTrue(result['save_snapshot'])
            publish = prepare_due(root/'refresh/output/weather-snapshot.zip', result['sha256'], root/'publish',
                                  mode='publish', policy=load_policy(), now=now)
            self.assertTrue(publish['deploy'])
            self.assertFalse(publish['save_snapshot'])
            self.assertEqual(publish['content_id'], result['content_id'])
