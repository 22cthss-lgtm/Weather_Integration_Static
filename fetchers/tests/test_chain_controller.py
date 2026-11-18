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
        self.incomplete_reads = 0   # Transiently inconsistent listings before recovery.
        self.hidden_reads = 0       # Filtered listings that do not yet show a new dispatch.
        self.overflow = False
        self.calls = []
        self.return_run_id = False  # POST body carries workflow_run_id (newer API behaviour).
        self.hidden_ids = set()     # Created runs that filtered listings never show.
        self.id_404_reads = 0       # By-ID reads that 404 before the run becomes readable.
        self.failed_posts = set()   # Workflows whose POST fails and creates nothing.

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
            if workflow in self.failed_posts:
                raise chain.RelayError('api_transport_or_retry_exhausted')
            if not self.absent_response:
                self.rows.append(item)
            if self.lost_response:
                raise chain.RelayError('transport_unknown')
            return {'workflow_run_id': item['id']} if self.return_run_id else None
        if '/runs/' in parsed.path:
            identifier = int(parsed.path.split('/')[-1])
            if identifier > 100 and self.id_404_reads:
                self.id_404_reads -= 1
                raise chain.RelayError('api_http_404')
            found = [r.copy() for r in self.rows if r['id'] == identifier]
            if not found:
                raise chain.RelayError('api_http_404')
            return found[0]
        if parsed.path.endswith('/runs'):
            workflow = parsed.path.split('/')[-2]
            query = parse_qs(parsed.query)
            rows = [r.copy() for r in self.rows if r['path'].endswith('/' + workflow)]
            if 'status' in query:
                rows = [r for r in rows if r['status'] == query['status'][0]]
            if 'created' in query:
                since = datetime.fromisoformat(query['created'][0][2:].replace('Z', '+00:00'))
                rows = [r for r in rows if datetime.fromisoformat(r['created_at']) >= since]
                if self.posts and self.hidden_reads:
                    self.hidden_reads -= 1
                    rows = [r for r in rows if r['id'] <= 100]
                rows = [r for r in rows if r['id'] not in self.hidden_ids]
            if self.overflow:
                return {'total_count': 101, 'workflow_runs': rows}
            extra = int(self.incomplete)
            if self.incomplete_reads:
                self.incomplete_reads -= 1
                extra = 1
            return {'total_count': len(rows) + extra, 'workflow_runs': rows}
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
                        CHAIN_REQUEST_ID='u10a1', SOURCE_MODE='auto', MODE='refresh', RETENTION_DAYS='15')
        self.api.rows.append(record(80, chain.PUBLISH, 'Pages chain u10a1', 'in_progress'))

    def test_retention_constant_matches_confirmed_policy(self):
        import json
        policy = json.loads((Path(__file__).resolve().parents[1] / 'policies/due-runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(chain.RETENTION_DAYS, str(policy['artifact_retention_days']))
        self.assertEqual(policy['artifact_retention_days'], policy['zip_valid_days'])

    def test_old_seven_day_chain_inputs_are_rejected(self):
        self.publisher()
        self.env['RETENTION_DAYS'] = '7'
        with self.assertRaisesRegex(chain.RelayError, 'invalid_chain_inputs'):
            self.controller.admit()

    def test_normal_round_has_explicit_inputs_and_next_parent(self):
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 2)
        self.assertEqual(self.api.posts[0][1], {'ref': 'main', 'inputs': dict(
            snapshot_source='auto', mode='refresh', snapshot_retention_days='15', chain_request_id='u10a1')})
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
        self.assertEqual(self.elapsed, sum(chain.RECONCILE_DELAYS))
        self.assertLessEqual(self.elapsed, 60)

    def test_slow_listing_after_successful_post_is_confirmed_without_resend(self):
        # Run #27 (2026-11-06): POST created the publisher, but the filtered listing
        # did not show it within the old ~6 second window, so the chain stopped.
        self.api.hidden_reads = 5
        found = self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'),
                                         'Pages chain u10a1', NOW)
        self.assertEqual(found['id'], 101)
        self.assertEqual(len(self.api.posts), 1)
        self.assertEqual(self.elapsed, sum(chain.RECONCILE_DELAYS[:5]))
        self.assertIn(('dispatch_confirmed_after_reads', 6), self.messages)

    def test_slow_listing_relay_round_still_hands_off(self):
        self.api.hidden_reads = 3
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 2)
        self.assertTrue(any(k == 'next_relay' for k, _ in self.messages))

    def test_disable_during_reconcile_stops_without_resend(self):
        self.api.lost_response = self.api.absent_response = True
        original = self.sleep
        def stop(seconds):
            original(seconds)
            if self.elapsed >= 6:
                self.api.active = False
        self.controller.sleep = stop
        with self.assertRaises(chain.Stopped):
            self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertEqual(len(self.api.posts), 1)

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
        with self.assertRaisesRegex(chain.RelayError, 'incomplete_run_query'):
            self.controller.relay()
        self.assertFalse(self.api.posts)
        self.assertEqual(self.elapsed, sum(chain.LISTING_RETRY_DELAYS))

    def test_transiently_inconsistent_listing_is_reread_then_used(self):
        # Run #49 (2026-11-06): one listing reported total_count != rows and the
        # controller stopped immediately instead of re-reading.
        self.api.incomplete_reads = 2
        self.controller.relay()
        self.assertEqual(len(self.api.posts), 2)
        self.assertEqual(self.elapsed, 600)

    def test_overflowing_listing_is_not_retried(self):
        self.api.overflow = True
        with self.assertRaisesRegex(chain.RelayError, 'incomplete_run_query'):
            self.controller.relay()
        self.assertFalse(self.api.posts)
        self.assertEqual(self.elapsed, 0)

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

    def lagging_listing(self, misses, hidden=(80,)):
        """The first ``misses`` admission listings do not yet show ``hidden`` runs."""
        original = self.controller.matching
        calls = []
        def lagging(*args):
            calls.append(args)
            rows = original(*args)
            return [r for r in rows if r['id'] not in hidden] if len(calls) <= misses else rows
        self.controller.matching = lagging
        return calls

    def test_admission_rereads_until_current_run_is_listed(self):
        # Pages chain #550 (2026-11-10) stopped on the first listing that lacked itself.
        self.publisher()
        calls = self.lagging_listing(2)
        self.assertTrue(self.controller.admit())
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.elapsed, sum(chain.ADMISSION_DELAYS[:2]))
        self.assertIn(('admission_listing_reads', 3), self.messages)

    def test_admission_still_stops_when_current_run_never_appears(self):
        self.publisher()
        calls = self.lagging_listing(99)
        with self.assertRaisesRegex(chain.RelayError, 'current_run_not_in_complete_query'):
            self.controller.admit()
        self.assertEqual(len(calls), len(chain.ADMISSION_DELAYS) + 1)
        self.assertEqual(self.elapsed, sum(chain.ADMISSION_DELAYS))
        self.assertLess(self.elapsed, 60)

    def test_admission_wait_honours_stop_and_late_duplicates(self):
        self.publisher()
        self.lagging_listing(1)
        original = self.sleep
        def stop(seconds):
            original(seconds)
            self.api.active = False
        self.controller.sleep = stop
        with self.assertRaises(chain.Stopped):
            self.controller.admit()
        self.api.active = True
        self.controller.sleep = original
        # An earlier duplicate that only shows up on a later read still stops admission.
        self.api.rows.append(record(79, chain.PUBLISH, 'Pages chain u10a1'))
        calls = self.lagging_listing(1, hidden=(79, 80))
        with self.assertRaisesRegex(chain.Stopped, 'duplicate'):
            self.controller.admit()
        self.assertEqual(len(calls), 2)

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


class UnconfirmedDispatchTests(unittest.TestCase):
    """Relay 43835501368 (2026-11-16): POST created Pages 43835544201 one second later,
    but the created>= listing never showed it within the reconcile window."""
    setUp = ControllerTests.setUp
    sleep = ControllerTests.sleep

    def pages_posts(self):
        return [p for p in self.api.posts if chain.PUBLISH in p[0]]

    def relay_posts(self):
        return [p for p in self.api.posts if chain.RELAY in p[0]]

    def keys(self):
        return [k for k, _ in self.messages]

    def message(self, key):
        return next(v for k, v in self.messages if k == key)

    def test_incident_post_accepted_but_never_listed_relay_continues(self):
        self.api.hidden_ids = {101}
        self.controller.relay()
        self.assertEqual(len(self.pages_posts()), 1)   # Never resent.
        self.assertEqual(len(self.relay_posts()), 1)
        self.assertIn('POST accepted', self.message('update_unconfirmed'))
        self.assertNotIn('update_run', self.keys())
        self.assertIn('next_relay', self.keys())
        self.assertEqual(self.elapsed, 600)             # Reconcile stayed inside the window.

    def test_listing_appears_late_within_relay_round(self):
        self.api.hidden_reads = 4
        self.controller.relay()
        self.assertEqual(self.message('update_run'), 101)
        self.assertIn(('dispatch_confirmed_after_reads', 5), self.messages)
        self.assertNotIn('update_unconfirmed', self.keys())
        self.assertEqual(len(self.pages_posts()), 1)

    def test_post_failure_creates_nothing_and_relay_continues(self):
        self.api.failed_posts = {chain.PUBLISH}
        self.controller.relay()
        self.assertEqual(len(self.pages_posts()), 1)
        self.assertIn('POST result unknown', self.message('update_unconfirmed'))
        self.assertIn('next_relay', self.keys())

    def test_next_relay_unconfirmed_does_not_resend_and_still_fails_visibly(self):
        self.api.hidden_ids = {102}
        with self.assertRaisesRegex(chain.Unconfirmed, 'dispatch_unconfirmed_no_resend'):
            self.controller.relay()
        self.assertEqual(len(self.relay_posts()), 1)
        self.assertIn('pending behind the weather-relay lock', self.message('next_relay_unconfirmed'))
        self.assertEqual(self.message('next_request'), 'r10a1')
        self.assertEqual(self.message('update_run'), 101)
        self.assertLessEqual(self.elapsed, 600 + chain.RECONCILE_BUDGET)

    def test_next_relay_post_failure_is_reported_and_not_resent(self):
        self.api.failed_posts = {chain.RELAY}
        with self.assertRaises(chain.Unconfirmed):
            self.controller.relay()
        self.assertEqual(len(self.relay_posts()), 1)
        self.assertIn('cron may be needed', self.message('next_relay_unconfirmed'))

    def test_both_dispatches_unconfirmed_still_one_post_each(self):
        self.api.hidden_ids = {101, 102}
        with self.assertRaises(chain.Unconfirmed):
            self.controller.relay()
        self.assertEqual((len(self.pages_posts()), len(self.relay_posts())), (1, 1))
        self.assertIn('update_unconfirmed', self.keys())

    def test_cli_exit_codes_for_unconfirmed_dispatches(self):
        self.api.hidden_ids = {101}
        with patch.dict(os.environ, dict(GITHUB_REPOSITORY='owner/repo'), clear=True), \
             patch.object(chain, 'GitHub', return_value=self.api), \
             patch.object(chain, 'Controller', side_effect=lambda api, env: self.controller), \
             patch.object(chain, 'summary'):
            self.assertEqual(chain.main(['relay']), 0)  # Pages unconfirmed: relay handed off.
        self.assertIn('next_relay', self.keys())
        self.setUp()
        self.api.hidden_ids = {102}
        with patch.dict(os.environ, dict(GITHUB_REPOSITORY='owner/repo'), clear=True), \
             patch.object(chain, 'GitHub', return_value=self.api), \
             patch.object(chain, 'Controller', side_effect=lambda api, env: self.controller), \
             patch.object(chain, 'summary') as output:
            self.assertEqual(chain.main(['relay']), 1)  # Next relay unconfirmed: stays red.
        output.assert_any_call('safe_stop', 'dispatch_unconfirmed_no_resend')

    def next_round(self):
        """Continue with the relay run that round one dispatched (ID 102)."""
        self.api.hidden_ids = set()
        self.env.update(GITHUB_RUN_ID='102', GITHUB_EVENT_NAME='workflow_dispatch', RELAY_REQUEST_ID='r10a1')
        self.messages.clear()
        self.elapsed = 0

    def test_next_round_is_blocked_by_busy_unconfirmed_run(self):
        self.api.hidden_ids = {101}
        self.controller.relay()
        self.next_round()
        # In the incident the publisher was still queued/building ten minutes later.
        for status in ('queued', 'in_progress', 'pending', 'waiting'):
            with self.subTest(status=status):
                next(r for r in self.api.rows if r['id'] == 101)['status'] = status
                before = len(self.pages_posts())
                self.controller.relay()
                self.assertEqual(len(self.pages_posts()), before)
                self.assertIn('busy', self.keys())
                self.api.rows = [r for r in self.api.rows if r['id'] <= 102]
                self.api.posts = self.api.posts[:2]
                self.messages.clear()
                self.elapsed = 0

    def test_next_round_waits_cadence_after_finished_unconfirmed_run(self):
        self.api.hidden_ids = {101}
        self.controller.relay()
        self.next_round()
        finished = next(r for r in self.api.rows if r['id'] == 101)
        finished.update(status='completed', created_at='2026-11-05T23:59:00+00:00')
        posted_at = []
        original = self.api.request
        def track(method, path, payload=None):
            if path.endswith(chain.PUBLISH + '/dispatches'):
                posted_at.append(self.elapsed)
            return original(method, path, payload)
        self.api.request = track
        self.controller.relay()
        self.assertIn(('cadence_wait_seconds', 540.0), self.messages)
        self.assertEqual(posted_at, [540])          # Not before 600 s after the unconfirmed run.
        self.assertEqual(self.pages_posts()[-1][1]['inputs']['chain_request_id'], 'u102a1')

    def test_unconfirmed_run_that_appears_twice_is_rejected_by_admission(self):
        self.api.hidden_ids = {101}
        self.controller.relay()
        # If a second run with the same identity ever existed, the later one is skipped.
        self.api.rows.append(record(150, chain.PUBLISH, 'Pages chain u10a1', 'in_progress'))
        self.env.update(GITHUB_RUN_ID='150', GITHUB_EVENT_NAME='workflow_dispatch',
                        CHAIN_REQUEST_ID='u10a1', SOURCE_MODE='auto', MODE='refresh', RETENTION_DAYS='15')
        self.api.hidden_ids = set()
        with self.assertRaisesRegex(chain.Stopped, 'duplicate_chain_request'):
            self.controller.admit()

    def test_run_id_from_post_confirms_without_listing(self):
        self.api.return_run_id = True
        self.api.hidden_ids = {101}
        found = self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertEqual(found['id'], 101)
        self.assertEqual(self.elapsed, 0)
        self.assertIn(('dispatch_confirmed_by_id', 101), self.messages)
        self.assertEqual(len(self.api.posts), 1)

    def test_run_id_404_then_readable(self):
        self.api.return_run_id = True
        self.api.hidden_ids = {101}
        self.api.id_404_reads = 2
        found = self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertEqual(found['id'], 101)
        self.assertEqual(self.elapsed, sum(chain.RECONCILE_DELAYS[:2]))
        self.assertEqual(len(self.api.posts), 1)

    def test_run_id_title_not_yet_evaluated_falls_back_to_listing(self):
        self.api.return_run_id = True
        original = self.api.request
        def untitled(method, path, payload=None):
            result = original(method, path, payload)
            if path == '/actions/runs/101':
                result['display_title'] = 'Publish validated snapshot to Pages'
            return result
        self.api.request = untitled
        found = self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertEqual(found['id'], 101)
        self.assertNotIn('dispatch_confirmed_by_id', self.keys())

    def test_run_id_with_wrong_identity_stops_without_resend(self):
        self.api.return_run_id = True
        for field, value in (('head_branch', 'other'), ('event', 'push'), ('id', 999),
                             ('created_at', '2020-01-01T00:00:00+00:00')):
            with self.subTest(field=field):
                self.setUp()
                self.api.return_run_id = True
                original = self.api.request
                def tampered(method, path, payload=None, field=field, value=value, original=original):
                    result = original(method, path, payload)
                    if path == '/actions/runs/101':
                        result[field] = value
                    return result
                self.api.request = tampered
                with self.assertRaisesRegex(chain.RelayError, 'untrusted_dispatch_response'):
                    self.controller.relay()
                self.assertEqual(len(self.api.posts), 1)

    def test_run_id_and_listing_disagree_is_ambiguous(self):
        self.api.return_run_id = True
        original = self.api.request
        def other(method, path, payload=None):
            result = original(method, path, payload)
            if path == '/actions/runs/101':
                result['display_title'] = 'not yet evaluated'
            if '/runs?' in path and 'created=' in path:
                for row in result['workflow_runs']:
                    if row['id'] == 101:
                        row['id'] = 103
            return result
        self.api.request = other
        with self.assertRaisesRegex(chain.RelayError, 'ambiguous_dispatch_identity'):
            self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertEqual(len(self.api.posts), 1)

    def test_untrusted_listing_match_after_post_still_stops_relay(self):
        original = self.api.request
        def wrong(method, path, payload=None):
            result = original(method, path, payload)
            if '/runs?' in path and 'created=' in path:
                for row in result['workflow_runs']:
                    if row['id'] == 101:
                        row['head_branch'] = 'other'
            return result
        self.api.request = wrong
        with self.assertRaisesRegex(chain.RelayError, 'untrusted_matching_run'):
            self.controller.relay()
        self.assertEqual(len(self.api.posts), 1)       # No hand-off on integrity failure.

    def test_transient_listing_failure_after_post_is_a_miss_not_a_stop(self):
        original = self.api.request
        failures = []
        def flaky(method, path, payload=None):
            if self.api.posts and '/runs?' in path and 'created=' in path and len(failures) < 2:
                failures.append(path)
                raise chain.RelayError('api_transport_or_retry_exhausted')
            return original(method, path, payload)
        self.api.request = flaky
        self.controller.relay()
        self.assertEqual(self.message('update_run'), 101)
        self.assertEqual(len(self.pages_posts()), 1)
        self.assertIn('next_relay', self.keys())

    def test_reconcile_budget_bounds_slow_reads(self):
        self.api.hidden_ids = {101}
        original = self.controller.matching
        reads = []
        def slow(*args):
            self.elapsed += 30          # Each listing burns 30 s in GET retries.
            reads.append(args)
            return original(*args)
        self.controller.matching = slow
        with self.assertRaises(chain.Unconfirmed):
            self.controller.dispatch(chain.PUBLISH, dict(chain_request_id='u10a1'), 'Pages chain u10a1', NOW)
        self.assertLess(len(reads) - 1, len(chain.RECONCILE_DELAYS) + 1)  # First read is the pre-POST check.
        self.assertLessEqual(self.elapsed, 30 + chain.RECONCILE_BUDGET + 30 + max(chain.RECONCILE_DELAYS))

    def test_explicit_post_rejection_fails_visibly_without_reconcile_or_resend(self):
        original = self.api.request
        def reject(method, path, payload=None):
            if method == 'POST':
                self.api.posts.append((path, payload))
                raise chain.RelayError('api_http_422')
            return original(method, path, payload)
        self.api.request = reject
        with self.assertRaisesRegex(chain.RelayError, 'dispatch_rejected_422'):
            self.controller.relay()
        self.assertEqual(len(self.api.posts), 1)
        self.assertEqual(self.elapsed, 0)
        self.assertNotIn('update_unconfirmed', self.keys())

    def test_oversized_listing_after_post_is_not_a_transient_miss(self):
        original = self.api.request
        def flood(method, path, payload=None):
            result = original(method, path, payload)
            if self.api.posts and '/runs?' in path and 'created=' in path:
                result['total_count'] = 101
            return result
        self.api.request = flood
        with self.assertRaisesRegex(chain.TooManyRuns, 'incomplete_run_query'):
            self.controller.relay()
        self.assertEqual(len(self.api.posts), 1)
        self.assertNotIn('update_unconfirmed', self.keys())

    def test_child_observation_read_failure_still_hands_off(self):
        original = self.api.request
        def flaky(method, path, payload=None):
            if path == '/actions/runs/101' and self.elapsed >= 600:
                raise chain.RelayError('api_transport_or_retry_exhausted')
            return original(method, path, payload)
        self.api.request = flaky
        self.controller.relay()
        self.assertIn('not observed', self.message('update_observed_result'))
        self.assertIn('next_relay', self.keys())

    def test_child_observation_integrity_failure_still_stops(self):
        original = self.api.request
        def bad(method, path, payload=None):
            if path == '/actions/runs/101' and self.elapsed >= 600:
                raise chain.RelayError('api_http_403')
            return original(method, path, payload)
        self.api.request = bad
        with self.assertRaisesRegex(chain.RelayError, 'api_http_403'):
            self.controller.relay()
        self.assertEqual(len(self.relay_posts()), 0)


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
