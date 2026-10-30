"""Due-only orchestration built on the common candidate and package publishers."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from .content_versions import content_metadata, fetch_image_hashes, resource_identity, stamp_changed_images
from .history_reconciliation import history_due, history_scope
from .pages_package import pack_snapshot, unpack_snapshot
from .publication import atomic_write_json
from .scheduling import default_tasks, is_due, restore_state, record_result
from .snapshot_runner import belongs, run_candidate
from .snapshots import read_resources


def load_policy():
    return json.loads((Path(__file__).resolve().parents[1] / 'policies/due-runtime.json').read_text())


def _restore(document, selected, now, tasks, policy):
    history, scheduler = {}, None
    invalid = None
    if document is not None:
        invalid = 'corrupt'
    if isinstance(document, dict) and set(document) == {'schema_version', 'content_id', 'scheduler', 'history'}:
        if type(document['schema_version']) is int and document['schema_version'] == 1 and document['content_id'] == selected['content_id']:
            scheduler, history = document['scheduler'], document['history']
            invalid = None
        elif document.get('content_id') != selected['content_id']:
            invalid = 'content_mismatch'
    restored, warning = restore_state(scheduler, selected['content_id'], now, tasks,
                                      ttl_seconds=policy['state_ttl_seconds'])
    return restored, history if warning is None else {}, invalid or warning


def prepare_due(archive, sha256, work, *, mode, policy, task_config=None, state_document=None,
                update=None, now=None, image_hasher=fetch_image_hashes):
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None or mode not in ('refresh', 'publish'):
        raise ValueError('Invalid due refresh mode or instant')
    now = now.astimezone(timezone.utc)
    tasks = default_tasks() if task_config is None else task_config
    work = Path(work)
    work.mkdir(parents=True, exist_ok=False)
    seed = work / 'seed'
    selected = unpack_snapshot(archive, sha256, seed, now=now)
    scheduler, gaps, state_warning = _restore(state_document, selected, now, tasks, policy)
    hashes = dict(selected['content']['image_hashes'])
    before, _ = read_resources(seed)
    checks, chosen, occurrences, history_only = {}, [], {}, set()
    if mode == 'refresh':
        if update is None:
            raise ValueError('Refresh requires registered update entry')
        for kind, config in tasks.items():
            due, occurrence, reason = is_due(config, scheduler['tasks'][kind], now, policy['fixed'])
            if due or history_due(kind, gaps, now, policy['history']):
                chosen.append(kind)
                occurrences[kind] = occurrence
                if not due:
                    history_only.add(kind)
            checks[kind] = {'state': 'history_recheck' if kind in history_only else 'pending' if due else 'not_due',
                            'reason': reason, 'error_code': None}

    with history_scope(policy['history'], gaps, now) as context:
        def checked_update(kind, images_root):
            nonlocal hashes
            context.active_kind = kind
            old_files, _ = read_resources(Path(images_root).parent)
            old_hashes = dict(hashes)
            failure = False
            try:
                if kind in history_only:
                    from .current_day import publish_current_history
                    from .services.base import ImagePayload
                    from .services.cwa_service import CWAService
                    latest = json.loads(old_files[f'images/{kind}/latest.json'])
                    publish_current_history(CWAService(), ImagePayload(**latest), images_root, now=now)
                else:
                    update(kind, images_root)
            except Exception:
                failure = True
            after, bad = read_resources(Path(images_root).parent, strict=False)
            if any(belongs(name, kind) for name in bad):
                failure = True
            latest_ok = context.outcomes.get(kind, {}).get('latest_ok', not failure)
            latest_name = ('rainfall/rankings/latest.json' if kind == 'rainfall_rankings'
                           else f'images/{kind}/latest.json')
            if latest_name not in after or latest_name in bad:
                failure, latest_ok = True, False
                context.outcome(kind, latest_ok=False, safe_code='validation_error')
            # Daily rain is an independently validated child resource. A failed
            # latest request must not discard its successful daily update.
            daily_name = 'images/rainfall/daily/latest.json'
            preserved = ({daily_name} if kind == 'rainfall' and failure and not latest_ok
                         and context.outcomes.get(kind, {}).get('daily_ok')
                         and daily_name in after and daily_name not in bad else set())
            # A required body hash is part of validating this check, not an
            # optional Last-Modified proxy. Hash errors cannot claim success.
            if (not failure or preserved) and kind not in history_only:
                try:
                    verified_names = {name for name in after if belongs(name, kind)
                                      and (not failure or name in preserved)}
                    hashes = image_hasher({name: after[name] for name in verified_names}, hashes)
                    for name, raw in list(after.items()):
                        if name in verified_names:
                            payload = stamp_changed_images(json.loads(raw), old_hashes, hashes, now.isoformat())
                            if resource_identity(payload, hashes) != resource_identity(json.loads(old_files.get(name, b'{}')), old_hashes):
                                atomic_write_json(payload, Path(images_root).parent / name)
                    after, bad = read_resources(Path(images_root).parent, strict=False)
                except Exception:
                    failure, latest_ok = True, False
                    preserved = set()
            if failure and not latest_ok:
                # Roll back this resource family, including valid-but-unverified
                # partial writes; other products retain their own progress.
                for name in set(after) | set(bad):
                    if belongs(name, kind) and name not in old_files and name not in preserved:
                        (Path(images_root).parent / name).unlink(missing_ok=True)
                for name, raw in old_files.items():
                    if belongs(name, kind) and name not in preserved:
                        path = Path(images_root).parent / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(raw)
                if not preserved:
                    hashes = old_hashes
            # Discard check-time/cache-bust-only rewrites byte-for-byte, also
            # for successful daily data retained alongside a failed latest.
            final_valid, _ = read_resources(Path(images_root).parent, strict=False)
            for name, raw in final_valid.items():
                if belongs(name, kind) and name in old_files:
                    if resource_identity(json.loads(raw), hashes) == resource_identity(json.loads(old_files[name]), old_hashes):
                        (Path(images_root).parent / name).write_bytes(old_files[name])
            if kind not in history_only:
                record_result(scheduler, kind, now, bool(latest_ok), occurrences[kind],
                              'source_error' if not latest_ok else None, task_config=tasks)
                final, _ = read_resources(Path(images_root).parent)
                changed = any(belongs(name, kind) and old_files.get(name) != raw for name, raw in final.items())
                checks[kind].update(state='updated' if latest_ok and changed else 'checked_unchanged' if latest_ok else 'retained_after_failure',
                                    error_code=None if latest_ok else 'source_error')
                checks[kind]['outcome'] = context.outcomes.get(kind, {})
                details = checks[kind]['outcome']
                if not latest_ok and details.get('candidate_missing_count') and not details.get('candidate_fault_count') and not details.get('candidate_invalid_count'):
                    checks[kind]['reason'] = 'candidate_unavailable'
            if failure and not latest_ok:
                raise RuntimeError('Resource check failed; validated fallback retained')

        report = run_candidate(chosen, seed, work / 'store', checked_update, allow_empty=True)
        snapshot = work / 'store/snapshots' / str(report['snapshot_id'])
        data_root = snapshot / 'data' if report['publishable'] else seed
        content = content_metadata(data_root, hashes if report['publishable'] else selected['content']['image_hashes'], now.isoformat())
        changed = report['publishable'] and content['content_id'] != selected['content_id']
        if not changed:
            content = selected['content']
        scheduler['content_id'] = content['content_id']
        scheduler['saved_at'] = now.isoformat()
        state = {'schema_version': 1, 'content_id': content['content_id'], 'scheduler': scheduler, 'history': context.gaps}
        state_dir = work / 'state'
        state_dir.mkdir()
        atomic_write_json(state, state_dir / 'scheduler-state.json')
        deploy = mode == 'publish' or bool(changed)
        result = dict(report, deploy=deploy, save_snapshot=bool(changed), mode=mode,
                      checks=checks, state_warning=state_warning, scheduler_state=state,
                      content_id=content['content_id'], content_created_at=content['content_created_at'])
        if deploy:
            if changed:
                output = work / 'output/weather-snapshot.zip'
                package = pack_snapshot(snapshot, output, valid_days=policy['zip_valid_days'], now=now, content=content)
                verified = unpack_snapshot(output, package['sha256'], work / 'site-data', now=now)
                result.update(verified, sha256=package['sha256'])
            else:
                shutil.copytree(seed, work / 'site-data')
                result.update(selected, sha256=sha256)
        else:
            result.update(files=selected['files'], sha256=sha256,
                          incomplete_history=selected['incomplete_history'])
        result['reason'] = 'validated_candidate' if deploy else 'candidate_not_publishable' if any(
            item['state'] == 'no_data' for item in report['resources'].values()) else 'no_content_change'
        return result
