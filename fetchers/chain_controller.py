"""Bounded Actions relay. No weather requests, Git writes, or artifact changes."""
import argparse
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

RELAY = 'weather-relay.yml'
PUBLISH = 'pages-manual.yml'
ACTIVE = ('queued', 'in_progress', 'waiting', 'pending', 'requested')
INTERVAL = 600
READ_ATTEMPTS = 3
MAX_BODY = 2 * 1024 * 1024
# Run listings are eventually consistent: a filtered query may briefly report a
# total_count that disagrees with the rows returned. Re-read a bounded number of
# times before treating the listing as unusable.
LISTING_RETRY_DELAYS = (2, 4)
# After the single dispatch POST, a newly created run can take tens of seconds to
# appear in filtered listings. Observe for about a minute; never resend the POST.
RECONCILE_DELAYS = (2, 4, 8, 15, 15, 15)


class RelayError(ValueError):
    pass


class Stopped(RelayError):
    pass


class Busy(RelayError):
    pass


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
                raise RelayError('incomplete_run_query')  # Too many rows: not transient.
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

    def dispatch(self, workflow, inputs, title, since):
        self.enabled()
        matches = self.matching(workflow, title, since)
        if len(matches) > 1:
            raise RelayError('ambiguous_dispatch_identity')
        if matches:
            self.report('dispatch_reused', matches[0]['id'])
            return matches[0]
        if workflow == PUBLISH:
            busy = [row for status in ACTIVE for row in self.runs(PUBLISH, status=status)]
            if busy:
                raise Busy(', '.join(str(row['id']) + ':' + row['status'] for row in busy))
        self.enabled()  # Live read immediately before the sole POST.
        try:
            self.api.request('POST', '/actions/workflows/' + workflow + '/dispatches',
                             {'ref': self.env['DEFAULT_BRANCH'], 'inputs': inputs})
        except RelayError as error:
            self.report('dispatch_response', str(error) + '; reconcile only, no resend')
        for attempt in range(len(RECONCILE_DELAYS) + 1):
            matches = self.matching(workflow, title, since)
            if len(matches) > 1:
                raise RelayError('ambiguous_dispatch_identity')
            if matches:
                if attempt:
                    self.report('dispatch_confirmed_after_reads', attempt + 1)
                return matches[0]
            if attempt < len(RECONCILE_DELAYS):
                self.sleep(RECONCILE_DELAYS[attempt])
                self.enabled()
        raise RelayError('dispatch_unconfirmed_no_resend')

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
                or self.env.get('RETENTION_DAYS') != '7'
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
        matches = self.matching(PUBLISH, 'Pages chain ' + request_id, timestamp(parent['created_at']))
        if not any(row['id'] == current for row in matches):
            raise RelayError('current_run_not_in_complete_query')
        if any(row['id'] < current for row in matches):
            raise Stopped('duplicate_chain_request')
        self.enabled()  # Check after metadata queries, immediately before admission/fetch.
        self.report('chain_parent', parent['id'])
        self.report('chain_request', request_id)
        return True

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
        busy = []
        for status in ACTIVE:
            busy.extend(self.runs(PUBLISH, status=status))
        child = None
        if busy:
            self.report('busy', ', '.join(str(row['id']) + ':' + row['status'] for row in busy))
            self.report('update', 'not dispatched; publisher lock/queue remains untouched')
        else:
            recent = self.runs(PUBLISH, created='>=' + (self.now() - timedelta(seconds=600)).isoformat())
            automatic = [row for row in recent if row['display_title'].startswith('Pages chain ')]
            if automatic:
                last = max(automatic, key=lambda row: timestamp(row['created_at']))
                remaining = (timestamp(last['created_at']) + timedelta(seconds=600) - self.now()).total_seconds()
                if not 0 <= remaining <= 600:
                    raise RelayError('invalid_recent_dispatch_time')
                self.report('cadence_wait_seconds', round(remaining, 1))
                self.wait_until(self.clock() + remaining)
                # Work may have started while waiting. Do not enqueue behind it.
                busy = [row for status in ACTIVE for row in self.runs(PUBLISH, status=status)]
            if busy:
                self.report('busy', ', '.join(str(row['id']) + ':' + row['status'] for row in busy))
            else:
                request_id = 'u' + identifier + 'a' + attempt
                try:
                    child = self.dispatch(PUBLISH, dict(snapshot_source='auto', mode='refresh',
                        snapshot_retention_days='7', chain_request_id=request_id),
                        'Pages chain ' + request_id, timestamp(current['created_at']))
                except Busy as error:
                    self.report('busy', str(error) + '; changed during preflight, no update dispatched')
                if child:
                    self.report('update_run', child['id'])
                    self.report('update_request', request_id)
        self.report('next_target', 'about 600 seconds from controller admission; no catch-up burst')
        self.wait_until(started + INTERVAL)
        if child:
            observed = self.validate_run(self.api.request('GET', '/actions/runs/' + str(child['id'])), PUBLISH)
            if observed['id'] != child['id']:
                raise RelayError('inconsistent_child_identity')
            self.report('update_observed_result', str(observed['id']) + ':' + observed['status'] + ':' +
                        str(observed.get('conclusion')) + ' (observation, not a completion guarantee)')
        next_id = 'r' + identifier + 'a' + attempt
        following = self.dispatch(RELAY, {'relay_request_id': next_id}, 'Relay ' + next_id,
                                  timestamp(current['created_at']))
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
