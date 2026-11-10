"""Bounded Actions snapshot management; all mutation is in cleanup."""
import argparse
import json
import os
import sys

from src.artifact_store import GitHubArtifactClient
from src.cloud_snapshots import CloudSnapshots, safe_reason


def main(argv=None, *, env=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('resolve', 'deployment', 'verify-data', 'verify-state', 'cleanup', 'guard'))
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    try:
        # Cleanup re-verifies every retained snapshot (tiered retention keeps ~30),
        # so it gets a larger overall budget; other commands keep the default.
        budget = 300 if args.command == 'cleanup' else 120
        client = client or GitHubArtifactClient(env['GITHUB_REPOSITORY'], env['GH_TOKEN'],
                                                total_timeout=budget)
        manager = CloudSnapshots(client, env)
        result = getattr(manager, args.command.replace('-', '_'))()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('Snapshot management failed; publication must stop. Check artifact access and validated input.', file=sys.stderr)
        print('Failure reason: ' + safe_reason(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
