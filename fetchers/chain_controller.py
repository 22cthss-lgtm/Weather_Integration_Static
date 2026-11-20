"""Bounded Actions relay. No weather requests, Git writes, or artifact changes."""
import argparse
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

RELAY = 'weather-relay.yml'
PUBLISH = 'pages-manual.yml'
ACTIVE = ('queued', 'in_progress', 'waiting', 'pending', 'requested')
INTERVAL = 600
# Must equal fetchers/policies/due-runtime.json artifact_retention_days (tested).
RETENTION_DAYS = '15'
READ_ATTEMPTS = 3
MAX_BODY = 2 * 1024 * 1024
# Run listings are eventually consistent: a filtered query may briefly report a
# total_count that disagrees with the rows returned. Re-read a bounded number of
# times before treating the listing as unusable.
LISTING_RETRY_DELAYS = (2, 4)
# After the single dispatch POST, a newly created run can take tens of seconds to
# appear in filtered listings. Observe for about a minute; never resend the POST.
# Relay 43835501368 (2026-11-16): the publisher run existed 1 s after the POST but
# stayed out of the created>= listing for the whole window, so the run ID from the
# POST response is checked directly first and the listing is only a fallback.
RECONCILE_DELAYS = (2, 4, 8, 15, 15, 15)
# No new reconcile read starts after this many seconds. It is not a hard cap: the
# last round may still spend its GET retries (a few minutes in pathological cases).
RECONCILE_BUDGET = 120
# Read failures that may clear on a later read. Anything else (bad identity,
# ambiguous matches, refused documents) still stops the relay.
TRANSIENT_READ_ERRORS = ('api_transport_or_retry_exhausted', 'incomplete_run_query')
# Publisher admission waits for its own run to appear (~29 s; admission job limit 3 min).
ADMISSION_DELAYS = (2, 4, 8, 15)


class RelayError(ValueError):
    pass


class Stopped(RelayError):
    pass


class Busy(RelayError):
    pass


class TooManyRuns(RelayError):
    """More than 100 matching runs: not transient, never treated as a listing miss."""
    def __init__(self):
        super().__init__('incomplete_run_query')


class StateUnknown(RelayError):
    """A publisher-state read before the Pages POST failed transiently; nothing was sent."""


def transient(error):
    """True for read failures that may clear later; never for TooManyRuns."""
    return not isinstance(error, TooManyRuns) and str(error) in TRANSIENT_READ_ERRORS


class Unconfirmed(RelayError):
    """The sole POST was sent (or its result is unknown) but no run was confirmed."""
    def __init__(self, post_accepted):
        super().__init__('dispatch_unconfirmed_no_resend')
        self.post_accepted = post_accepted


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RelayError('api_redirect_refused')


class GitHub:
    def __init__(self, repository, token, *, opener=None, sleep=time.sleep):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not token:
            raise RelayError('invalid_api_configuration')
        self.base = 'https://api.github.com/repos/' + repository
        self.token, self.sleep = token, sleep
        self.opener = opener or build_opener(NoRedirect())

    def request(self, method, path, payload=None):
        if not path.startswith('/actions/') or '..' in path:
            raise RelayError('invalid_api_path')
        # A POST has no idempotency guarantee. Never blindly retry it, including 5xx.
        attempts = READ_ATTEMPTS if method == 'GET' else 1
        for attempt in range(attempts):
            request = Request(self.base + path, method=method,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers={'Authorization': 'Bearer ' + self.token,
                         'Accept': 'application/vnd.github+json',
                         'Content-Type': 'application/json',
                         'X-GitHub-Api-Version': '2026-03-10',
                         'User-Agent': 'weather-bounded-relay', 'Cache-Control': 'no-cache'})
            try:
                with self.opener.open(request, timeout=10) as response:
                    body = response.read(MAX_BODY + 1)
                    if len(body) > MAX_BODY:
                        raise RelayError('api_body_too_large')
                    if not body and response.status == 204:
                        return None
                    document = json.loads(body)
                    if not isinstance(document, dict):
                        raise RelayError('invalid_api_document')
                    return document
            except HTTPError as error:
                code = error.code
                error.close()
                if code != 429 and not 500 <= code < 600:
                    raise RelayError('api_http_' + str(code)) from None
            except (URLError, TimeoutError, OSError, HTTPException):
                pass
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise RelayError('invalid_api_json') from None
            if attempt + 1 < attempts:
                self.sleep((1, 3)[attempt])
        raise RelayError('api_transport_or_retry_exhausted')


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise RelayError('invalid_run_timestamp') from None


def summary(key, value):
    line = '- **' + key + '**: ' + str(value).replace('\n', ' ') + '\n'
    print(line.strip(), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write(line)


class Controller:
    def __init__(self, api, env, *, clock=time.monotonic, sleep=time.sleep,
                 now=lambda: datetime.now(timezone.utc), report=summary):
        self.api, self.env = api, env
        self.clock, self.sleep, self.now, self.report = clock, sleep, now, report

    def enabled(self):
        metadata = self.api.request('GET', '/actions/workflows/' + RELAY)
        if not isinstance(metadata, dict) or metadata.get('path') != '.github/workflows/' + RELAY:
            raise RelayError('invalid_controller_metadata')
        if metadata.get('state') != 'active':
            raise Stopped('controller_not_active')

    def context(self):
        if (self.env.get('GITHUB_REF') != 'refs/heads/' + self.env.get('DEFAULT_BRANCH', '')
                or self.env.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')):
            raise RelayError('untrusted_event_or_branch')
        for field in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
            if not re.fullmatch(r'[1-9][0-9]*', self.env.get(field, '')):
                raise RelayError('invalid_run_identity')

    def validate_run(self, run, workflow):
        if (not isinstance(run, dict) or type(run.get('id')) is not int
                or run['id'] <= 0 or run.get('path') != '.github/workflows/' + workflow
                or run.get('status') not in (*ACTIVE, 'completed')
                or not isinstance(run.get('display_title'), str)):
            raise RelayError('invalid_run_record')
        timestamp(run.get('created_at'))
        return run

    def runs(self, workflow, **query):
        path = '/actions/workflows/' + workflow + '/runs?' + urlencode(dict(per_page=100, **query))
        for attempt in range(len(LISTING_RETRY_DELAYS) + 1):
            result = self.api.request('GET', path)
            if (not isinstance(result, dict) or type(result.get('total_count')) is not int
                    or not isinstance(result.get('workflow_runs'), list)):
                raise RelayError('incomplete_run_query')
            if result['total_count'] > 100 or len(result['workflow_runs']) > 100:
                raise TooManyRuns()  # Too many rows: not transient.
            if result['total_count'] == len(result['workflow_runs']) and result['total_count'] >= 0:
                break
            if attempt == len(LISTING_RETRY_DELAYS):
                raise RelayError('incomplete_run_query')
            self.sleep(LISTING_RETRY_DELAYS[attempt])
        rows = [self.validate_run(row, workflow) for row in result['workflow_runs']]
        if len({row['id'] for row in rows}) != len(rows):
            raise RelayError('duplicate_run_query')
        return rows

    def matching(self, workflow, title, since):
        rows = self.runs(workflow, created='>=' + since.isoformat())
        matches = [row for row in rows if row['display_title'] == title]
        if any(row.get('head_branch') != self.env['DEFAULT_BRANCH']
               or row.get('event') != 'workflow_dispatch' for row in matches):
            raise RelayError('untrusted_matching_run')
        return matches

    def active_publishers(self):
        return [row for status in ACTIVE for row in self.runs(PUBLISH, status=status)]

    def dispatch(self, workflow, inputs, title, since):
        self.enabled()
        try:
            matches = self.matching(workflow, title, since)
            busy = self.active_publishers() if workflow == PUBLISH and not matches else []
        except RelayError as error:
            # Pre-POST publisher reads only: nothing was sent, so skipping is safe.
            # The hand-off (RELAY) keeps failing visibly; see docs/data-flow.md section 13.
            if workflow != PUBLISH or not transient(error):
                raise
            raise StateUnknown(str(error)) from None
        if len(matches) > 1:
            raise RelayError('ambiguous_dispatch_identity')
        if matches:
            self.report('dispatch_reused', matches[0]['id'])
            return matches[0]
        if workflow == PUBLISH:
            if busy:
                raise Busy(', '.join(str(row['id']) + ':' + row['status'] for row in busy))
        self.enabled()  # Live read immediately before the sole POST.
        response, post_accepted = None, True
        try:
            response = self.api.request('POST', '/actions/workflows/' + workflow + '/dispatches',
                                        {'ref': self.env['DEFAULT_BRANCH'], 'inputs': inputs})
        except RelayError as error:
            if str(error).startswith('api_http_'):
                # 429/5xx surface as transport errors; any other HTTP status is an
                # explicit rejection, so no run exists. Fail visibly, never resend.
                raise RelayError('dispatch_rejected_' + str(error)[len('api_http_'):]) from None
            post_accepted = False
            self.report('dispatch_response', str(error) + '; reconcile only, no resend')
        run_id = response.get('workflow_run_id') if isinstance(response, dict) else None
        if type(run_id) is not int or run_id <= 0:
            run_id = None
        deadline = self.clock() + RECONCILE_BUDGET
        for attempt in range(len(RECONCILE_DELAYS) + 1):
            found = self.reconcile_once(workflow, title, since, run_id)
            if found:
                if attempt:
                    self.report('dispatch_confirmed_after_reads', attempt + 1)
                return found
            if attempt == len(RECONCILE_DELAYS) or self.clock() >= deadline:
                break
            self.sleep(RECONCILE_DELAYS[attempt])
            self.enabled()
        raise Unconfirmed(post_accepted)

    def reconcile_once(self, workflow, title, since, run_id):
        """One read after the POST: the returned run ID first, then the listing."""
        if run_id is not None:
            try:
                run = self.validate_run(self.api.request('GET', '/actions/runs/' + str(run_id)), workflow)
            except RelayError as error:
                # A just-created run may briefly 404 by ID; treat like a listing miss.
                if not transient(error) and str(error) != 'api_http_404':
                    raise
                run = None
            if run is not None:
                if (run['id'] != run_id or run.get('head_branch') != self.env['DEFAULT_BRANCH']
                        or run.get('event') != 'workflow_dispatch' or timestamp(run['created_at']) < since):
                    raise RelayError('untrusted_dispatch_response')
                if run['display_title'] == title:
                    self.report('dispatch_confirmed_by_id', run_id)
                    return run
                # The run-name may not be evaluated yet; fall through to the listing.
        try:
            matches = self.matching(workflow, title, since)
        except RelayError as error:
            if not transient(error):
                raise
            return None
        if len(matches) > 1 or (matches and run_id is not None and matches[0]['id'] != run_id):
            raise RelayError('ambiguous_dispatch_identity')
        return matches[0] if matches else None

    def wait_until(self, deadline):
        while True:
            self.enabled()
            remaining = deadline - self.clock()
            if remaining <= 0:
                return
            self.sleep(min(20, remaining))

    def admit(self):
        request_id = self.env.get('CHAIN_REQUEST_ID', '')
        if not request_id:
            self.report('admission', 'manual input; controller switch does not apply')
            return True
        self.context()
        match = re.fullmatch(r'u([1-9][0-9]*)a([1-9][0-9]*)', request_id)
        if (not match or self.env.get('SOURCE_MODE') != 'auto' or self.env.get('MODE') != 'refresh'
                or self.env.get('RETENTION_DAYS') != RETENTION_DAYS
                or self.env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
            raise RelayError('invalid_chain_inputs')
        self.enabled()
        if self.env['GITHUB_RUN_ATTEMPT'] != '1':
            raise Stopped('automatic_rerun_refused_use_new_controller')
        parent = self.validate_run(self.api.request('GET', '/actions/runs/' + match[1]), RELAY)
        if (parent['id'] != int(match[1])
                or parent.get('head_branch') != self.env['DEFAULT_BRANCH']
                or parent.get('event') not in ('schedule', 'workflow_dispatch')
                or type(parent.get('run_attempt')) is not int
                or parent.get('run_attempt') != int(match[2])):
            raise RelayError('invalid_chain_parent')
        current = int(self.env['GITHUB_RUN_ID'])
        # A just-started run can be missing from filtered listings for a while
        # (Pages chain #550, 2026-11-10). Re-read a bounded number of times.
        for attempt in range(len(ADMISSION_DELAYS) + 1):
            matches = self.matching(PUBLISH, 'Pages chain ' + request_id, timestamp(parent['created_at']))
            if any(row['id'] == current for row in matches):
                if attempt:
                    self.report('admission_listing_reads', attempt + 1)
                break
            if attempt == len(ADMISSION_DELAYS):
                raise RelayError('current_run_not_in_complete_query')
            self.sleep(ADMISSION_DELAYS[attempt])
            self.enabled()
        if any(row['id'] < current for row in matches):
            raise Stopped('duplicate_chain_request')
        self.enabled()  # Check after metadata queries, immediately before admission/fetch.
        self.report('chain_parent', parent['id'])
        self.report('chain_request', request_id)
        return True

    def state_unknown(self, error):
        self.report('update', 'not dispatched; publisher state unknown (' + str(error) +
                    '); no retry or catch-up this round; publisher lock/queue remains untouched')

    def relay(self):
        started = self.clock()
        self.context()
        self.enabled()
        identifier, attempt = self.env['GITHUB_RUN_ID'], self.env['GITHUB_RUN_ATTEMPT']
        current = self.validate_run(self.api.request('GET', '/actions/runs/' + identifier), RELAY)
        if (current['id'] != int(identifier)
                or type(current.get('run_attempt')) is not int
                or current.get('run_attempt') != int(attempt)
                or current.get('head_branch') != self.env['DEFAULT_BRANCH']
                or current.get('event') != self.env['GITHUB_EVENT_NAME']):
            raise RelayError('invalid_controller_run')
        self.report('controller_run', identifier + ' attempt ' + attempt)
        parent_request = self.env.get('RELAY_REQUEST_ID', '')
        if parent_request:
            match = re.fullmatch(r'r([1-9][0-9]*)a([1-9][0-9]*)', parent_request)
            if (not match or self.env['GITHUB_EVENT_NAME'] != 'workflow_dispatch'
                    or current['display_title'] != 'Relay ' + parent_request):
                raise RelayError('invalid_relay_request')
            parent = self.validate_run(self.api.request('GET', '/actions/runs/' + match[1]), RELAY)
            if (parent['id'] != int(match[1]) or parent['id'] >= current['id']
                    or type(parent.get('run_attempt')) is not int
                    or parent['run_attempt'] != int(match[2])
                    or parent.get('head_branch') != self.env['DEFAULT_BRANCH']
                    or parent.get('event') not in ('schedule', 'workflow_dispatch')):
                raise RelayError('invalid_relay_parent')
        self.report('relay_parent_request', parent_request or 'cron/manual seed')
        child = None
        # Relay 44631504533 (2026-11-19): an inconsistent busy listing stopped the
        # chain for ~2.5 h. A transient publisher-state read now skips this round's
        # update (never dispatching blind) but still waits and hands off.
        try:
            busy = self.active_publishers()
            recent = None if busy else self.runs(
                PUBLISH, created='>=' + (self.now() - timedelta(seconds=600)).isoformat())
        except RelayError as error:
            if not transient(error):
                raise
            busy = recent = None
            self.state_unknown(error)
        if busy:
            self.report('busy', ', '.join(str(row['id']) + ':' + row['status'] for row in busy))
            self.report('update', 'not dispatched; publisher lock/queue remains untouched')
        elif recent is not None:
            automatic = [row for row in recent if row['display_title'].startswith('Pages chain ')]
            if automatic:
                last = max(automatic, key=lambda row: timestamp(row['created_at']))
                remaining = (timestamp(last['created_at']) + timedelta(seconds=600) - self.now()).total_seconds()
                if not 0 <= remaining <= 600:
                    raise RelayError('invalid_recent_dispatch_time')
                self.report('cadence_wait_seconds', round(remaining, 1))
                self.wait_until(self.clock() + remaining)
                # Work may have started while waiting. Do not enqueue behind it.
                try:
                    busy = self.active_publishers()
                except RelayError as error:
                    if not transient(error):
                        raise
                    busy = None
                    self.state_unknown(error)
            if busy:
                self.report('busy', ', '.join(str(row['id']) + ':' + row['status'] for row in busy))
            elif busy is not None:
                request_id = 'u' + identifier + 'a' + attempt
                try:
                    child = self.dispatch(PUBLISH, dict(snapshot_source='auto', mode='refresh',
                        snapshot_retention_days=RETENTION_DAYS, chain_request_id=request_id),
                        'Pages chain ' + request_id, timestamp(current['created_at']))
                except Busy as error:
                    self.report('busy', str(error) + '; changed during preflight, no update dispatched')
                except StateUnknown as error:
                    self.state_unknown(error)
                except Unconfirmed as error:
                    # Never resend. If the run exists, the next relay sees it as busy or
                    # recent; publisher admission still rejects an earlier same-ID run.
                    self.report('update_unconfirmed', 'Pages chain ' + request_id + '; ' +
                                ('POST accepted' if error.post_accepted else 'POST result unknown') +
                                '; no resend; relay continues')
                if child:
                    self.report('update_run', child['id'])
                    self.report('update_request', request_id)
        self.report('next_target', 'about 600 seconds from controller admission; no catch-up burst')
        self.wait_until(started + INTERVAL)
        if child:
            try:
                observed = self.validate_run(self.api.request('GET', '/actions/runs/' + str(child['id'])), PUBLISH)
            except RelayError as error:
                if str(error) not in TRANSIENT_READ_ERRORS:
                    raise
                # Observation only: a failed read must not block the hand-off.
                self.report('update_observed_result', str(child['id']) + ': not observed (' + str(error) + ')')
            else:
                if observed['id'] != child['id']:
                    raise RelayError('inconsistent_child_identity')
                self.report('update_observed_result', str(observed['id']) + ':' + observed['status'] + ':' +
                            str(observed.get('conclusion')) + ' (observation, not a completion guarantee)')
        next_id = 'r' + identifier + 'a' + attempt
        try:
            following = self.dispatch(RELAY, {'relay_request_id': next_id}, 'Relay ' + next_id,
                                      timestamp(current['created_at']))
        except Unconfirmed as error:
            self.report('next_relay_unconfirmed', 'Relay ' + next_id + '; no resend; ' +
                        ('POST accepted, so the run is probably pending behind the weather-relay lock'
                         if error.post_accepted else 'POST result unknown; cron may be needed to resume'))
            self.report('next_request', next_id)
            raise
        self.report('next_relay', str(following['id']) + ':' + following['status'] + '; completion not yet observed')
        self.report('next_request', next_id)


def require_enabled(env=None):
    """Re-admit immediately before source refresh, including after runner setup."""
    env = os.environ if env is None else env
    if env.get('CHAIN_REQUEST_ID'):
        controller = Controller(GitHub(env['GITHUB_REPOSITORY'], env.get('GH_TOKEN', '')), env)
        try:
            controller.admit()
        except RelayError as error:
            summary('source_refresh_stopped', str(error))
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('relay', 'admit'))
    args = parser.parse_args(argv)
    try:
        # Manual publisher admission needs neither network nor a token.
        api = (GitHub(os.environ['GITHUB_REPOSITORY'], os.environ.get('GH_TOKEN', ''))
               if args.command == 'relay' or os.environ.get('CHAIN_REQUEST_ID') else None)
        controller = Controller(api, os.environ)
        if args.command == 'relay':
            controller.relay()
        else:
            try:
                allowed = controller.admit()
            except Stopped as error:
                summary('admission_stopped', str(error))
                allowed = False
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write('allowed=' + str(allowed).lower() + '\n')
        return 0
    except Stopped as error:
        summary('relay_stopped', str(error))
        return 0
    except (RelayError, KeyError, OSError) as error:
        summary('safe_stop', str(error) if isinstance(error, RelayError) else type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
