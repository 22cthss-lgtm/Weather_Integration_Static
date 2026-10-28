"""Shared one-batch orchestration for the local watcher and future CI jobs."""

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from .publication import atomic_write_json
from .http_client import http_scope

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / 'frontend/public/data/images'


class UpdateInProgress(RuntimeError):
    pass


class FileLock(AbstractContextManager):
    """OS-managed nonblocking lock; a crash releases it without deleting files."""

    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+b')
        try:
            if self.path.stat().st_size == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise UpdateInProgress('Another updater is already running for this output directory.') from None
        self.file = handle
        return self

    def __exit__(self, *args):
        try:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None


def runtime_directory(output_root):
    normalized = os.path.normcase(str(Path(output_root).resolve()))
    default = os.path.normcase(str(DEFAULT_OUTPUT_ROOT.resolve()))
    base = PROJECT_ROOT / '.runtime/updater'
    if normalized == default:
        return base
    return base / hashlib.sha256(normalized.encode()).hexdigest()[:16]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_status(runtime_dir):
    try:
        report = json.loads((Path(runtime_dir) / 'status.json').read_text(encoding='utf-8'))
        if isinstance(report, dict) and isinstance(report.get('resources'), dict):
            return report
    except (FileNotFoundError, ValueError):
        pass
    return {'resources': {}}


def write_status(runtime_dir, report):
    return atomic_write_json(report, Path(runtime_dir) / 'status.json')


def read_status_safely(runtime_dir):
    for attempt in range(4):
        try:
            return read_status(runtime_dir)
        except OSError as exc:
            if isinstance(exc, PermissionError) and attempt < 3:
                time.sleep(0.02 * (2 ** attempt))
                continue
            print('Previous update status could not be read; keeping it unchanged. '
                  'Product updates will continue.', file=sys.stderr, flush=True)
            return None


def save_status(runtime_dir, report):
    """Private progress must never abort a batch of otherwise valid updates."""
    for attempt in range(4):
        try:
            write_status(runtime_dir, report)
            return True
        except OSError as exc:
            # Windows readers/indexers can briefly deny replacing the status
            # file. Retry only the private record, not successful Fetchers.
            if isinstance(exc, PermissionError) and attempt < 3:
                time.sleep(0.02 * (2 ** attempt))
                continue
            print('Update status could not be saved; product updates will continue. '
                  'The status display may be out of date.', file=sys.stderr, flush=True)
            return False


def run_batch(types, output_root, update, runtime_dir=None, *, mode='once'):
    """Run each selected updater once; do not disclose source exceptions."""
    runtime_dir = Path(runtime_dir) if runtime_dir is not None else runtime_directory(output_root)
    types = list(dict.fromkeys(types))
    if not types:
        raise ValueError('At least one product is required')
    with FileLock(runtime_dir / 'update.lock'), http_scope():
        report = read_status_safely(runtime_dir)
        can_save = report is not None
        if report is None:
            report = {'resources': {}}

        def checkpoint():
            # Do not replace an unreadable previous record with empty history.
            if can_save:
                save_status(runtime_dir, report)

        report.update(schema_version=1, state='running', mode=mode, pid=os.getpid(),
                      started_at=utc_now(), finished_at=None, next_run_at=None,
                      selected_products=types)
        checkpoint()
        failed = 0
        active_kind = None
        try:
            for kind in types:
                active_kind = kind
                entry = report['resources'].setdefault(kind, {})
                entry.update(state='running', attempted_at=utc_now(), finished_at=None, error_code=None)
                checkpoint()
                print(f'[{utc_now()}] {kind}: updating', flush=True)
                try:
                    data = update(kind, output_root)
                    if not isinstance(data, dict):
                        raise RuntimeError('Invalid updater result')
                except Exception:
                    failed += 1
                    entry.update(state='failed', finished_at=utc_now(), error_code='update_failed_or_incomplete')
                    # Never include arbitrary requests exceptions/URLs: they may
                    # contain the generator-side API authorization parameter.
                    print(f'{kind}: update failed or incomplete; previous JSON preserved for failed resources',
                          file=sys.stderr, flush=True)
                else:
                    entry.update(state='success', finished_at=utc_now(), last_success_at=utc_now())
                    for field in ('image_time', 'fetched_at'):
                        value = data.get(field)
                        if value is None:
                            entry[field] = None
                        elif isinstance(value, str):
                            # Store only parseable time fields, never raw payloads.
                            try:
                                datetime.fromisoformat(value)
                                entry[field] = value
                            except ValueError:
                                pass
                    print(f'[{utc_now()}] {kind}: success', flush=True)
                checkpoint()
                active_kind = None
        except KeyboardInterrupt:
            if active_kind is not None:
                report['resources'][active_kind].update(state='interrupted', finished_at=utc_now(),
                                                       error_code='interrupted')
            report.update(state='stopped', last_batch_state='interrupted', finished_at=utc_now(), next_run_at=None)
            checkpoint()
            raise
        state = 'success' if failed == 0 else 'failed' if failed == len(types) else 'partial_failure'
        report.update(state=state, last_batch_state=state, finished_at=utc_now(), next_run_at=None)
        checkpoint()
        return int(failed > 0)
