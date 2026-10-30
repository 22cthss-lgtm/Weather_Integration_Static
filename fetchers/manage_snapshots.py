"""Bounded Actions snapshot management; all mutation is in cleanup."""
import argparse
import json
import os
import sys

from src.artifact_store import GitHubArtifactClient
from src.cloud_snapshots import CloudSnapshots


def main(argv=None, *, env=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('resolve', 'verify-data', 'verify-state', 'cleanup', 'guard'))
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    try:
        client = client or GitHubArtifactClient(env['GITHUB_REPOSITORY'], env['GH_TOKEN'])
        manager = CloudSnapshots(client, env)
        result = getattr(manager, args.command.replace('-', '_'))()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError):
        print('Snapshot management failed; publication must stop. Check artifact access and validated input.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
