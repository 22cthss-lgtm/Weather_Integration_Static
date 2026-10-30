"""Bounded same-repository artifact transport and conservative retention.

Only GitHub API metadata supplies the outer archive digest. Inner validators must
verify the package/manifest and return trusted content identity and creation time.
No credentials or downloaded signed URLs are persisted or included in errors.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import re
import time
import zipfile
from urllib.parse import urlsplit
from urllib.parse import quote

import requests


class ArtifactError(ValueError):
    """An artifact cannot safely be used."""


class ArtifactPermissionError(ArtifactError):
    """Authentication/authorization failure; candidate fallback must stop."""


def trusted_run(run, workflow, default_branch):
    paths = {workflow, workflow + '@' + default_branch,
             workflow + '@refs/heads/' + default_branch}
    return (run.get('path') in paths and run.get('head_branch') == default_branch
            and run.get('event') in ('workflow_dispatch', 'schedule')
            and run.get('status') == 'completed')


def _instant(value):
    if not isinstance(value, str):
        raise ArtifactError('Invalid content timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ArtifactError('Timezone required')
    return parsed.astimezone(timezone.utc)


def _id(value):
    if type(value) is not int or value <= 0:
        raise ArtifactError('Invalid artifact/run identifier')
    return value


class GitHubArtifactClient:
    def __init__(self, repository, token, *, transport=None, timeout=20,
                 max_bytes=64 * 1024 * 1024, retries=2, sleep=time.sleep,
                 total_timeout=120, clock=time.monotonic):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ArtifactError('Invalid repository')
        if not 0 < timeout <= 120 or not 1 <= max_bytes <= 512 * 1024 * 1024 or not 0 <= retries <= 5 or not 0 < total_timeout <= 600:
            raise ArtifactError('Invalid transport limits')
        self.repository = repository
        self._token = token
        self._transport = transport or requests.request
        self.timeout, self.max_bytes, self.retries = timeout, max_bytes, retries
        self._sleep = sleep
        self._clock = clock
        self._deadline = clock() + total_timeout
        self._checked = {}
        self._base = 'https://api.github.com/repos/' + repository + '/actions/'

    def _remaining(self):
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise ArtifactError('Artifact client time budget exhausted')
        return remaining

    def _backoff(self, attempt, headers=None):
        delay = min(2 ** attempt, 8)
        retry_after = (headers or {}).get('Retry-After')
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                try:
                    delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    pass
        delay = max(0, min(delay, 30))
        if delay >= self._remaining():
            raise ArtifactError('Artifact retry exceeds client time budget')
        self._sleep(delay)

    def _request(self, method, url, *, blob=False):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.fragment:
            raise ArtifactError('Unsafe transport URL')
        if blob and not (parsed.port in (None, 443) and (
                parsed.hostname in ('objects.githubusercontent.com', 'github.com')
                or (parsed.hostname or '').endswith('.actions.githubusercontent.com')
                or (parsed.hostname or '').endswith('.blob.core.windows.net'))):
            raise ArtifactError('Untrusted artifact redirect host')
        if not blob and not url.startswith(self._base):
            raise ArtifactError('Cross-repository request refused')
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
        if not blob:
            headers['Authorization'] = 'Bearer ' + self._token
        for attempt in range(self.retries + 1):
            response = None
            try:
                response = self._transport(method, url, headers=headers, timeout=min(self.timeout, self._remaining()),
                                           allow_redirects=False, stream=True)
                status = response.status_code
                if status in (401, 403):
                    raise ArtifactPermissionError('GitHub artifact permission denied')
                if status in (429, 500, 502, 503, 504) and attempt < self.retries:
                    self._backoff(attempt, response.headers)
                    continue
                if status not in (200, 204, 301, 302, 303, 307, 308):
                    raise ArtifactError('GitHub request failed (HTTP %s)' % status)
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    self._remaining()
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ArtifactError('Response exceeds byte limit')
                    chunks.append(chunk)
                return status, response.headers, b''.join(chunks)
            except (requests.RequestException, OSError):
                if attempt == self.retries:
                    raise ArtifactError('Artifact transport failed') from None
                self._backoff(attempt)
            finally:
                if response is not None:
                    response.close()

    def _json(self, suffix):
        status, _, body = self._request('GET', self._base + suffix)
        if status != 200:
            raise ArtifactError('Unexpected API redirect')
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError):
            raise ArtifactError('Invalid API response') from None
        if not isinstance(result, dict):
            raise ArtifactError('Invalid API response')
        return result

    def list_artifacts(self, name='weather-snapshot', *, max_pages=3):
        if name not in ('weather-snapshot', 'weather-scheduler-state') or not 1 <= max_pages <= 10:
            raise ArtifactError('Invalid listing limits')
        records = []
        for page in range(1, max_pages + 1):
            result = self._json('artifacts?name=' + name + '&per_page=100&page=' + str(page))
            items = result.get('artifacts')
            if not isinstance(items, list):
                raise ArtifactError('Invalid artifact listing')
            for record in items:
                if not isinstance(record, dict):
                    raise ArtifactError('Invalid artifact metadata')
                if record.get('name') == name and not record.get('expired', False):
                    self._checked[_id(record.get('id'))] = dict(record)
                    records.append(dict(record))
            if len(items) < 100:
                break
        return records

    def get_run(self, run_id):
        run = self._json('runs/' + str(_id(run_id)))
        if run.get('repository', {}).get('full_name') != self.repository:
            raise ArtifactError('Run repository mismatch')
        return run

    def list_workflow_runs(self, workflow, branch, *, max_pages=3):
        """Bounded all-event runs for superseded-run guards."""
        if not 1 <= max_pages <= 3:
            raise ArtifactError('Invalid workflow run listing limit')
        result = []
        for page in range(1, max_pages + 1):
            document = self._json('workflows/' + quote(workflow.rsplit('/', 1)[-1], safe='')
                                  + '/runs?branch=' + quote(branch, safe='')
                                  + '&per_page=100&page=' + str(page))
            runs = document.get('workflow_runs')
            if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
                raise ArtifactError('Invalid workflow runs response')
            result.extend(runs)
            if len(runs) < 100:
                break
        return result

    def download_artifact(self, record):
        return self._download_outer(record, 'weather-snapshot')['weather-snapshot.zip']

    def download_state(self, record):
        """Return digest-verified state bytes; caller validates the safe JSON schema."""
        return self._download_outer(record, 'weather-scheduler-state')['scheduler-state.json']

    def get_metadata(self, artifact_id):
        """Always refresh same-repository metadata, including post-upload readback."""
        artifact_id = _id(artifact_id)
        trusted = self._json('artifacts/' + str(artifact_id))
        if trusted.get('id') != artifact_id:
            raise ArtifactError('Artifact identity mismatch')
        self._checked[artifact_id] = dict(trusted)
        return dict(trusted)

    def _download_outer(self, record, name):
        artifact_id = _id(record.get('id'))
        # Re-read metadata when the caller did not obtain it through this client.
        trusted = self._checked.get(artifact_id)
        if trusted is None:
            trusted = self.get_metadata(artifact_id)
        digest = trusted.get('digest', '')
        if trusted.get('name') != name or trusted.get('expired', False) or not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
            raise ArtifactError('Missing trusted artifact digest')
        url = self._base + 'artifacts/' + str(artifact_id) + '/zip'
        for redirects in range(4):
            status, headers, blob = self._request('GET', url, blob=redirects > 0)
            if status == 200:
                break
            url = headers.get('Location', '')
        else:
            raise ArtifactError('Too many artifact redirects')
        if hashlib.sha256(blob).hexdigest() != digest[7:].lower():
            raise ArtifactError('Artifact digest mismatch')
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                inventory = archive.infolist()
                names = [item.filename for item in inventory]
                allowed = ({'weather-snapshot.zip'}, {'weather-snapshot.zip', 'snapshot-info.json'}) if name == 'weather-snapshot' else ({'scheduler-state.json'},)
                if len(names) != len(set(names)) or set(names) not in allowed:
                    raise ArtifactError('Unsafe outer archive inventory')
                if any(item.file_size > self.max_bytes or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000 for item in inventory):
                    raise ArtifactError('Unsafe outer archive entry')
                if 'snapshot-info.json' in names:
                    if archive.getinfo('snapshot-info.json').file_size > 4096:
                        raise ArtifactError('Oversized public metadata')
                    info = json.loads(archive.read('snapshot-info.json'))
                    if not isinstance(info, dict) or set(info) - {'content_id', 'content_created_at', 'schema_version'}:
                        raise ArtifactError('Unsafe public metadata')
                if name == 'weather-scheduler-state' and archive.getinfo('scheduler-state.json').file_size > 1024 * 1024:
                    raise ArtifactError('State exceeds byte limit')
                return {entry: archive.read(entry) for entry in names}
        except (zipfile.BadZipFile, RuntimeError, KeyError, UnicodeError, json.JSONDecodeError):
            raise ArtifactError('Invalid outer archive') from None

    def delete_artifact(self, artifact_id):
        """Delete only IDs checked by this client's same-repo API; failures are safe."""
        if artifact_id not in self._checked or self._checked[artifact_id].get('name') not in ('weather-snapshot', 'weather-scheduler-state'):
            return False
        try:
            status, _, _ = self._request('DELETE', self._base + 'artifacts/' + str(_id(artifact_id)))
            return status == 204
        except ArtifactError:
            return False


def recover_snapshot(client, validate_inner, target, *, workflow, default_branch,
                     max_candidates=12, max_failed_versions=3):
    """Validate bounded candidates; callback must use isolated scratch targets.

    Callback receives (inner_zip_bytes, target) and returns trusted metadata.
    The returned winning bytes permit caller to install only the selected version.
    """
    if not 1 <= max_candidates <= 100 or not 1 <= max_failed_versions <= 100:
        raise ArtifactError('Invalid recovery limits')
    versions, failures = {}, 0
    for artifact in client.list_artifacts('weather-snapshot')[:max_candidates]:
        try:
            run = client.get_run(_id(artifact.get('workflow_run', {}).get('id')))
            if not trusted_run(run, workflow, default_branch):
                continue
            blob = client.download_artifact(artifact)
            metadata = dict(validate_inner(blob, target))
            content_id = metadata.get('content_id')
            if not isinstance(content_id, str) or not content_id:
                raise ArtifactError('Invalid content identity')
            created = _instant(metadata['content_created_at'])
            previous = versions.get(content_id)
            # Re-uploading the same content never promotes its original creation.
            if previous is None or created < previous[0]:
                versions[content_id] = (created, {'artifact': artifact, 'metadata': metadata, 'archive_bytes': blob})
        except ArtifactPermissionError:
            raise
        except (ArtifactError, ValueError, KeyError, TypeError, OSError):
            failures += 1
            if failures >= max_failed_versions:
                break
    return max(versions.values(), key=lambda item: item[0])[1] if versions else None


def cleanup_plan(records, online_content_id, saved_content_id, verified_saved,
                 deployment_confirmed, *, protected_artifact_ids=()):
    """Return safe deletions from trusted, manifest-verified record inventory.

    Records need id/name/verified/content_id/content_created_at; separate state
    records need verified/created_at. Unknown or incomplete protection fails closed.
    """
    if not (online_content_id and saved_content_id and verified_saved and deployment_confirmed):
        return []
    try:
        snapshots = [r for r in records if r.get('name') == 'weather-snapshot']
        states = [r for r in records if r.get('name') == 'weather-scheduler-state']
        groups = {}
        for record in snapshots:
            _id(record['id'])
            if record.get('verified') is not True or not record.get('content_id'):
                return []
            groups.setdefault(record['content_id'], []).append(record)
        if online_content_id not in groups or saved_content_id not in groups:
            return []
        created = {key: min(_instant(r['content_created_at']) for r in group) for key, group in groups.items()}
        keep_versions = set(sorted(groups, key=lambda key: created[key], reverse=True)[:5])
        keep_versions.add(online_content_id)
        if saved_content_id not in keep_versions:
            return []
        protected = set(protected_artifact_ids)
        all_ids = {r['id'] for r in snapshots + states}
        if not protected.issubset(all_ids):
            return []
        keep = set(protected)
        for key in keep_versions:
            candidates = groups[key]
            selected = next((r for r in candidates if r['id'] in protected), candidates[0])
            keep.add(selected['id'])
        for record in states:
            _id(record['id'])
            if record.get('verified') is not True:
                return []
        keep.update(r['id'] for r in sorted(states, key=lambda r: _instant(r['created_at']), reverse=True)[:2])
        return [r['id'] for r in snapshots + states if r['id'] not in keep]
    except (ValueError, KeyError, TypeError):
        return []
