"""Actions integration for authenticated snapshot recovery and safe retention.

Only cleanup deletes artifacts. No operation uploads, deploys, or fetches weather.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import urlsplit

import requests

from .artifact_store import (ArtifactError, ArtifactPermissionError, cleanup_plan,
                             recover_snapshot, trusted_run)
from .history_reconciliation import _safe_gaps
from .pages_package import unpack_snapshot
from .scheduling import default_tasks, restore_state

WORKFLOW = '.github/workflows/pages-manual.yml'
TTL_SECONDS = 604800
STATE_CANDIDATE_LIMIT = 12
# A just-finalized artifact can briefly be missing (404) or lack its digest in the
# API. Re-read the whole readback a bounded number of times; content mismatches,
# permission failures and invalid documents are never retried.
READBACK_RETRY_DELAYS = (3, 6, 12)


def safe_reason(error):
    """Name a failure without echoing paths, URLs, tokens or document contents.

    Only fixed sentences are shown, such as "GitHub request failed (HTTP 404)":
    letters, digits, single spaces, parentheses and slash; at least two words, each
    at most 16 characters and not starting with "/". Anything else (possible tokens,
    paths, URLs or document values) is reported by exception type only.
    """
    message = str(error)
    words = message.split(' ')
    if ((isinstance(error, ArtifactError) or type(error) is ValueError)
            and len(words) >= 2 and re.fullmatch(r'[A-Za-z0-9 ()/]{1,120}', message)
            and all(0 < len(word) <= 16 and not word.startswith('/') for word in words)):
        return type(error).__name__ + ': ' + message
    return type(error).__name__


def _read_json(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Metadata exceeds safe size')
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(document, sort_keys=True), encoding='utf-8')
    temporary.replace(path)


def public_marker(url):
    """Read a bounded public deployment marker, without GitHub credentials."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid public site URL')
    with requests.get(url, timeout=15, allow_redirects=False, stream=True,
                      headers={'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}) as response:
        if response.status_code != 200:
            raise ValueError('Deployment marker unavailable')
        body = bytearray()
        for chunk in response.iter_content(4096):
            body.extend(chunk)
            if len(body) > 16384:
                raise ValueError('Deployment marker exceeds size limit')
        return json.loads(body)


def validate_state(blob, content_id, now):
    """Reject extras rather than sanitizing potentially secret-bearing state."""
    if len(blob) > 1024 * 1024:
        raise ValueError('State exceeds safe size')
    document = json.loads(blob)
    if (not isinstance(document, dict)
            or set(document) != {'schema_version', 'content_id', 'scheduler', 'history'}
            or type(document['schema_version']) is not int or document['schema_version'] != 1
            or document['content_id'] != content_id):
        raise ValueError('Invalid state envelope')
    _, warning = restore_state(document['scheduler'], content_id, now, default_tasks(), ttl_seconds=TTL_SECONDS)
    if warning is not None or _safe_gaps(document['history']) != document['history']:
        raise ValueError('Invalid or expired scheduler state')
    return document


class CloudSnapshots:
    def __init__(self, client, env, *, now=None, unpack=unpack_snapshot, public_get=public_marker,
                 sleep=time.sleep):
        self.client, self.env, self.sleep = client, env, sleep
        self.now = now or datetime.now(timezone.utc)
        self.unpack, self.public_get = unpack, public_get
        self.root = Path(env['RUNNER_TEMP'])
        self.root.mkdir(parents=True, exist_ok=True)
        self.branch = env['DEFAULT_BRANCH']
        self.verified_versions = {}

    def _validate_inner(self, blob, target=None):
        # GitHub's trusted outer digest has already authenticated these bytes.
        with tempfile.TemporaryDirectory(dir=self.root) as scratch:
            archive = Path(scratch) / 'input.zip'
            archive.write_bytes(blob)
            metadata = self.unpack(archive, hashlib.sha256(blob).hexdigest(), Path(scratch) / 'data', now=self.now)
            key, created = metadata['content_id'], metadata['content_created_at']
            prior = self.verified_versions.get(key)
            if prior is None or datetime.fromisoformat(created.replace('Z', '+00:00')) < datetime.fromisoformat(prior.replace('Z', '+00:00')):
                self.verified_versions[key] = created
            return metadata

    def _trusted(self, record, *, allow_current=False):
        run_id = record.get('workflow_run', {}).get('id')
        run = self.client.get_run(run_id)
        if allow_current and str(run_id) == self.env['GITHUB_RUN_ID'] and run.get('status') == 'in_progress':
            run = dict(run, status='completed')
        return trusted_run(run, WORKFLOW, self.branch)

    def _snapshot(self, artifact_id, *, allow_current=False):
        record = self.client.get_metadata(int(artifact_id))
        if not self._trusted(record, allow_current=allow_current):
            raise ValueError('Artifact source run is not trusted')
        blob = self.client.download_artifact(record)
        metadata = self._validate_inner(blob)
        return record, blob, metadata

    def _output(self, result):
        path = self.env.get('GITHUB_OUTPUT')
        if path:
            with open(path, 'a', encoding='utf-8') as output:
                for key in ('sha256', 'snapshot_artifact_id', 'content_id'):
                    value = str(result[key])
                    if '\n' in value or '\r' in value:
                        raise ValueError('Unsafe output value')
                    output.write(key + '=' + value + '\n')

    def resolve(self):
        winner = recover_snapshot(self.client, self._validate_inner, None,
                                  workflow=WORKFLOW, default_branch=self.branch)
        if winner is None:
            raise ValueError('No valid trusted snapshot is available')
        blob, metadata, record = winner['archive_bytes'], winner['metadata'], winner['artifact']
        destination = self.root / 'pages-input/weather-snapshot.zip'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(blob)
        result = {'sha256': hashlib.sha256(blob).hexdigest(), 'artifact_id': record['id'],
                  'snapshot_artifact_id': record['id'], 'content_id': metadata['content_id'],
                  'content_created_at': metadata['content_created_at']}
        restored = {}
        compatible = []
        states = self.client.list_artifacts('weather-scheduler-state')
        for state in states[:STATE_CANDIDATE_LIMIT]:
            try:
                if self._trusted(state):
                    document = validate_state(self.client.download_state(state), result['content_id'], self.now)
                    saved = datetime.fromisoformat(document['scheduler']['saved_at'].replace('Z', '+00:00'))
                    compatible.append((saved, int(state['id']), document))
            except ArtifactPermissionError:
                raise
            except (ValueError, TypeError, KeyError, OSError):
                continue
        if compatible:
            _, result['state_artifact_id'], restored = max(compatible, key=lambda item: item[:2])
        _write_json(self.root / 'source-result.json', result)
        _write_json(self.root / 'source-state.json', restored)
        self._output(result)
        return result

    def deployment(self):
        """Resolve online identity/order without assuming the newest saved data is live."""
        result = {'state': 'unavailable'}
        try:
            marker = self.public_get(self.env['SITE_URL'].rstrip('/') + '/deployment.json')
        except (ValueError, OSError, requests.RequestException):
            marker = None
        if marker is not None:
            result = {'state': 'invalid'}
            fields = {'schema_version', 'content_id', 'code_sha', 'run_id', 'run_number'}
            def positive(value):
                return type(value) in (str, int) and re.fullmatch(r'[1-9][0-9]*', str(value)) is not None
            if (isinstance(marker, dict) and set(marker) == fields and type(marker['schema_version']) is int
                    and marker['schema_version'] == 1
                    and isinstance(marker['content_id'], str) and re.fullmatch('[0-9a-f]{64}', marker['content_id'])
                    and isinstance(marker['code_sha'], str) and re.fullmatch('[0-9a-f]{40}', marker['code_sha'])
                    and positive(marker['run_id']) and positive(marker['run_number'])):
                run = self.client.get_run(int(marker['run_id']))
                result = {'state': 'untrusted'}
                if (trusted_run(run, WORKFLOW, self.branch) and str(run.get('id')) == str(marker['run_id'])
                        and str(run.get('run_number')) == str(marker['run_number'])
                        and run.get('head_sha') == marker['code_sha']):
                    if int(marker['run_number']) >= int(self.env['GITHUB_RUN_NUMBER']):
                        result = {'state': 'newer_run'}
                    else:
                        # Revalidate bounded artifact candidates here as well;
                        # never trust unverified marker timestamps or artifact IDs.
                        recover_snapshot(self.client, self._validate_inner, None,
                                         workflow=WORKFLOW, default_branch=self.branch)
                        created = self.verified_versions.get(marker['content_id'])
                        result = ({'state': 'verified', 'marker': marker, 'content_created_at': created}
                                  if created is not None else {'state': 'version_unknown'})
        _write_json(self.root / 'online-deployment.json', result)
        return result

    def _readback(self, read):
        """Retry only transport/availability errors of a freshly uploaded artifact."""
        for attempt in range(len(READBACK_RETRY_DELAYS) + 1):
            try:
                return read()
            except ArtifactPermissionError:
                raise
            except ArtifactError as error:
                # The client's overall time budget never recovers within this process.
                if attempt == len(READBACK_RETRY_DELAYS) or 'time budget' in str(error):
                    raise
                print('Readback attempt %d not yet available (%s); retrying.'
                      % (attempt + 1, safe_reason(error)), file=sys.stderr)
                self.sleep(READBACK_RETRY_DELAYS[attempt])

    def verify_data(self):
        expected = _read_json(self.root / 'pages-input-result.json')
        record, blob, metadata = self._readback(
            lambda: self._snapshot(self.env['DATA_ARTIFACT_ID'], allow_current=True))
        sha = hashlib.sha256(blob).hexdigest()
        if sha != expected['sha256'] or any(metadata.get(key) != expected.get(key) for key in ('snapshot_id', 'files', 'content_id', 'content_created_at')):
            raise ValueError('Saved data readback differs from prepared data')
        result = {'artifact_id': record['id'], 'sha256': sha, 'content_id': metadata['content_id'],
                  'content_created_at': metadata['content_created_at'], 'verified': True}
        _write_json(self.root / 'saved-data.json', result)
        return result

    def verify_state(self):
        def read():
            record = self.client.get_metadata(int(self.env['STATE_ARTIFACT_ID']))
            if not self._trusted(record, allow_current=True):
                raise ValueError('Saved state source run is not trusted')
            return record, self.client.download_state(record)
        record, blob = self._readback(read)
        local = (self.root / 'pages-work/state/scheduler-state.json').read_bytes()
        if blob != local:
            raise ValueError('Saved state readback differs from prepared state')
        content_id = self.env.get('CONTENT_ID') or _read_json(self.root / 'pages-input-result.json')['content_id']
        document = validate_state(blob, content_id, self.now)
        result = {'artifact_id': record['id'], 'sha256': hashlib.sha256(blob).hexdigest(),
                  'content_id': document['content_id'], 'verified': True}
        _write_json(self.root / 'saved-state.json', result)
        return result

    def guard(self):
        current = int(self.env['GITHUB_RUN_NUMBER'])
        runs = self.client.list_workflow_runs(WORKFLOW, self.branch, max_pages=3)
        for run in runs:
            # Any event can supersede an old execution. Snapshot-source event
            # restrictions do not apply to the concurrency guard.
            if trusted_run(dict(run, event='workflow_dispatch'), WORKFLOW, self.branch) and run.get('conclusion') == 'success' and int(run['run_number']) > current:
                raise ValueError('A newer successful workflow run superseded this run')
        return {'current': True}

    def _marker_matches(self):
        try:
            marker = self.public_get(self.env['SITE_URL'].rstrip('/') + '/deployment.json')
            return (isinstance(marker, dict) and set(marker) == {'schema_version', 'content_id', 'code_sha', 'run_id', 'run_number'}
                    and type(marker['schema_version']) is int and marker['schema_version'] == 1
                    and marker['content_id'] == self.env['CONTENT_ID']
                    and marker['code_sha'] == self.env['GITHUB_SHA']
                    and str(marker['run_id']) == self.env['GITHUB_RUN_ID']
                    and str(marker['run_number']) == self.env['GITHUB_RUN_NUMBER'])
        except (ValueError, KeyError, OSError, requests.RequestException):
            return False

    def cleanup(self):
        """Reverify saved data/state in this independent job before any deletion."""
        deletions = []
        weather = self.env.get('NEW_SNAPSHOT') == 'true' and self._marker_matches()
        content_id = self.env.get('CONTENT_ID')
        records = []
        if weather:
            try:
                saved_record, _, saved = self._snapshot(self.env['DATA_ARTIFACT_ID'], allow_current=True)
                if saved['content_id'] != content_id:
                    weather = False
            except ArtifactPermissionError:
                raise
            except (ValueError, KeyError, OSError):
                weather = False
        if weather:
            for record in self.client.list_artifacts('weather-snapshot')[:100]:
                try:
                    if not self._trusted(record, allow_current=True):
                        continue
                    metadata = self._validate_inner(self.client.download_artifact(record))
                    records.append(dict(record, verified=True, content_id=metadata['content_id'],
                                        content_created_at=metadata['content_created_at']))
                except ArtifactPermissionError:
                    raise
                except (ValueError, KeyError, OSError):
                    continue
            deletions.extend(cleanup_plan(records, content_id, content_id, True, True,
                                          protected_artifact_ids=[saved_record['id']]))
        # State cleanup is independent of a data deploy, but requires this run's
        # fresh state to survive an authenticated download and schema validation.
        state_verified, states = False, []
        try:
            saved_state = self.client.get_metadata(int(self.env['STATE_ARTIFACT_ID']))
            if str(saved_state.get('workflow_run', {}).get('id')) == self.env['GITHUB_RUN_ID'] and self._trusted(saved_state, allow_current=True):
                validate_state(self.client.download_state(saved_state), content_id, self.now)
                state_verified = True
        except ArtifactPermissionError:
            raise
        except (ValueError, KeyError, TypeError, OSError):
            pass
        if state_verified:
            for record in self.client.list_artifacts('weather-scheduler-state')[:100]:
                try:
                    if not self._trusted(record, allow_current=True):
                        continue
                    blob = self.client.download_state(record)
                    state = json.loads(blob)
                    validate_state(blob, state['content_id'], self.now)
                    states.append((record, state['scheduler']['saved_at']))
                except ArtifactPermissionError:
                    raise
                except (ValueError, KeyError, TypeError, OSError):
                    continue
            states.sort(key=lambda item: datetime.fromisoformat(item[1].replace('Z', '+00:00')), reverse=True)
            deletions.extend(record['id'] for record, _ in states[2:] if record['id'] != saved_state['id'])
        deleted, failed = [], []
        for artifact_id in dict.fromkeys(deletions):
            (deleted if self.client.delete_artifact(artifact_id) else failed).append(artifact_id)
        return {'deleted': deleted, 'failed': failed}
