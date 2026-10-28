"""Pack a local snapshot or verify/restore an explicitly downloaded package."""
import argparse
import json
from pathlib import Path
import re
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='command', required=True)
    pack = actions.add_parser('pack')
    pack.add_argument('--snapshot', required=True, type=Path)
    pack.add_argument('--output', required=True, type=Path)
    pack.add_argument('--valid-days', type=int, default=7)
    restore = actions.add_parser('restore')
    restore.add_argument('--archive', required=True, type=Path)
    restore.add_argument('--sha256', required=True)
    restore.add_argument('--destination', required=True, type=Path)
    inputs = actions.add_parser('check-inputs')
    inputs.add_argument('--tag', required=True)
    inputs.add_argument('--asset', required=True)
    inputs.add_argument('--sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'pack':
            from src.pages_package import pack_snapshot
            result = pack_snapshot(args.snapshot, args.output, valid_days=args.valid_days)
        elif args.command == 'restore':
            from src.pages_package import unpack_snapshot
            result = unpack_snapshot(args.archive, args.sha256, args.destination)
        else:
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', args.tag)
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.zip', args.asset)
                    or not re.fullmatch('[0-9a-f]{64}', args.sha256)):
                raise ValueError('Invalid release tag, exact asset name or SHA-256')
            result = {'inputs_valid': True}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError):
        print('Pages input validation failed; deployment must stop.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
