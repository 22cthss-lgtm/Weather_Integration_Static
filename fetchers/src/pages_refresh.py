"""Protected manual Pages preparation; transport and HTTP policies stay shared."""
import json
from pathlib import Path
import re
import shutil

from .pages_package import pack_snapshot, unpack_snapshot, site_summary
from .snapshot_runner import run_candidate
from .snapshots import read_resources


def validate_inputs(*, mode, run_id, tag, asset, sha256, days):
    if mode not in ('publish', 'refresh') or not re.fullmatch(r'[0-9a-f]{64}', sha256):
        raise ValueError('Invalid mode or checksum')
    if not re.fullmatch(r'[1-9][0-9]*', days) or not 1 <= int(days) <= 30:
        raise ValueError('Choose explicit retention of 1..30 days')
    if run_id:
        if not re.fullmatch(r'[1-9][0-9]*', run_id) or tag or asset:
            raise ValueError('Choose one exact Actions run or Release source')
    elif (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', tag)
          or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.zip', asset)):
        raise ValueError('An exact Release tag and ZIP name are required')
    return int(days)


def validate_run(run, run_id, default_branch):
    path = '.github/workflows/pages-manual.yml'
    allowed = (path, path + '@' + default_branch, path + '@refs/heads/' + default_branch)
    if (str(run.get('id')) != run_id or run.get('path') not in allowed
            or run.get('event') not in ('workflow_dispatch', 'schedule') or run.get('status') != 'completed'
            or run.get('head_branch') != default_branch):
        raise ValueError('Source must be a completed manual run on the default branch')


def prepare(archive, sha256, work, *, mode, days, products=None, update=None):
    if mode not in ('publish', 'refresh') or type(days) is not int or not 1 <= days <= 30:
        raise ValueError('Invalid preparation policy')
    work = Path(work)
    work.mkdir(parents=True, exist_ok=False)
    seed = work / 'seed'
    selected = unpack_snapshot(archive, sha256, seed)
    if mode == 'refresh':
        if products is None or update is None:
            raise ValueError('Refresh requires registered fetchers')
        report = run_candidate(products, seed, work / 'store', update)
        successful = any(value == 'success' for value in report['products'].values())
        if not successful or not report['updated_count']:
            return dict(report, deploy=False, reason='no_successful_update')
        if not report['publishable']:
            return dict(report, deploy=False, reason='candidate_not_publishable')
        snapshot = work / 'store/snapshots' / report['snapshot_id']
    else:
        resources, _ = read_resources(seed)
        incomplete = site_summary(seed)['incomplete_history']
        report = {'products': {}, 'resources': {
            name: {'state': 'incomplete_history' if name in incomplete else 'retained',
                   'updated': False, 'error_code': None} for name in resources}, 'updated_count': 0}
        snapshot = None
    output = work / 'output/weather-snapshot.zip'
    output.parent.mkdir()
    if snapshot:
        package = pack_snapshot(snapshot, output, valid_days=days)
    else:
        # Publishing code with old data never renews the input validity period.
        shutil.copyfile(archive, output)
        package = dict(selected, sha256=sha256)
    selected = unpack_snapshot(output, package['sha256'], work / 'site-data')
    return dict(report, **selected, sha256=package['sha256'], deploy=True,
                reason='validated_candidate', mode=mode)


def summary_markdown(result):
    lines = ['## Manual Pages data result', '', f"Decision: {result['reason']}", '']
    if result.get('snapshot_id'):
        lines += [f"Snapshot: `{result['snapshot_id']}`", f"SHA-256: `{result.get('sha256', '')}`",
                  f"Package expires: `{result.get('expires_at', '')}`", '']
    if 'checks' in result:
        lines += [f"Content version: `{result['content_id']}`", f"State recovery: `{result.get('state_warning') or 'restored'}`", '',
                  '| Check | State | Reason | Retry count | Next due / retry (UTC) | Details |',
                  '| --- | --- | --- | --- | --- | --- |']
        for kind, check in sorted(result['checks'].items()):
            task = result['scheduler_state']['scheduler']['tasks'][kind]
            lines.append(f"| {kind} | {check['state']} | {check['reason']} | {task['consecutive_failures']} | "
                         f"{task['next_retry_at'] or task['next_due_at'] or ''} | {json.dumps(check.get('outcome', {}), sort_keys=True)} |")
        lines.append('')
    lines += ['### Product fetch results', '']
    lines += [f'- {name}: {state}' for name, state in sorted(result['products'].items())]
    lines += ['', '### Resource results', '', '| Resource | State | Changed | Failure/warning |',
              '| --- | --- | --- | --- |']
    for name, resource in sorted(result['resources'].items()):
        lines.append(f"| {name} | {resource['state']} | {resource['updated']} | {resource['error_code'] or ''} |")
    lines += ['', 'States: updated / retained / no_data / incomplete_history.',
              'Incomplete histories may also contain successfully updated slots. JSON does not archive image bodies.', '']
    return '\n'.join(lines)
