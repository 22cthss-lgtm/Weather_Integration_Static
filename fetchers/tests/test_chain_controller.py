"""Offline relay failure paths; never dispatch to GitHub in tests."""
from datetime import datetime, timezone
from pathlib import Path
import io
from http.client import IncompleteRead
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chain_controller as chain


NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)


def record(identifier, workflow, title='', status='completed', **extra):
    return dict(id=identifier, path='.github/workflows/' + workflow,
                display_title=title, status=status, conclusion='success',
                head_branch='main', event='workflow_dispatch', run_attempt=1,
                created_at=NOW.isoformat(), **extra)


class FakeAPI:
    def __init__(self):
        self.active = True
        self.rows = [record(10, chain.RELAY, 'Relay seed', 'in_progress')]
        self.rows[0]['event'] = 'schedule'
        self.posts = []
        self.lost_response = False
        self.absent_response = False
        self.incomplete = False
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path))
        parsed = urlsplit(path)
        if parsed.path.endswith('/dispatches'):
            self.posts.append((path, payload))
            workflow = parsed.path.split('/')[-2]
            inputs = payload['inputs']
            title = ('Pages chain ' + inputs['chain_request_id'] if workflow == chain.PUBLISH
                     else 'Relay ' + inputs['relay_request_id'])
            item = record(100 + len(self.posts), workflow, title, 'queued')
            if not self.absent_response:
                self.rows.append(item)
            if self.lost_response:
                raise chain.RelayError('transport_unknown')
            return {'workflow_run_id': item['id']}
        if '/runs/' in parsed.path:
            return next(r.copy() for r in self.rows if r['id'] == int(parsed.path.split('/')[-1]))
        if parsed.path.endswith('/runs'):
            workflow = parsed.path.split('/')[-2]
            query = parse_qs(parsed.query)
            rows = [r.copy() for r in self.rows if r['path'].endswith('/' + workflow)]
            if 'status' in query:
                rows = [r for r in rows if r['status'] == query['status'][0]]
            if 'created' in query:
                since = datetime.fromisoformat(query['created'][0][2:].replace('Z', '+00:00'))
                rows = [r for r in rows if datetime.fromisoformat(r['created_at']) >= since]
            return {'total_count': len(rows) + int(self.incomplete), 'workflow_runs': rows}
        return {'path': '.github/workflows/' + chain.RELAY,
                'state': 'active' if self.active else 'disabled_manually'}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.elapsed = 0
        self.messages = []
        self.env = dict(GITHUB_REPOSITORY='owner/repo', DEFAULT_BRANCH='main',
                        GITHUB_REF='refs/heads/main', GITHUB_RUN_ID='10',
                        GITHUB_RUN_ATTEMPT='1', GITHUB_EVENT_NAME='schedule',
                        CHAIN_REQUEST_ID='', RELAY_REQUEST_ID='')
        self.controller = chain.Controller(self.api, self.env, clock=lambda: self.elapsed,
            sleep=self.sleep, now=lambda: NOW, report=lambda k, v: self.messages.append((k, v)))

    def sleep(self, seconds):
        self.assertLessEqual(seconds, 20)
        self.elapsed += seconds

    def publisher(self):
        self.env.update(GITHUB_RUN_ID='80', GITHUB_EVENT_NAME='workflow_dispatch',
                        CHAIN_REQUEST_ID='u10a1', SOURCE_MODE='auto', MODE='refresh', RETENTION_DAYS='7')
        self.api.rows.append(record(80, chain.PUBLISH, 'Pages chain u10a1', 'in_progress'))

    def test_normal_round_has_explicit_inputs_and_next_parent(self):
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 2)
        self.assertEqual(self.api.posts[0][1], {'ref': 'main', 'inputs': dict(
            snapshot_source='auto', mode='refresh', snapshot_retention_days='7', chain_request_id='u10a1')})
        self.assertEqual(self.api.posts[1][1]['inputs'], {'relay_request_id': 'r10a1'})
        self.assertEqual(self.elapsed, 600)
        self.assertTrue(any(k == 'next_relay' for k, _ in self.messages))

    def test_busy_does_not_enqueue_update_but_keeps_relay(self):
        self.api.rows.append(record(77, chain.PUBLISH, status='waiting'))
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 1)
        self.assertIn(chain.RELAY, self.api.posts[0][0])
        self.assertTrue(any(k == 'busy' for k, _ in self.messages))

    def test_old_busy_run_is_not_ignored(self):
        self.api.rows.append(record(77, chain.PUBLISH, status='queued'))
        self.api.rows[-1]['created_at'] = '2020-01-01T00:00:00+00:00'
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 1)

    def test_disabled_entry_never_dispatches(self):
        self.api.active = False
        with self.assertRaises(chain.Stopped):
            self.controller.relay()
        self.assertFalse(self.api.posts)

    def test_disabled_during_wait_never_dispatches_next(self):
        def stop(seconds):
            self.sleep(seconds)
            self.api.active = False
        self.controller.sleep = stop
        with self.assertRaises(chain.Stopped):
            self.controller.relay()
        self.assertEqual(len(self.api.posts), 1)
        self.assertLess(self.elapsed, 600)

    def test_cancel_during_wait_does_not_chain_in_finally(self):
        def cancel(_):
            raise KeyboardInterrupt()
        self.controller.sleep = cancel
        with self.assertRaises(KeyboardInterrupt):
            self.controller.relay()
        self.assertEqual(len(self.api.posts), 1)

    def test_stop_immediately_before_post(self):
        original = self.api.request
        def stop(method, path, payload=None):
            result = original(method, path, payload)
            if path.startswith('/actions/workflows/' + chain.PUBLISH + '/runs?'):
                self.api.active = False
            return result
        self.api.request = stop
        with self.assertRaises(chain.Stopped):
            self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertFalse(self.api.posts)

    def test_lost_response_reconciles_without_second_post(self):
        self.api.lost_response = True
        found = self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'),
                                         'Pages chain u10a1', NOW)
        self.assertEqual(found['id'], 101)
        self.assertEqual(len(self.api.posts), 1)

    def test_unknown_response_stops_without_resending(self):
        self.api.lost_response = self.api.absent_response = True
        with self.assertRaisesRegex(chain.RelayError, 'dispatch_unconfirmed'):
            self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertEqual(len(self.api.posts), 1)
        self.assertLess(self.elapsed, 30)

    def test_existing_request_reused_without_post(self):
        self.api.rows.append(record(79, chain.PUBLISH, 'Pages chain u10a1'))
        result = self.controller.dispatch(chain.PUBLISH, {}, 'Pages chain u10a1', NOW)
        self.assertEqual(result['id'], 79)
        self.assertFalse(self.api.posts)

    def test_manual_arrives_during_dispatch_preflight(self):
        original = self.api.request
        def arrival(method, path, payload=None):
            result = original(method, path, payload)
            if '/runs?' in path and 'created=' in path and not self.api.posts:
                if not any(row['id'] == 76 for row in self.api.rows):
                    self.api.rows.append(record(76, chain.PUBLISH, 'manual', 'pending'))
            return result
        self.api.request = arrival
        with self.assertRaises(chain.Busy):
            self.controller.dispatch(chain.PUBLISH, {}, 'Pages chain u10a1', NOW)
        self.assertFalse(self.api.posts)

    def test_multiple_matching_requests_stop(self):
        for identifier in (78, 79):
            self.api.rows.append(record(identifier, chain.PUBLISH, 'Pages chain u10a1'))
        with self.assertRaises(chain.RelayError):
            self.controller.dispatch(chain.PUBLISH, {}, 'Pages chain u10a1', NOW)
        self.assertFalse(self.api.posts)

    def test_recent_auto_run_waits_before_new_fetch(self):
        self.api.rows.append(record(79, chain.PUBLISH, 'Pages chain u9a1'))
        self.api.rows[-1]['created_at'] = '2026-11-05T23:55:00+00:00'
        self.controller.relay()
        self.assertEqual(self.elapsed, 600)
        self.assertIn(('cadence_wait_seconds', 300.0), self.messages)

    def test_incomplete_query_stops_before_post(self):
        self.api.incomplete = True
        with self.assertRaises(chain.RelayError):
            self.controller.relay()
        self.assertFalse(self.api.posts)

    def test_manual_publisher_works_while_controller_disabled(self):
        self.api.active = False
        self.assertTrue(self.controller.admit())
        self.assertFalse(self.api.calls)

    def test_publisher_accepts_traceable_parent_and_checks_live_state(self):
        self.publisher()
        self.assertTrue(self.controller.admit())
        self.api.active = False
        with self.assertRaises(chain.Stopped):
            self.controller.admit()

    def test_disable_during_admission_query_stops_before_fetch(self):
        self.publisher()
        original = self.controller.matching
        def disable(*args):
            result = original(*args)
            self.api.active = False
            return result
        self.controller.matching = disable
        with self.assertRaises(chain.Stopped):
            self.controller.admit()

    def test_duplicate_and_rerun_are_rejected(self):
        self.publisher()
        self.api.rows.append(record(79, chain.PUBLISH, 'Pages chain u10a1'))
        with self.assertRaisesRegex(chain.Stopped, 'duplicate'):
            self.controller.admit()
        self.api.rows.pop()
        self.env['GITHUB_RUN_ATTEMPT'] = '2'
        with self.assertRaises(chain.Stopped):
            self.controller.admit()

    def test_auto_parent_wrong_branch_attempt_or_input_rejected(self):
        self.publisher()
        for key, value in [('MODE', 'publish'), ('SOURCE_MODE', 'explicit'), ('RETENTION_DAYS', '6'),
                           ('GITHUB_REF', 'refs/heads/other'), ('CHAIN_REQUEST_ID', 'u10a2')]:
            old = self.env[key]
            self.env[key] = value
            with self.subTest(key=key), self.assertRaises(chain.RelayError):
                self.controller.admit()
            self.env[key] = old

    def test_inconsistent_run_identity_is_rejected(self):
        original = self.api.request
        def inconsistent(method, path, payload=None):
            result = original(method, path, payload)
            if path == '/actions/runs/10':
                result['id'] = 11
            return result
        self.api.request = inconsistent
        with self.assertRaises(chain.RelayError):
            self.controller.relay()
        self.publisher()
        with self.assertRaises(chain.RelayError):
            self.controller.admit()

    def test_failed_prior_update_does_not_break_relay(self):
        self.api.rows.append(record(77, chain.PUBLISH, 'Pages chain old'))
        self.api.rows[-1]['conclusion'] = 'failure'
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 2)

    def test_nondefault_controller_never_dispatches(self):
        self.env['GITHUB_REF'] = 'refs/heads/other'
        with self.assertRaises(chain.RelayError):
            self.controller.relay()
        self.assertFalse(self.api.posts)

    def test_relay_parent_is_verified_not_just_printed(self):
        self.env['GITHUB_EVENT_NAME'] = 'workflow_dispatch'
        self.env['RELAY_REQUEST_ID'] = 'r9a1'
        self.api.rows[0].update(event='workflow_dispatch', display_title='Relay r9a1')
        self.api.rows.append(record(9, chain.RELAY, 'Relay seed 9'))
        self.api.rows[-1]['run_attempt'] = 2
        with self.assertRaises(chain.RelayError):
            self.controller.relay()
        self.assertFalse(self.api.posts)
        self.api.rows[-1]['run_attempt'] = 1
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 2)

    def test_source_entry_rechecks_after_admission_and_before_prepare(self):
        import refresh_pages
        env = dict(self.env, CHAIN_REQUEST_ID='u10a1', GH_TOKEN='test-token', MODE='refresh', CWA_API_KEY='test-only')
        with patch.dict(os.environ, env, clear=True), \
             patch.object(chain.Controller, 'admit', side_effect=chain.Stopped('controller_not_active')), \
             patch.object(refresh_pages, 'prepare_due') as prepare, \
             patch.object(chain, 'summary'), patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(refresh_pages.main(['prepare']), 1)
            prepare.assert_not_called()


class TransportTests(unittest.TestCase):
    def response(self, body=b'{}', status=200):
        response = Mock(status=status)
        response.read.return_value = body
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def client(self, effects):
        opener, sleep = Mock(), Mock()
        opener.open.side_effect = effects
        return chain.GitHub('owner/repo', 'test-only-token', opener=opener, sleep=sleep), opener, sleep

    def test_get_retries_exactly_three_and_post_never_retries(self):
        for method, count in [('GET', 3), ('POST', 1)]:
            api, opener, sleep = self.client([URLError('offline')] * 3)
            with self.subTest(method=method), self.assertRaises(chain.RelayError):
                api.request(method, '/actions/workflows/x')
            self.assertEqual(opener.open.call_count, count)
            self.assertEqual(sleep.call_count, count - 1)

    def test_429_and_5xx_are_bounded_but_403_not_retried(self):
        for status, count in [(429, 3), (503, 3), (403, 1)]:
            errors = [HTTPError('https://api.github.com/', status, 'error', {}, None) for _ in range(3)]
            api, opener, _ = self.client(errors)
            with self.subTest(status=status), self.assertRaises(chain.RelayError):
                api.request('GET', '/actions/workflows/x')
            self.assertEqual(opener.open.call_count, count)

    def test_read_retry_can_recover_and_uses_fixed_api_origin(self):
        api, opener, sleep = self.client([URLError('offline'), self.response()])
        self.assertEqual(api.request('GET', '/actions/workflows/x'), {})
        self.assertEqual(sleep.call_count, 1)
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.startswith('https://api.github.com/repos/owner/repo/actions/'))
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)

    def test_truncated_response_is_transport_failure_with_no_post_retry(self):
        for method, count in [('GET', 3), ('POST', 1)]:
            response = self.response()
            response.read.side_effect = IncompleteRead(b'partial', 100)
            api, opener, _ = self.client([response] * 3)
            with self.subTest(method=method), self.assertRaises(chain.RelayError):
                api.request(method, '/actions/workflows/x')
            self.assertEqual(opener.open.call_count, count)

    def test_oversized_corrupt_and_nonobject_responses_stop(self):
        for body in (b'x' * (chain.MAX_BODY + 1), b'invalid-json', b'[]'):
            api, opener, _ = self.client([self.response(body)])
            with self.assertRaises(chain.RelayError):
                api.request('GET', '/actions/workflows/x')
            self.assertEqual(opener.open.call_count, 1)

    def test_redirect_is_refused_without_forwarding_credentials(self):
        with self.assertRaises(chain.RelayError):
            chain.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid/')

    def test_manual_cli_and_output_write_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'output'
            env = dict(GITHUB_REPOSITORY='owner/repo', GITHUB_OUTPUT=str(output))
            with patch.dict(os.environ, env, clear=True), patch.object(chain, 'summary'), \
                 patch.object(chain.GitHub, 'request', side_effect=AssertionError('network forbidden')):
                self.assertEqual(chain.main(['admit']), 0)
                self.assertEqual(output.read_text(), 'allowed=true\n')
                os.environ['GITHUB_OUTPUT'] = folder
                self.assertEqual(chain.main(['admit']), 1)


if __name__ == '__main__':
    unittest.main()
