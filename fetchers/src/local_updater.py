"""A bounded or continuous local loop around the shared one-batch runner."""

from datetime import datetime, timedelta, timezone
import os
import math
from pathlib import Path
import sys
import time

from .update_runner import FileLock, UpdateInProgress, read_status_safely, run_batch, runtime_directory, save_status


def _local_state(runtime_dir, state, *, delay=None):
    # A manually invoked one-shot job may run while this watcher is waiting.
    # Never overwrite that job's in-progress status.
    try:
        with FileLock(Path(runtime_dir) / 'update.lock'):
            report = read_status_safely(runtime_dir)
            if report is None:
                return
            if report.get('pid') != os.getpid() or report.get('mode') != 'local':
                return
            next_run = datetime.now(timezone.utc) + timedelta(seconds=delay) if delay is not None else None
            report.update(state=state, next_run_at=next_run.isoformat() if next_run else None)
            save_status(runtime_dir, report)
    except UpdateInProgress:
        pass


def run_local(types, output_root, update, runtime_dir=None, *, interval_seconds=600,
              max_cycles=None, wait=time.sleep):
    runtime_dir = Path(runtime_dir) if runtime_dir is not None else runtime_directory(output_root)
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError('Interval must be finite and positive')
    if max_cycles is not None and max_cycles <= 0:
        raise ValueError('Cycle count must be positive')
    types = list(types)
    with FileLock(runtime_dir / 'watch.lock'):
        print(f'Local updater started. First update begins now; wait {interval_seconds:g} seconds after each batch. '
              'Press Ctrl+C to stop.', flush=True)
        cycle = 0
        result = 1
        try:
            while max_cycles is None or cycle < max_cycles:
                cycle += 1
                try:
                    result = run_batch(types, output_root, update, runtime_dir, mode='local')
                except UpdateInProgress:
                    result = 1
                    print('Another update is running; this cycle was skipped.', file=sys.stderr, flush=True)
                except Exception:
                    result = 1
                    print('Local update could not complete. It will be retried next cycle.',
                          file=sys.stderr, flush=True)
                if max_cycles is not None and cycle >= max_cycles:
                    break
                _local_state(runtime_dir, 'waiting', delay=interval_seconds)
                print(f'Waiting {interval_seconds:g} seconds before the next update.', flush=True)
                wait(interval_seconds)
        except KeyboardInterrupt:
            result = 130
            print('Local updater stopped by user.', flush=True)
        finally:
            _local_state(runtime_dir, 'stopped')
        return result


def is_locked(path):
    if not Path(path).exists():
        return False
    try:
        with FileLock(path):
            return False
    except UpdateInProgress:
        return True
