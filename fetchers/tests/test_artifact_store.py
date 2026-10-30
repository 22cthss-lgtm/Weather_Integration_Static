import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def outer(inner=b'inner', extra=None):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as archive:
        archive.writestr('weather-snapshot.zip', inner)
        if extra:
            archive.writestr(*extra)
    return result.getvalue()


class Response:
    def __init__(self, status=200, body=b'', headers=None):
        self.status_code = status
        self.content = body
        self.headers = headers or {}

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        pass


class ArtifactTests(unittest.TestCase):
    def client(self, responses, **kwargs):
        from src.artifact_store import GitHubArtifactClient
        self.calls = []
        def transport(method, url, **options):
            self.calls.append((method, url, options))
            return responses.pop(0)
        return GitHubArtifactClient('owner/repo', 'secret', transport=transport,
                                    sleep=lambda _: None, **kwargs)

    def test_digest_before_inner_validation_and_no_redirect_auth(self):
        blob = outer()
        record = {'id': 10, 'name': 'weather-snapshot', 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest()}
        client = self.client([Response(body=json.dumps(record).encode()), Response(302, headers={'Location': 'https://productionresult.blob.core.windows.net/file?signed=1'}), Response(body=blob)])
        self.assertEqual(client.download_artifact(record), b'inner')
        self.assertNotIn('Authorization', self.calls[2][2]['headers'])
        self.assertFalse(self.calls[0][2]['allow_redirects'])
        from src.artifact_store import ArtifactError
        client = self.client([Response(body=json.dumps(dict(record, digest='sha256:' + '0' * 64)).encode()), Response(body=blob)])
        with self.assertRaises(ArtifactError):
            client.download_artifact(dict(record, digest='sha256:' + '0' * 64))
        client = self.client([Response(body=b'{"id":10,"name":"weather-snapshot"}')])
        with self.assertRaises(ArtifactError):
            client.download_artifact({'id': 10, 'name': 'weather-snapshot'})
        self.assertEqual(len(self.calls), 1)

    def test_outer_inventory_and_limits(self):
        from src.artifact_store import ArtifactError
        for extra in [('../escape', 'x'), ('snapshot-info.json', '{"token":"x"}')]:
            blob = outer(extra=extra)
            record = {'id': 1, 'name': 'weather-snapshot', 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest()}
            client = self.client([Response(body=json.dumps(record).encode()), Response(body=blob)])
            with self.assertRaises(ArtifactError):
                client.download_artifact({'id': 1, 'name': 'weather-snapshot', 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest()})
        client = self.client([Response(body=b'12345')], max_bytes=4)
        with self.assertRaises(ArtifactError):
            client.get_run(1)

    def test_retry_and_delete_are_bounded_and_fail_closed(self):
        from src.artifact_store import ArtifactError
        client = self.client([Response(503), Response(503), Response(503)])
        with self.assertRaises(ArtifactError):
            client.get_run(1)
        self.assertEqual(len(self.calls), 3)
        client = self.client([Response(403)])
        with self.assertRaises(ArtifactError):
            client.get_run(1)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(client.delete_artifact(9))
        self.assertEqual(len(self.calls), 1)

    def test_recovery_validates_run_and_orders_content_not_upload(self):
        from src.artifact_store import recover_snapshot
        class Client:
            def list_artifacts(self, name):
                return [{'id': n, 'name': name, 'workflow_run': {'id': n}} for n in [1, 2, 3, 4]]
            def get_run(self, n):
                return {'path': '.github/workflows/weather.yml', 'head_branch': 'main',
                        'event': 'pull_request' if n == 4 else 'workflow_dispatch',
                        'status': 'completed', 'conclusion': 'failure'}
            def download_artifact(self, record):
                if record['id'] == 1:
                    raise ValueError('corrupt')
                return str(record['id']).encode()
        seen = []
        def validate(blob, target):
            seen.append(blob)
            return {'content_id': 'same' if blob in (b'2', b'3') else 'other',
                    'content_created_at': '2026-10-0' + ('2' if blob == b'2' else '3') + 'T00:00:00Z'}
        result = recover_snapshot(Client(), validate, 'target', workflow='.github/workflows/weather.yml', default_branch='main')
        self.assertEqual(result['artifact']['id'], 2)
        self.assertEqual(result['metadata']['content_created_at'], '2026-10-02T00:00:00Z')
        self.assertEqual(seen, [b'2', b'3'])

    def test_cleanup_distinct_versions_online_state_and_gate(self):
        from src.artifact_store import cleanup_plan
        records = [{'id': n, 'name': 'weather-snapshot', 'content_id': str(n),
                    'content_created_at': f'2026-10-{n:02d}T00:00:00Z', 'verified': True} for n in range(1, 9)]
        records += [dict(records[-1], id=99), {'id': 100, 'name': 'unrelated'}]
        records += [{'id': 200 + n, 'name': 'weather-scheduler-state', 'verified': True,
                     'created_at': f'2026-10-{n:02d}T00:00:00Z'} for n in range(1, 5)]
        args = (records, '1', '8', True, True)
        self.assertEqual(set(cleanup_plan(*args)), {2, 3, 99, 201, 202})
        self.assertEqual(cleanup_plan(records, None, '8', True, True), [])
        self.assertEqual(cleanup_plan(records, '1', '8', False, True), [])
        self.assertEqual(cleanup_plan(records, 'missing', '8', True, True), [])
        self.assertNotIn(99, cleanup_plan(*args, protected_artifact_ids=[99]))

    def test_metadata_from_caller_cannot_supply_digest(self):
        from src.artifact_store import ArtifactError
        blob = outer()
        client = self.client([Response(body=b'{"id":1,"name":"weather-snapshot"}')])
        with self.assertRaises(ArtifactError):
            client.download_artifact({'id': 1, 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest()})
        self.assertEqual(len(self.calls), 1)

    def test_listing_limits_and_delete_only_checked_repo_ids(self):
        records = [{'id': 1, 'name': 'weather-snapshot', 'expired': False},
                   {'id': 2, 'name': 'other'}, {'id': 3, 'name': 'weather-snapshot', 'expired': True}]
        client = self.client([Response(body=json.dumps({'artifacts': records}).encode()), Response(204)])
        self.assertEqual([r['id'] for r in client.list_artifacts()], [1])
        self.assertFalse(client.delete_artifact(2))
        self.assertTrue(client.delete_artifact(1))
        self.assertTrue(all('/repos/owner/repo/actions/' in call[1] for call in self.calls))

    def test_run_metadata_repo_mismatch_and_redirect_limit(self):
        from src.artifact_store import ArtifactError
        client = self.client([Response(body=b'{"repository":{"full_name":"evil/repo"}}')])
        with self.assertRaises(ArtifactError):
            client.get_run(1)
        record = {'id': 1, 'name': 'weather-snapshot', 'digest': 'sha256:' + '0' * 64}
        responses = [Response(body=json.dumps(record).encode())]
        responses += [Response(302, headers={'Location': 'https://productionresult.blob.core.windows.net/path'}) for _ in range(4)]
        client = self.client(responses)
        with self.assertRaises(ArtifactError):
            client.download_artifact(record)
        self.assertEqual(len(self.calls), 5)
        self.assertTrue(all('Authorization' not in call[2]['headers'] for call in self.calls[2:]))

    def test_duplicate_content_does_not_get_new_version_timestamp(self):
        from src.artifact_store import cleanup_plan
        records = [{'id': n, 'name': 'weather-snapshot', 'content_id': str(n),
                    'content_created_at': f'2026-10-{n:02d}T00:00:00Z', 'verified': True} for n in range(1, 9)]
        records.append(dict(records[0], id=99, content_created_at='2026-10-29T00:00:00Z'))
        deletions = cleanup_plan(records, '8', '8', True, True)
        self.assertEqual(set(deletions), {1, 2, 3, 99})
        records.append({'id': 100, 'name': 'weather-snapshot', 'verified': False})
        self.assertEqual(cleanup_plan(records, '8', '8', True, True), [])

    def test_recovery_bounds_failed_candidates_and_uses_older_fallback(self):
        from src.artifact_store import recover_snapshot, ArtifactError
        class Client:
            count = 0
            def list_artifacts(self, name):
                return [{'id': n, 'workflow_run': {'id': n}} for n in range(1, 20)]
            def get_run(self, n):
                return {'path': 'workflow', 'head_branch': 'main', 'event': 'schedule', 'status': 'completed'}
            def download_artifact(self, record):
                self.count += 1
                if record['id'] != 2:
                    raise ArtifactError('bad download')
                return b'valid older content'
        client = Client()
        result = recover_snapshot(client, lambda blob, target: {'content_id': 'old', 'content_created_at': '2026-01-01T00:00:00Z'},
                                  None, workflow='workflow', default_branch='main', max_failed_versions=2)
        self.assertEqual(result['metadata']['content_id'], 'old')
        self.assertEqual(client.count, 3)

    def test_malformed_remote_or_callback_metadata_is_rejected(self):
        from src.artifact_store import ArtifactError, cleanup_plan
        client = self.client([Response(body=b'{"artifacts":[null]}')])
        with self.assertRaises(ArtifactError):
            client.list_artifacts()
        records = [{'id': 1, 'name': 'weather-snapshot', 'verified': True,
                    'content_id': 'same', 'content_created_at': 123}]
        self.assertEqual(cleanup_plan(records, 'same', 'same', True, True), [])

    def test_state_download_readback_and_redirect_host_restriction(self):
        from src.artifact_store import ArtifactError
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('scheduler-state.json', '{"safe":true}')
        blob = raw.getvalue()
        record = {'id': 1, 'name': 'weather-scheduler-state', 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest()}
        client = self.client([Response(body=json.dumps(record).encode()), Response(body=blob)])
        self.assertEqual(client.get_metadata(1), record)
        self.assertEqual(client.download_state(record), b'{"safe":true}')
        client = self.client([Response(body=json.dumps(record).encode()), Response(302, headers={'Location': 'https://evil.example/download'})])
        with self.assertRaises(ArtifactError):
            client.download_state(record)
        self.assertEqual(len(self.calls), 2)

    def test_retry_after_global_budget_and_permission_failfast(self):
        from src.artifact_store import ArtifactError, ArtifactPermissionError, recover_snapshot
        ticks = [0]
        waits = []
        def sleep(delay):
            waits.append(delay)
            ticks[0] += delay
        client = self.client([Response(503, headers={'Retry-After': '999'}), Response(503), Response(503)],
                             clock=lambda: ticks[0], total_timeout=31)
        client._sleep = sleep
        with self.assertRaises(ArtifactError):
            client.get_run(1)
        self.assertEqual(waits, [30])
        self.assertEqual(len(self.calls), 2)
        class Client:
            count = 0
            def list_artifacts(self, name):
                return [{'workflow_run': {'id': 1}}] * 12
            def get_run(self, run_id):
                self.count += 1
                raise ArtifactPermissionError('denied')
        client = Client()
        with self.assertRaises(ArtifactPermissionError):
            recover_snapshot(client, None, None, workflow='a', default_branch='main')
        self.assertEqual(client.count, 1)

    def test_trusted_workflow_default_branch_suffixes(self):
        from src.artifact_store import trusted_run
        for suffix in ('', '@main', '@refs/heads/main'):
            run = {'path': 'workflow' + suffix, 'head_branch': 'main', 'event': 'schedule', 'status': 'completed'}
            self.assertTrue(trusted_run(run, 'workflow', 'main'))
        run['path'] = 'workflow@evil'
        self.assertFalse(trusted_run(run, 'workflow', 'main'))

    def test_state_limit_inventory_and_fresh_metadata(self):
        from src.artifact_store import ArtifactError
        for size, filename in ((1024 * 1024 + 1, 'scheduler-state.json'), (1, 'weather-snapshot.zip')):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(filename, b'x' * size)
            blob = raw.getvalue()
            record = {'id': 1, 'name': 'weather-scheduler-state', 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest()}
            client = self.client([Response(body=json.dumps(record).encode()), Response(body=blob)])
            with self.assertRaises(ArtifactError):
                client.download_state(record)
        client = self.client([Response(body=b'{"id":1,"name":"weather-snapshot","digest":"old"}'),
                              Response(body=b'{"id":1,"name":"weather-snapshot","digest":"new"}')])
        self.assertEqual(client.get_metadata(1)['digest'], 'old')
        self.assertEqual(client.get_metadata(1)['digest'], 'new')
        self.assertEqual(len(self.calls), 2)

    def test_workflow_run_listing_is_bounded_without_event_filter(self):
        client = self.client([Response(body=json.dumps({'workflow_runs': [{'run_number': 9}] * 100}).encode())] * 3)
        self.assertEqual(len(client.list_workflow_runs('.github/workflows/pages-manual.yml', 'main')), 300)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all('/workflows/pages-manual.yml/runs?' in call[1] for call in self.calls))
        self.assertTrue(all('event=' not in call[1] for call in self.calls))


if __name__ == '__main__':
    unittest.main()
