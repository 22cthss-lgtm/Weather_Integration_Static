"""Manual Actions adapter: no network except existing fetchers; no Git writes."""
import argparse
import json
import os
from pathlib import Path
import sys

from src.pages_refresh import summary_markdown, validate_inputs, validate_run
from src.due_refresh import load_policy, prepare_due


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inputs', 'source-run', 'prepare'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'inputs':
            policy = load_policy()
            if int(os.environ['RETENTION_DAYS']) != policy['artifact_retention_days']:
                raise ValueError('Retention input must match the confirmed policy')
            if os.environ.get('SOURCE_MODE') == 'auto':
                if os.environ['MODE'] not in ('publish', 'refresh') or any(os.environ.get(key, '') for key in ('SOURCE_RUN', 'RELEASE_TAG', 'ASSET_NAME', 'ASSET_SHA')):
                    raise ValueError('Automatic selection must not include explicit source inputs')
            else:
                validate_inputs(mode=os.environ['MODE'], run_id=os.environ.get('SOURCE_RUN', ''),
                            tag=os.environ.get('RELEASE_TAG', ''), asset=os.environ.get('ASSET_NAME', ''),
                            sha256=os.environ['ASSET_SHA'], days=os.environ['RETENTION_DAYS'])
        elif args.command == 'source-run':
            validate_run(json.loads(Path(os.environ['RUN_METADATA']).read_text()),
                         os.environ['SOURCE_RUN'], os.environ['DEFAULT_BRANCH'])
        else:
            update = None
            if os.environ['MODE'] == 'refresh':
                if not os.environ.get('CWA_API_KEY', '').strip():
                    raise ValueError('CWA_API_KEY is required for refreshing all website resources')
                from update_images import registered_products, update_image
                update = update_image
            state_path = Path(os.environ['RUNNER_TEMP']) / 'source-state.json' if os.environ.get('RUNNER_TEMP') else None
            state_document = None
            if state_path and state_path.is_file():
                try:
                    if state_path.stat().st_size > 1024 * 1024:
                        raise ValueError('Oversized state')
                    state_document = json.loads(state_path.read_text())
                except (ValueError, OSError):
                    state_document = {}  # Engine reports corrupt and resets safely.
            result = prepare_due(os.environ['ARCHIVE'], os.environ['ASSET_SHA'], os.environ['WORK'],
                                 mode=os.environ['MODE'], policy=load_policy(), update=update,
                                 state_document=state_document)
            if result['deploy']:
                marker = {'schema_version': 1, 'content_id': result['content_id'],
                          'code_sha': os.environ.get('GITHUB_SHA', 'local'),
                          'run_id': os.environ.get('GITHUB_RUN_ID', 'local'),
                          'run_number': os.environ.get('GITHUB_RUN_NUMBER', '0')}
                (Path(os.environ['WORK']) / 'site-data').parent.joinpath('deployment.json').write_text(json.dumps(marker), encoding='utf-8')
            Path(os.environ['RESULT']).write_text(json.dumps(result, indent=2), encoding='utf-8')
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
                summary.write(summary_markdown(result))
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write('deploy=' + str(result['deploy']).lower() + '\n')
                output.write('snapshot_id=' + str(result.get('snapshot_id') or '') + '\n')
                output.write('save_snapshot=' + str(result['save_snapshot']).lower() + '\n')
                output.write('content_id=' + result['content_id'] + '\n')
            if result['reason'] == 'candidate_not_publishable':
                return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print('Manual Pages preparation failed; deployment must stop. Check selected input, policy and secret configuration.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
