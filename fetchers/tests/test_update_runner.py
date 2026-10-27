from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class UpdateRunnerTests(unittest.TestCase):
    def test_unreadable_status_does_not_stop_updates_or_erase_previous_success(self):
        from unittest.mock import patch
        from src.update_runner import run_batch, write_status
        calls = []
        logs = io.StringIO()
        def update(kind, root): calls.append(kind); return {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            write_status(runtime, {'resources': {'radar': {'last_success_at': '2026-10-27T00:00:00+00:00'}}})
            status = runtime / 'status.json'
            original = status.read_bytes()
            with patch('src.update_runner.read_status', side_effect=PermissionError('private-secret')), \
                 redirect_stdout(logs), redirect_stderr(logs):
                result = run_batch(['radar', 'satellite'], Path(directory) / 'images', update, runtime)
            self.assertEqual(result, 0)
            self.assertEqual(calls, ['radar', 'satellite'])
            self.assertEqual(status.read_bytes(), original)
            self.assertNotIn('private-secret', logs.getvalue())

    def test_status_collision_after_arctic_does_not_skip_remaining_products(self):
        from unittest.mock import patch
        from src.update_runner import run_batch, write_status
        types = ['sst', 'temperature', 'weather_chart', '850hpa', 'tchp',
                 'cimss_wind_analysis', 'cimss_steering_flow', 'seaice_arctic',
                 'seaice_antarctic', 'radar', 'satellite', 'rainfall', 'rainfall_rankings']
        calls = []
        collided = []
        def save(runtime, report):
            if report['resources'].get('seaice_antarctic', {}).get('state') == 'running' and not collided:
                collided.append(True)
                raise PermissionError('temporary sharing violation, private detail must not leak')
            return write_status(runtime, report)
        def update(kind, root): calls.append(kind); return {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            with patch('src.update_runner.write_status', side_effect=save), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = run_batch(types, Path(directory) / 'images', update, runtime)
            self.assertEqual(result, 0)
            self.assertEqual(calls, types)
            self.assertEqual(json.loads((runtime / 'status.json').read_text(encoding='utf-8'))['last_batch_state'], 'success')

    def test_persistent_private_status_failure_does_not_abort_product_updates(self):
        from unittest.mock import patch
        from src.update_runner import run_batch
        calls = []
        def update(kind, root): calls.append(kind); return {}
        logs = io.StringIO()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with patch('src.update_runner.write_status', side_effect=OSError('Authorization=private-secret')), \
                 redirect_stdout(logs), redirect_stderr(logs):
                self.assertEqual(run_batch(['radar', 'satellite'], Path(directory) / 'images', update,
                                           Path(directory) / '.runtime'), 0)
        self.assertEqual(calls, ['radar', 'satellite'])
        self.assertIn('status', logs.getvalue().lower())
        self.assertNotIn('private-secret', logs.getvalue())

    def test_legacy_sst_command_also_uses_shared_batch_guard(self):
        from unittest.mock import patch
        import update_sst
        with patch.object(update_sst, 'run_batch', create=True, return_value=0) as batch, \
             patch.object(update_sst, 'update_sst', return_value={
                 'image_time': '2026-10-25', 'fetched_at': '2026-10-27T02:05:00+00:00'}), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(update_sst.main(), 0)
        batch.assert_called_once()
        self.assertEqual(batch.call_args.args[0], ['sst'])

    def test_invalid_result_is_a_failed_resource_not_a_batch_crash(self):
        from src.update_runner import run_batch
        calls = []
        def update(kind, root):
            calls.append(kind)
            return None if kind == 'radar' else {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(run_batch(['radar', 'satellite'], Path(directory) / 'images', update,
                                           Path(directory) / '.runtime'), 1)
            self.assertEqual(calls, ['radar', 'satellite'])

    def test_failed_product_does_not_stop_batch_and_status_is_private(self):
        from src.update_runner import run_batch
        calls = []
        def update(kind, root):
            calls.append(kind)
            if kind == 'radar':
                raise RuntimeError('Authorization=do-not-expose-this-secret')
            return {'image_time': '2026-10-27T10:00:00+08:00', 'fetched_at': '2026-10-27T02:05:00+00:00'}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            output = Path(directory) / 'public/data/images'
            logs = io.StringIO()
            with redirect_stdout(logs), redirect_stderr(logs):
                result = run_batch(['radar', 'satellite'], output, update, runtime)
            status = json.loads((runtime / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(result, 1)
            self.assertEqual(calls, ['radar', 'satellite'])
            self.assertEqual(status['state'], 'partial_failure')
            self.assertEqual(status['resources']['radar']['state'], 'failed')
            self.assertEqual(status['resources']['satellite']['state'], 'success')
            self.assertNotIn('do-not-expose', logs.getvalue() + json.dumps(status))
            self.assertFalse(output.exists())
            self.assertIsNotNone(status['finished_at'])

    def test_previous_success_is_kept_after_failure(self):
        from src.update_runner import run_batch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            output = Path(directory) / 'images'
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                run_batch(['radar'], output, lambda *_: {'image_time': '2026-10-27T10:00:00+08:00'}, runtime)
                before = json.loads((runtime / 'status.json').read_text(encoding='utf-8'))
                def failed(*args): raise RuntimeError('offline')
                run_batch(['radar'], output, failed, runtime)
            after = json.loads((runtime / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(after['resources']['radar']['last_success_at'], before['resources']['radar']['last_success_at'])
            self.assertEqual(after['resources']['radar']['image_time'], '2026-10-27T10:00:00+08:00')
            self.assertEqual(after['state'], 'failed')

    def test_lock_rejects_overlap_and_releases_after_exception(self):
        from src.update_runner import FileLock, UpdateInProgress
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'update.lock'
            with self.assertRaisesRegex(RuntimeError, 'test exception'):
                with FileLock(path):
                    with self.assertRaises(UpdateInProgress):
                        with FileLock(path): self.fail('overlap allowed')
                    raise RuntimeError('test exception')
            with FileLock(path):
                pass

    def test_running_batch_is_visible_before_fetch_and_locked(self):
        from src.update_runner import FileLock, UpdateInProgress, run_batch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            def update(kind, root):
                status = json.loads((runtime / 'status.json').read_text(encoding='utf-8'))
                self.assertEqual(status['state'], 'running')
                self.assertEqual(status['resources'][kind]['state'], 'running')
                with self.assertRaises(UpdateInProgress):
                    with FileLock(runtime / 'update.lock'): pass
                return {}
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run_batch(['radar'], Path(directory) / 'images', update, runtime), 0)

    def test_interrupt_records_interrupted_resource_and_releases_lock(self):
        from src.update_runner import FileLock, run_batch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            def update(*args): raise KeyboardInterrupt()
            with redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
                run_batch(['radar'], Path(directory) / 'images', update, runtime)
            status = json.loads((runtime / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(status['state'], 'stopped')
            self.assertEqual(status['resources']['radar']['state'], 'interrupted')
            with FileLock(runtime / 'update.lock'): pass

    def test_rejected_overlapping_batch_does_not_rewrite_status(self):
        from src.update_runner import FileLock, UpdateInProgress, run_batch
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            runtime.mkdir()
            status = runtime / 'status.json'
            status.write_bytes(b'previous status')
            with FileLock(runtime / 'update.lock'):
                with self.assertRaises(UpdateInProgress):
                    run_batch(['radar'], Path(directory) / 'images', lambda *_: {}, runtime)
            self.assertEqual(status.read_bytes(), b'previous status')
