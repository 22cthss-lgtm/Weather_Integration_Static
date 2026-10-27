from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class WatchImagesTests(unittest.TestCase):
    def test_status_read_failure_between_batches_keeps_loop_and_previous_record(self):
        from src.local_updater import run_local
        from src.update_runner import read_status
        calls = []
        reads = []
        saved = []
        def read(runtime):
            reads.append(True)
            if len(reads) > 1:
                raise PermissionError('status occupied')
            return read_status(runtime)
        def update(kind, root): calls.append(kind); return {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            def wait(_): saved.append((runtime / 'status.json').read_bytes())
            with patch('src.update_runner.read_status', side_effect=read), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = run_local(['radar'], Path(directory) / 'images', update, runtime,
                                   max_cycles=2, wait=wait)
            self.assertEqual(result, 0)
            self.assertEqual(calls, ['radar', 'radar'])
            self.assertEqual((runtime / 'status.json').read_bytes(), saved[0])

    def test_status_failure_during_wait_still_runs_next_cycle(self):
        from src.local_updater import run_local
        from src.update_runner import write_status
        calls = []
        def save(runtime, report):
            if report['state'] in ('waiting', 'stopped'):
                raise PermissionError('status temporarily in use')
            return write_status(runtime, report)
        def update(kind, root): calls.append(kind); return {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with patch('src.update_runner.write_status', side_effect=save), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = run_local(['radar'], Path(directory) / 'images', update,
                    Path(directory) / '.runtime', max_cycles=2, wait=lambda _: None)
        self.assertEqual(result, 0)
        self.assertEqual(calls, ['radar', 'radar'])

    def test_immediate_first_cycle_then_wait_and_retry_failed_product(self):
        from src.local_updater import run_local
        calls = []
        waits = []
        def update(kind, root):
            calls.append(kind)
            if len(calls) == 1: raise RuntimeError('source unavailable')
            return {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            def wait(seconds):
                self.assertEqual(len(calls), 1)
                status = json.loads((runtime / 'status.json').read_text(encoding='utf-8'))
                self.assertEqual(status['state'], 'waiting')
                self.assertIsNotNone(status['next_run_at'])
                waits.append(seconds)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = run_local(['radar'], Path(directory) / 'images', update, runtime,
                                   interval_seconds=60, max_cycles=2, wait=wait)
            self.assertEqual(calls, ['radar', 'radar'])
            self.assertEqual(waits, [60])
            self.assertEqual(result, 0)
            status = json.loads((runtime / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(status['state'], 'stopped')
            self.assertEqual(status['last_batch_state'], 'success')
            self.assertIsNone(status['next_run_at'])

    def test_ctrl_c_during_wait_stops_without_another_fetch(self):
        from src.local_updater import run_local
        calls = []
        def update(*args): calls.append(True); return {}
        def wait(seconds): raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = run_local(['radar'], Path(directory) / 'images', update, runtime,
                                 interval_seconds=600, wait=wait)
            self.assertEqual(code, 130)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads((runtime / 'status.json').read_text(encoding='utf-8'))['state'], 'stopped')

    def test_duplicate_watch_process_is_refused_even_between_batches(self):
        from src.update_runner import FileLock, UpdateInProgress
        from src.local_updater import run_local
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            runtime = Path(directory) / '.runtime'
            with FileLock(runtime / 'watch.lock'):
                with self.assertRaises(UpdateInProgress):
                    run_local(['radar'], Path(directory) / 'images', lambda *_: {}, runtime, max_cycles=1)

    def test_invalid_intervals_are_rejected_without_fetching(self):
        import watch_images
        for value in ('0', '-1', 'nan', 'inf'):
            with self.subTest(value=value), patch.object(watch_images, 'run_local') as run:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    watch_images.main(['--interval-minutes', value])
                run.assert_not_called()

    def test_once_uses_one_cycle_and_default_selection(self):
        import watch_images
        with patch.object(watch_images, 'run_local', return_value=0) as run:
            self.assertEqual(watch_images.main(['--once']), 0)
        self.assertEqual(run.call_args.kwargs['max_cycles'], 1)
        self.assertIn('rainfall_rankings', run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs['interval_seconds'], 600)
