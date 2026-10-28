"""Create a protected local JSON snapshot; never deploy or modify public files."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

from src.snapshot_runner import run_candidate, current_snapshot
from src.snapshots import restore_snapshot
from src.publication import atomic_write_json
from src.update_runner import FileLock, UpdateInProgress
from update_images import registered_products, update_image

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', encoding='utf-8-sig')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('types', nargs='*')
    parser.add_argument('--store', type=Path, default=ROOT / '.runtime/snapshots')
    parser.add_argument('--seed-data', type=Path, default=None,
                        help='Explicit bootstrap JSON directory; used only without a saved snapshot')
    parser.add_argument('--previous-snapshot', type=Path, help='Explicit manifest snapshot to restore')
    args = parser.parse_args(argv)
    registered = registered_products()
    if set(args.types) - registered.keys():
        parser.error('Unknown product')
    if args.seed_data and args.previous_snapshot:
        parser.error('Choose seed data or previous snapshot')
    bootstrap = args.seed_data or ROOT / 'frontend/public/data'
    if (bootstrap.resolve().is_relative_to(args.store.resolve())
            or args.store.resolve().is_relative_to(bootstrap.resolve())
            or args.store.resolve().is_relative_to((ROOT / 'frontend/public').resolve())):
        parser.error('Seed data and store must not overlap')
    try:
        # Includes restoration: overlapping runs cannot restore an obsolete pointer.
        with FileLock(args.store / 'command.lock'):
            previous = args.previous_snapshot or current_snapshot(args.store)
            with tempfile.TemporaryDirectory(dir=args.store.parent) as temporary:
                seed = Path(temporary) / 'restored'
                if previous:
                    restore_snapshot(previous, seed)
                else:
                    seed = bootstrap
                report = run_candidate(args.types or registered, seed, args.store, update_image)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return int(not report['publishable'] or any(s == 'failed' for s in report['products'].values())
                       or any(r['state'] == 'incomplete_history' or r['error_code'] for r in report['resources'].values()))
    except (ValueError, OSError, UpdateInProgress):
        from datetime import datetime, timezone
        from uuid import uuid4
        try:
            atomic_write_json({'schema_version': 1, 'state': 'failed',
                               'error_code': 'snapshot_restore_or_save_failed',
                               'attempted_at': datetime.now(timezone.utc).isoformat()},
                              args.store / 'reports' / f'failure-{uuid4().hex}.json')
        except OSError:
            pass
        print('Snapshot update/restore failed; previous snapshot remains selected.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
