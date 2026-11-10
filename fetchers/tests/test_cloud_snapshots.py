from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
WORKFLOW = '.github/workflows/pages-manual.yml'


class Client:
    def __init__(self):
        self.records = [{'id': 1, 'name': 'weather-snapshot', 'workflow_run': {'id': 10}}]
        self.states = []
        self.deleted = []
        self.runs = []
        self.metadata = {'content_id': 'content', 'content_created_at': NOW.isoformat(), 'files': {'a': 'hash'}, 'snapshot_id': 'snapshot'}
    def list_artifacts(self, name):
        return self.records if name == 'weather-snapshot' else self.states
    def get_metadata(self, artifact_id):
        for record in self.records + self.states:
            if record['id'] == artifact_id:
                return record
        raise ValueError('missing artifact')
    def get_run(self, run_id):
        return {'id': run_id, 'path': WORKFLOW, 'head_branch': 'main', 'event': 'workflow_dispatch',
                'status': 'completed', 'conclusion': 'failure', 'run_number': 1}
    def download_artifact(self, record):
        return str(record['id']).encode()
    def download_state(self, record):
        return self.state_bytes
    def list_workflow_runs(self, workflow, branch, max_pages=3):
        return self.runs
    def delete_artifact(self, artifact_id):
        self.deleted.append(artifact_id)
        return True


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {'RUNNER_TEMP': str(self.root), 'DEFAULT_BRANCH': 'main', 'GITHUB_RUN_ID': '10',
                    'GITHUB_RUN_NUMBER': '5', 'GITHUB_SHA': 'abc', 'CONTENT_ID': 'content',
                    'DATA_ARTIFACT_ID': '1', 'STATE_ARTIFACT_ID': '2', 'NEW_SNAPSHOT': 'true', 'SITE_URL': 'https://site.example'}
        self.client = Client()
    def manager(self, **kwargs):
        from src.cloud_snapshots import CloudSnapshots
        def unpack(path, sha, target, now=None):
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), sha)
            return self.client.metadata.copy()
        return CloudSnapshots(self.client, self.env, now=NOW, unpack=unpack, **kwargs)
    def state(self, content_id='content', now=NOW):
        from src.scheduling import new_state
        return {'schema_version': 1, 'content_id': content_id, 'scheduler': new_state(content_id, now), 'history': {}}
    def install_state(self, state=None):
        self.client.states = [{'id': 2, 'name': 'weather-scheduler-state', 'created_at': NOW.isoformat(), 'workflow_run': {'id': 10}}]
        self.client.state_bytes = json.dumps(state or self.state()).encode()
    def result(self):
        result = dict(self.client.metadata, sha256=hashlib.sha256(b'1').hexdigest())
        (self.root / 'pages-input-result.json').write_text(json.dumps(result))
        return result
    def test_resolve_digest_chain_and_optional_state(self):
        self.install_state()
        result = self.manager().resolve()
        self.assertEqual(result['artifact_id'], 1)
        self.assertEqual((self.root / 'pages-input/weather-snapshot.zip').read_bytes(), b'1')
        self.assertEqual(json.loads((self.root / 'source-state.json').read_text()), self.state())

    def test_resolve_validates_bounded_candidates_and_uses_latest_saved_at(self):
        old = self.state(now=NOW-timedelta(minutes=20))
        latest = self.state(now=NOW-timedelta(minutes=1))
        blobs = {2: json.dumps(old).encode(), 3: b'broken', 4: json.dumps(self.state('other')).encode(),
                 5: json.dumps(latest).encode()}
        self.client.states = [{'id': n, 'name': 'weather-scheduler-state', 'workflow_run': {'id': 10}}
                              for n in range(2, 20)]
        seen = []
        def download(record):
            seen.append(record['id'])
            return blobs.get(record['id'], b'broken')
        with patch.object(self.client, 'download_state', side_effect=download):
            result = self.manager().resolve()
        self.assertEqual(json.loads((self.root/'source-state.json').read_text()), latest)
        self.assertEqual(len(seen), 12)
        self.assertEqual(result['state_artifact_id'], 5)

    def test_state_selection_uses_instant_not_id_upload_order_or_offset_text(self):
        earlier = self.state(now=NOW-timedelta(minutes=2))
        latest = self.state(now=NOW-timedelta(minutes=1))
        latest['scheduler']['saved_at'] = (NOW-timedelta(minutes=1)).astimezone(timezone(timedelta(hours=-5))).isoformat()
        self.client.states = [{'id': n, 'workflow_run': {'id': 10}} for n in (99, 2)]
        with patch.object(self.client, 'download_state', side_effect=[json.dumps(earlier).encode(), json.dumps(latest).encode()]):
            self.manager().resolve()
        self.assertEqual(json.loads((self.root/'source-state.json').read_text()), latest)

    def test_online_marker_requires_trusted_run_and_verified_content_order(self):
        self.client.metadata['content_id']='a'*64
        marker={'schema_version':1,'content_id':'a'*64,'code_sha':'b'*40,'run_id':'3','run_number':'3'}
        run=dict(self.client.get_run(3),id=3,run_number=3,head_sha='b'*40)
        with patch.object(self.client,'get_run',return_value=run):
            result=self.manager(public_get=lambda url:marker).deployment()
            self.assertEqual(result['state'],'verified')
            self.assertEqual(result['content_created_at'],self.client.metadata['content_created_at'])
            marker['run_number']='7'; run['run_number']=7
            self.assertEqual(self.manager(public_get=lambda url:marker).deployment()['state'],'newer_run')
            marker['run_number']='3'; run['run_number']=3
            marker['content_id']='c'*64
            self.assertEqual(self.manager(public_get=lambda url:marker).deployment()['state'],'version_unknown')
            marker['code_sha']='d'*40
            self.assertEqual(self.manager(public_get=lambda url:marker).deployment()['state'],'untrusted')
        self.assertEqual(json.loads((self.root/'online-deployment.json').read_text())['state'],'untrusted')

    def test_unknown_or_invalid_online_marker_never_becomes_verified(self):
        for index,marker in enumerate((None,{},[],{'schema_version':True}, {'content_id':'secret'})):
            with self.subTest(marker=marker):
                self.env['RUNNER_TEMP']=str(self.root/f'case-{index}')
                self.assertIn(self.manager(public_get=lambda url:marker).deployment()['state'],('unavailable','invalid'))
        import requests
        with patch.object(self.client,'get_run') as get:
            def unavailable(url): raise requests.Timeout('PRIVATE')
            self.assertEqual(self.manager(public_get=unavailable).deployment(),{'state':'unavailable'})
            get.assert_not_called()

    def test_state_write_failure_does_not_overwrite_prior_source_state(self):
        self.install_state()
        target=self.root/'source-state.json';target.write_bytes(b'prior-valid')
        from src.cloud_snapshots import _write_json
        def fail(path,document):
            if Path(path)==target: raise PermissionError('write denied')
            return _write_json(path,document)
        with patch('src.cloud_snapshots._write_json',side_effect=fail):
            with self.assertRaises(PermissionError): self.manager().resolve()
        self.assertEqual(target.read_bytes(),b'prior-valid')
    def test_corrupt_expired_and_mismatched_state_reset(self):
        for state in [self.state('other'), self.state(now=NOW - timedelta(days=8)), dict(self.state(), secret='never persist')]:
            self.install_state(state)
            self.manager().resolve()
            self.assertEqual(json.loads((self.root / 'source-state.json').read_text()), {})
    def test_resolve_has_no_hidden_fallback(self):
        self.client.records = []
        with self.assertRaises(ValueError):
            self.manager().resolve()
    def test_verify_data_compares_saved_manifest_and_identity(self):
        self.result()
        result = self.manager().verify_data()
        self.assertEqual(result['artifact_id'], 1)
        self.client.metadata['files'] = {'other': 'different'}
        with self.assertRaises(ValueError):
            self.manager().verify_data()
    def test_verify_state_requires_exact_bytes_and_safe_envelope(self):
        self.install_state()
        local = self.root / 'pages-work/state/scheduler-state.json'
        local.parent.mkdir(parents=True)
        local.write_bytes(self.client.state_bytes)
        self.assertEqual(self.manager().verify_state()['artifact_id'], 2)
        local.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.manager().verify_state()
    def _flaky(self, method, failures):
        """Make a client method raise each given error once, then behave normally."""
        original = getattr(self.client, method)
        pending = list(failures)
        def call(*args):
            if pending:
                raise pending.pop(0)
            return original(*args)
        setattr(self.client, method, call)

    def _install_local_state(self):
        self.install_state()
        local = self.root / 'pages-work/state/scheduler-state.json'
        local.parent.mkdir(parents=True)
        local.write_bytes(self.client.state_bytes)

    def test_fresh_upload_404_or_missing_digest_is_reread_then_verified(self):
        # Runs #342/#344/#381/#384 (2026-11-08/09) failed ~0.4 s after upload finalized.
        from src.artifact_store import ArtifactError
        from src.cloud_snapshots import READBACK_RETRY_DELAYS
        self._install_local_state()
        self.result()
        sleeps = []
        self._flaky('get_metadata', [ArtifactError('GitHub request failed (HTTP 404)')])
        self._flaky('download_state', [ArtifactError('Missing trusted artifact digest')])
        self.assertEqual(self.manager(sleep=sleeps.append).verify_state()['artifact_id'], 2)
        self.assertEqual(sleeps, list(READBACK_RETRY_DELAYS[:2]))
        sleeps.clear()
        self._flaky('download_artifact', [ArtifactError('Artifact transport failed')])
        self.assertEqual(self.manager(sleep=sleeps.append).verify_data()['artifact_id'], 1)
        self.assertEqual(sleeps, [READBACK_RETRY_DELAYS[0]])

    def test_persistent_unavailable_readback_is_bounded_and_stops(self):
        from src.artifact_store import ArtifactError
        from src.cloud_snapshots import READBACK_RETRY_DELAYS
        self._install_local_state()
        sleeps = []
        self._flaky('get_metadata', [ArtifactError('GitHub request failed (HTTP 404)')] * 10)
        with self.assertRaises(ArtifactError):
            self.manager(sleep=sleeps.append).verify_state()
        self.assertEqual(sleeps, list(READBACK_RETRY_DELAYS))
        sleeps.clear()
        self._flaky('get_metadata', [ArtifactError('Artifact client time budget exhausted')])
        with self.assertRaisesRegex(ArtifactError, 'time budget'):
            self.manager(sleep=sleeps.append).verify_state()
        self.assertEqual(sleeps, [])

    def test_readback_never_retries_mismatch_permission_or_untrusted_run(self):
        from src.artifact_store import ArtifactPermissionError
        self._install_local_state()
        self.result()
        sleeps = []
        (self.root / 'pages-work/state/scheduler-state.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.manager(sleep=sleeps.append).verify_state()
        self.client.metadata['files'] = {'other': 'different'}
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.manager(sleep=sleeps.append).verify_data()
        self._flaky('download_artifact', [ArtifactPermissionError('denied')])
        with self.assertRaises(ArtifactPermissionError):
            self.manager(sleep=sleeps.append).verify_data()
        self.client.get_run = lambda run_id: {'path': 'other.yml'}
        with self.assertRaisesRegex(ValueError, 'not trusted'):
            self.manager(sleep=sleeps.append).verify_state()
        self.assertEqual(sleeps, [])

    def test_cleanup_gets_larger_bounded_client_budget(self):
        import manage_snapshots
        env = dict(self.env, GITHUB_REPOSITORY='owner/repo', GH_TOKEN='x')
        budgets = {}
        for command in ('cleanup', 'verify-state'):
            with patch.object(manage_snapshots, 'GitHubArtifactClient') as client, \
                    patch.object(manage_snapshots.CloudSnapshots, command.replace('-', '_'), return_value={}):
                self.assertEqual(manage_snapshots.main([command], env=env), 0)
                budgets[command] = client.call_args.kwargs['total_timeout']
        self.assertEqual(budgets, {'cleanup': 300, 'verify-state': 120})

    def test_cli_reports_fixed_reason_but_never_values(self):
        import manage_snapshots
        import io
        from src.artifact_store import ArtifactError
        cases = [(ArtifactError('GitHub request failed (HTTP 404)'), 'ArtifactError: GitHub request failed (HTTP 404)'),
                 (ValueError('Saved state readback differs from prepared state'),
                  'ValueError: Saved state readback differs from prepared state'),
                 (ValueError('ghp1234567890abcdefTOKEN'), 'ValueError'),
                 (ValueError('Bearer ghp1234567890abcdef0123456789abcdef01234567'), 'ValueError'),
                 (ValueError('/home/runner/work/secret path'), 'ValueError'),
                 (ArtifactError('Artifact client time budget exhausted'),
                  'ArtifactError: Artifact client time budget exhausted'),
                 (ValueError("Invalid isoformat string: 'x'"), 'ValueError'),
                 (ValueError('see https://example.invalid/x?sig=abc'), 'ValueError'),
                 (OSError(2, 'No such file', '/runner/temp/secret path'), 'FileNotFoundError'),
                 (KeyError('GH_TOKEN'), 'KeyError')]
        for error, expected in cases:
            stderr = io.StringIO()
            with patch.object(manage_snapshots.CloudSnapshots, 'verify_state', side_effect=error):
                with patch('sys.stderr', stderr):
                    self.assertEqual(manage_snapshots.main(['verify-state'], env=self.env, client=self.client), 1)
            self.assertIn('Failure reason: ' + expected + '\n', stderr.getvalue())
            self.assertNotIn('ghp1234', stderr.getvalue())
            self.assertNotIn('secret path', stderr.getvalue())

    def test_guard_blocks_later_success_across_events(self):
        self.client.runs = [dict(self.client.get_run(11), run_number=6, conclusion='success', event='schedule')]
        with self.assertRaises(ValueError):
            self.manager().guard()
        self.client.runs[0]['conclusion'] = 'failure'
        self.manager().guard()
        self.client.runs[0].update(conclusion='success', event='push')
        with self.assertRaises(ValueError):
            self.manager().guard()

    def test_cleanup_preserves_explicit_saved_artifact_and_state_only_mode(self):
        marker = {'schema_version': 1, 'content_id': 'content', 'code_sha': 'abc', 'run_id': 10, 'run_number': 5}
        self.client.records.append(dict(self.client.records[0], id=9))
        self.env['DATA_ARTIFACT_ID'] = '9'
        self.assertEqual(self.manager(public_get=lambda url: marker).cleanup()['deleted'], [1])
        self.client.deleted.clear()
        self.env['NEW_SNAPSHOT'] = 'false'
        self.install_state()
        self.client.states += [dict(self.client.states[0], id=n) for n in (3, 4)]
        self.assertEqual(self.manager().cleanup()['deleted'], [4])
        self.assertNotIn(1, self.client.deleted)

    def test_marker_mismatch_and_corrupt_state_never_authorize_deletes(self):
        self.client.records.append(dict(self.client.records[0], id=9))
        self.install_state(dict(self.state(), secret='sensitive'))
        marker = {'schema_version': 1, 'content_id': 'content', 'code_sha': 'old', 'run_id': 10, 'run_number': 5}
        self.assertEqual(self.manager(public_get=lambda url: marker).cleanup()['deleted'], [])
        self.assertEqual(self.client.deleted, [])

    def test_state_history_schema_rejects_nested_unknown_fields(self):
        from src.cloud_snapshots import validate_state
        state = self.state()
        state['history'] = {'radar': {'2026-10-29': {'00:00': {
            'classification': 'pending', 'attempts': 0, 'last_attempt_at': None,
            'next_retry_at': None, 'secret': 'x'}}}}
        with self.assertRaises(ValueError):
            validate_state(json.dumps(state).encode(), 'content', NOW)

    def test_permission_failure_does_not_silently_reset_state(self):
        from src.artifact_store import ArtifactPermissionError
        self.install_state()
        with patch.object(self.client, 'download_state', side_effect=ArtifactPermissionError('denied')):
            with self.assertRaises(ArtifactPermissionError):
                self.manager().resolve()

    def test_resolution_outputs_small_safe_metadata(self):
        output = self.root / 'outputs.txt'
        self.env['GITHUB_OUTPUT'] = str(output)
        self.manager().resolve()
        lines = output.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn('snapshot_artifact_id=1', lines)
        self.assertIn('content_id=content', lines)

    def test_cli_failure_redacts_exception_and_credentials(self):
        import manage_snapshots
        import io
        stderr = io.StringIO()
        with patch.object(manage_snapshots.CloudSnapshots, 'resolve', side_effect=ValueError('secret-token')):
            with patch('sys.stderr', stderr):
                self.assertEqual(manage_snapshots.main(['resolve'], env=self.env, client=self.client), 1)
        self.assertNotIn('secret-token', stderr.getvalue())

    def test_real_package_through_api_digest_to_shared_unpack(self):
        import io
        import zipfile
        from src.artifact_store import GitHubArtifactClient
        from src.cloud_snapshots import CloudSnapshots
        from src.pages_package import pack_snapshot
        from src.snapshots import export_snapshot
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
        snapshot = self.root / 'snapshot'
        export_snapshot(source, snapshot)
        package_path = self.root / 'valid.zip'
        pack_snapshot(snapshot, package_path, now=NOW)
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('weather-snapshot.zip', package_path.read_bytes())
        outer = raw.getvalue()
        record = dict(self.client.records[0], digest='sha256:' + hashlib.sha256(outer).hexdigest())
        class Response:
            status_code = 200
            headers = {}
            def __init__(self, body):
                self.body = body
            def iter_content(self, chunk_size):
                yield self.body
            def close(self):
                pass
        run = dict(self.client.get_run(10), repository={'full_name': 'owner/repo'})
        responses = [Response(json.dumps({'artifacts': [record]}).encode()), Response(json.dumps(run).encode()),
                     Response(outer), Response(b'{"artifacts":[]}')]
        client = GitHubArtifactClient('owner/repo', 'never-log', transport=lambda *a, **kw: responses.pop(0))
        result = CloudSnapshots(client, self.env, now=NOW).resolve()
        self.assertEqual(result['sha256'], hashlib.sha256(package_path.read_bytes()).hexdigest())
        self.assertEqual(len(result['content_id']), 64)
        self.assertEqual(responses, [])
    def test_cleanup_marker_and_readback_gates(self):
        marker = {'schema_version': 1, 'content_id': 'content', 'code_sha': 'abc', 'run_id': 10, 'run_number': 5}
        self.client.records += [{'id': n, 'name': 'weather-snapshot', 'workflow_run': {'id': 10}} for n in range(3, 9)]
        self.env.pop('DATA_ARTIFACT_ID')
        manager = self.manager(public_get=lambda url: marker)
        result = manager.cleanup()
        self.assertEqual(result['deleted'], [])
        self.assertEqual(self.client.deleted, [])
        self.env['DATA_ARTIFACT_ID'] = '1'
        self.assertEqual(set(manager.cleanup()['deleted']), set(range(3, 9)))


if __name__ == '__main__':
    unittest.main()
