"""Keep local static weather JSON updated until Ctrl+C; does not run the frontend."""

import argparse
import json
import math
from pathlib import Path
import sys

from src.local_updater import is_locked, run_local
from src.update_runner import UpdateInProgress, read_status_safely, runtime_directory
from update_images import OUTPUT_ROOT, registered_products, update_image


def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', encoding='utf-8-sig')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('types', nargs='*', help='Product names; default: all registered products')
    parser.add_argument('--interval-minutes', type=float, default=10)
    parser.add_argument('--output-root', type=Path, default=OUTPUT_ROOT)
    parser.add_argument('--once', action='store_true', help='Update once and exit')
    parser.add_argument('--max-cycles', type=int, help='Stop after this many cycles')
    parser.add_argument('--status', action='store_true', help='Show local status without fetching')
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval_minutes) or args.interval_minutes <= 0:
        parser.error('--interval-minutes must be a finite positive number')
    if args.max_cycles is not None and args.max_cycles <= 0:
        parser.error('--max-cycles must be positive')
    registered = registered_products()
    unknown = set(args.types) - registered.keys()
    if unknown:
        parser.error(f'Unknown products: {", ".join(sorted(unknown))}')
    runtime = runtime_directory(args.output_root)
    if args.status:
        print('Local loop:', 'running' if is_locked(runtime / 'watch.lock') else 'not running')
        print('Current batch:', 'running' if is_locked(runtime / 'update.lock') else 'not running')
        report = read_status_safely(runtime)
        if report is None:
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    try:
        return run_local(list(dict.fromkeys(args.types or registered)), args.output_root, update_image, runtime,
                         interval_seconds=args.interval_minutes * 60,
                         max_cycles=1 if args.once else args.max_cycles)
    except UpdateInProgress:
        print('Another local updater already owns this output directory.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
