"""Manual Actions adapter: no network except existing fetchers; no Git writes."""
import argparse
import json
import os
from pathlib import Path
import sys

from src.pages_refresh import prepare, summary_markdown, validate_inputs, validate_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inputs', 'source-run', 'prepare'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'inputs':
            validate_inputs(mode=os.environ['MODE'], run_id=os.environ.get('SOURCE_RUN', ''),
                            tag=os.environ.get('RELEASE_TAG', ''), asset=os.environ.get('ASSET_NAME', ''),
                            sha256=os.environ['ASSET_SHA'], days=os.environ['RETENTION_DAYS'])
        elif args.command == 'source-run':
            validate_run(json.loads(Path(os.environ['RUN_METADATA']).read_text()),
                         os.environ['SOURCE_RUN'], os.environ['DEFAULT_BRANCH'])
        else:
            products, update = None, None
            if os.environ['MODE'] == 'refresh':
                if not os.environ.get('CWA_API_KEY', '').strip():
                    raise ValueError('CWA_API_KEY is required for refreshing all website resources')
                from update_images import registered_products, update_image
                products, update = registered_products(), update_image
            result = prepare(os.environ['ARCHIVE'], os.environ['ASSET_SHA'], os.environ['WORK'],
                             mode=os.environ['MODE'], days=int(os.environ['RETENTION_DAYS']),
                             products=products, update=update)
            Path(os.environ['RESULT']).write_text(json.dumps(result, indent=2), encoding='utf-8')
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
                summary.write(summary_markdown(result))
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write('deploy=' + str(result['deploy']).lower() + '\n')
                output.write('snapshot_id=' + str(result.get('snapshot_id') or '') + '\n')
            if result['reason'] == 'candidate_not_publishable':
                return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print('Manual Pages preparation failed; deployment must stop. Check selected input, policy and secret configuration.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
