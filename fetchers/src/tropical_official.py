"""tropical_official task: index and per-storm files from CWA, JMA and JTWC.

Design: docs/tropical-cyclone/design.md sections 1.3-1.5, 2.2, 2.3, 3, 6.1, 11a and 11b.
Every decision function takes ``now``; only ``update_tropical_official``
reads the clock.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time

from .http_client import http_scope
from .publication import atomic_write_json
from .services.tropical_common import SourceResult, TropicalClient, name_key, stamp
from .services.tropical_cwa import fetch_cwa
from .services.tropical_jma import feed_time_of, fetch_jma
from .services.tropical_jtwc import fetch_jtwc
from .tropical_contract import (AGENCIES, MAX_PAST_TRACK, MAX_STORMS, OFFICIAL_INDEX_PATH, REQUIRED_SOURCES,
                                expected_status, format_stamp, parse_stamp, validate_official_index,
                                validate_storm_file)

# Initial values ([初值] in design.md 3.2, 3.3, 3.5, 2.3). Tune here.
STALE_AFTER = {'jtwc': timedelta(hours=15), 'jma': timedelta(hours=9), 'cwa': timedelta(hours=15)}
FAILED_SOURCE_CARRY_LIMIT = timedelta(hours=72)
ENDED_RETENTION = timedelta(hours=48)
NAME_MATCH_MAX_KM = 1500.0
FUTURE_ANALYSIS_TOLERANCE = timedelta(hours=1)
MINT_ORDER = ('jma', 'jtwc', 'cwa')
EARTH_RADIUS_KM = 6371.0
STORMS_DIR = 'tropical/official/storms'
# Byte limits of design.md 6.1, measured in the published layout.
MAX_ANALYSIS_BYTES = 256 * 1024
MAX_FORECAST_BYTES = 64 * 1024
MAX_OFFICIAL_BYTES = 1024 * 1024


class AllSourcesFailed(RuntimeError):
    """Nothing is written; the previous index stays (design.md 3.3)."""


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def is_active(agency, analysis_time, ended, now):
    """Active = no end marker and the analysis is not older than the agency threshold."""
    return not ended and analysis_time >= now - STALE_AFTER[agency]


def _minute(now):
    return format_stamp(now.replace(second=0, microsecond=0))


def _bound(storm, record):
    """Rule 1: the agency identifier is already bound to this storm in the same season."""
    if storm['season'] != record['season']:
        return False
    ids = storm['ids']
    if record['agency'] == 'jma':
        return ids['jma_tc'] == record['ids']['jma_tc']
    if record['agency'] == 'jtwc':
        return ids['jtwc'] == record['ids']['jtwc']
    return any(record['ids'][key] is not None and ids[key] == record['ids'][key]
               for key in ('cwa_td', 'cwa_ty'))


def _latest_position(storm):
    known = [value for value in storm['summary'].values() if value is not None]
    newest = max(known, key=lambda value: value['analysis_time'])
    return newest['lat'], newest['lon']


def _mint_id(record):
    agency = record['agency']
    if agency == 'jma':
        code = record['ids']['jma_tc'].lower()
    elif agency == 'jtwc':
        code = record['ids']['jtwc'].lower()
    else:
        code = ('td' + record['ids']['cwa_td'] if record['ids']['cwa_td'] is not None
                else 'ty' + record['ids']['cwa_ty'])
    return f"{record['season']}-{agency}-{code}"


def _apply(storm, record, how, now, applied=None):
    agency = record['agency']
    for key, value in record['ids'].items():
        if value is not None:
            storm['ids'][key] = value
    if storm['match'][agency] != 'origin':
        storm['match'][agency] = how
    if record['name'] is not None and (storm['name'] is None or agency == 'jma'):
        storm['name'] = record['name']
    if record['name_zh'] is not None:
        storm['name_zh'] = record['name_zh']
    if agency == 'jtwc':
        storm['origin_basin'] = record['origin_basin']
    stamp = format_stamp(record['analysis_time'])
    previous = storm['summary'][agency]
    if previous is not None and previous['analysis_time'] > stamp:
        # Never regress to an older analysis, and never let it revive a system
        # the newer one ended: only the stale threshold is re-applied.
        previous['active'] = previous['active'] and is_active(
            agency, parse_stamp(previous['analysis_time']), False, now)
        return
    if applied is not None:
        # The per-storm files take this agency's block from the same record (design.md 11b #1).
        applied[(storm['cyclone_id'], agency)] = record
    storm['summary'][agency] = {
        'analysis_time': stamp, 'active': is_active(agency, record['analysis_time'], record['ended'], now),
        'lat': record['lat'], 'lon': record['lon'], 'category': record['category'],
        'max_wind': record['max_wind'], 'pressure_hpa': record['pressure_hpa']}


def _new_storm(record):
    return {'cyclone_id': _mint_id(record), 'status': 'active', 'season': record['season'],
            'name': None, 'name_zh': None, 'origin_basin': record['origin_basin'],
            'ids': {'jtwc': None, 'jma_tc': None, 'jma_number': None, 'cwa_ty': None, 'cwa_td': None},
            'match': dict.fromkeys(AGENCIES), 'last_fix_time': None, 'ended_at': None,
            'summary': dict.fromkeys(AGENCIES)}


def _still_listed(storm, agency, listed):
    if agency == 'jtwc':
        return storm['ids']['jtwc'] in listed
    return any(storm['ids']['cwa_' + kind] is not None
               and (storm['season'], kind, storm['ids']['cwa_' + kind]) in listed for kind in ('td', 'ty'))


def build_index(previous, results, now, applied=None):
    """Pure decision: previous index (validated dict or None) + source results -> new index.

    ``applied`` (optional dict) receives ``(cyclone_id, agency) -> record`` for
    every summary replaced in this run.
    """
    now = now.astimezone(timezone.utc)
    for agency in AGENCIES:
        # An analysis from the future is a broken source value: it would stay "active" indefinitely.
        sane = [record for record in results[agency].records
                if record['analysis_time'] <= now + FUTURE_ANALYSIS_TOLERANCE]
        if len(sane) != len(results[agency].records):
            results[agency].records = sane
            results[agency].fail('parse_error')
    states = {agency: results[agency].state for agency in AGENCIES}
    if expected_status(states, False) is None:
        raise AllSourcesFailed('Every tropical official source failed')
    storms = {storm['cyclone_id']: deepcopy(storm) for storm in (previous or {}).get('storms', [])}
    previous_ok = {agency: ((previous or {}).get('sources', {}).get(agency) or {}).get('last_ok_at')
                   for agency in AGENCIES}
    touched = {agency: set() for agency in AGENCIES}
    pending = []
    # Rule 1 first for every agency: an existing binding is never overturned.
    for agency in MINT_ORDER:
        for record in results[agency].records:
            target = next((identity for identity, storm in sorted(storms.items())
                           if identity not in touched[agency] and _bound(storm, record)), None)
            if target is None:
                pending.append(record)
                continue
            _apply(storms[target], record, 'id', now, applied)
            touched[agency].add(target)
    # Rule 2 (name), then rule 4 (mint). Rule 3 (position) belongs to S6b (design.md 11b).
    for record in pending:
        agency = record['agency']
        if not record['in_scope']:
            continue  # Outside the basin and not already tracked.
        target = None
        if record['name'] is not None:
            for identity, storm in sorted(storms.items()):
                if (storm['summary'][agency] is None and identity not in touched[agency]
                        and storm['season'] == record['season'] and storm['name'] is not None
                        and name_key(storm['name']) == name_key(record['name'])
                        and distance_km(record['lat'], record['lon'], *_latest_position(storm)) <= NAME_MATCH_MAX_KM):
                    target = identity
                    break
        if target is not None:
            _apply(storms[target], record, 'name', now, applied)
        elif is_active(agency, record['analysis_time'], record['ended'], now):
            storm = _new_storm(record)
            target = storm['cyclone_id']
            if target in storms:
                continue  # Never overwrite an existing system.
            storms[target] = storm
            _apply(storm, record, 'origin', now, applied)
            storm['match'][agency] = 'origin'
        else:
            continue  # Inactive leftovers never mint a system (design.md 2.2).
        touched[agency].add(target)
    # Systems this run brought no data for.
    for identity, storm in storms.items():
        for agency in AGENCIES:
            summary = storm['summary'][agency]
            if summary is None or identity in touched[agency] or not summary['active']:
                continue
            if states[agency] == 'failed':
                # Not fetched is not ended: carry the flag, up to the limit.
                # A source that never had a fully successful check is timed
                # from the analysis it did deliver.
                reference = parse_stamp(previous_ok[agency] or summary['analysis_time'])
                if now - reference > FAILED_SOURCE_CARRY_LIMIT:
                    summary['active'] = False
            elif agency == 'jma':
                # JMA has no listing rule: bulletins and the stale threshold decide.
                summary['active'] = is_active('jma', parse_stamp(summary['analysis_time']), False, now)
            elif not _still_listed(storm, agency, results[agency].listed or set()):
                # Source is fine and no longer lists it: inactive now, data kept.
                summary['active'] = False
            else:
                summary['active'] = is_active(agency, parse_stamp(summary['analysis_time']), False, now)
    kept = []
    for identity in sorted(storms):
        storm = storms[identity]
        summaries = [value for value in storm['summary'].values() if value is not None]
        storm['last_fix_time'] = max(value['analysis_time'] for value in summaries)
        if any(value['active'] for value in summaries):
            storm['status'], storm['ended_at'] = 'active', None
        else:
            storm['status'] = 'ended'
            storm['ended_at'] = storm['ended_at'] or _minute(now)
            if now > parse_stamp(storm['ended_at']) + ENDED_RETENTION:
                continue  # Retention over: leave the index.
        kept.append(storm)
    if len(kept) > MAX_STORMS:
        # Shed the longest-ended systems first; active systems are never dropped silently.
        ended = sorted((storm for storm in kept if storm['status'] == 'ended'), key=lambda storm: storm['ended_at'])
        drop = {storm['cyclone_id'] for storm in ended[:len(kept) - MAX_STORMS]}
        kept = [storm for storm in kept if storm['cyclone_id'] not in drop]
    sources = {}
    for agency in AGENCIES:
        ok = states[agency] == 'ok'
        sources[agency] = {
            'required': REQUIRED_SOURCES[agency], 'state': states[agency],
            'error_code': None if ok else results[agency].error_code or 'source_error',
            'last_ok_at': _minute(now) if ok else previous_ok[agency],
            # Systems this agency currently counts as active, consistent with storms[].summary.
            'active_count': sum(1 for storm in kept if storm['summary'][agency] is not None
                                and storm['summary'][agency]['active']) if ok else None}
    any_active = any(storm['status'] == 'active' for storm in kept)
    return {'schema_version': 1, 'basin': 'WP', 'status': expected_status(states, any_active),
            'fetched_at': format_stamp(now), 'sources': sources, 'storms': kept}


def read_previous(path):
    """A missing or invalid previous index means "no known systems" (design.md 2.2 rule 3)."""
    try:
        return validate_official_index(json.loads(Path(path).read_bytes()))
    except (OSError, ValueError):
        return None


def storm_path(identity, kind):
    return f'{STORMS_DIR}/{identity}/{kind}.json'


def read_previous_files(data_root, previous):
    """Saved analysis/forecast files of the systems the previous index lists.

    Files of systems not listed are never read: a leftover directory must not
    leak an old track into a system minted again with the same ID (11b #1).
    """
    files = {}
    for storm in (previous or {}).get('storms', []):
        identity = storm['cyclone_id']
        files[identity] = {}
        for kind in ('analysis', 'forecast'):
            path = storm_path(identity, kind)
            try:
                files[identity][kind] = validate_storm_file(path, json.loads((Path(data_root) / path).read_bytes()))
            except Exception:  # noqa: BLE001 - unreadable (even RecursionError) means "not saved".
                files[identity][kind] = None
    return files


def _saved_block(files, identity, kind, agency):
    data = (files or {}).get(identity, {}).get(kind)
    return None if data is None else data['agencies'][agency]


def _known_jma(previous, files=None):
    known = []
    for storm in (previous or {}).get('storms', []):
        summary = storm['summary']['jma']
        if storm['ids']['jma_tc'] is not None and summary is not None:
            item = {'event': storm['ids']['jma_tc'], 'active': summary['active'],
                    'analysis_time': parse_stamp(summary['analysis_time'])}
            block = _saved_block(files, storm['cyclone_id'], 'analysis', 'jma')
            # Only a saved bulletin that is the one behind the summary counts (5.3);
            # otherwise the S4 interim applies to this system.
            if block is not None and block['fix']['analysis_time'] == summary['analysis_time']:
                item.update(product_url=block['product_url'], feed_time=feed_time_of(block['product_url']),
                            issued_at=parse_stamp(block['issued_at']))
            known.append(item)
    return known


def _past_from_fix(fix):
    return {key: fix[key] for key in ('analysis_time', 'lat', 'lon', 'category', 'max_wind', 'pressure_hpa')}


def _accumulated(saved, record):
    """design.md 1.4: every fix seen, oldest first, before the new fix, at most 160."""
    points = {}
    if saved is not None:
        for point in saved['past_track'] + [_past_from_fix(saved['fix'])]:
            points[point['analysis_time']] = point
    for point in record['extra_points']:
        points[point['analysis_time']] = point
    current = stamp(record['analysis_time'])
    return [points[key] for key in sorted(points) if key < current][-MAX_PAST_TRACK:]


def build_storm_files(index, applied, files, now):
    """Return {path: data} for every system in ``index`` (design.md 1.4, 1.5, 11b)."""
    fetched = format_stamp(now)
    output = {}
    for storm in index['storms']:
        identity = storm['cyclone_id']
        analysis, forecast = {}, {}
        for agency in AGENCIES:
            record = applied.get((identity, agency))
            if record is None or record.get('analysis') is None:
                # Not fetched this run (or not newer): keep what was saved (3.3).
                analysis[agency] = deepcopy(_saved_block(files, identity, 'analysis', agency))
                forecast[agency] = deepcopy(_saved_block(files, identity, 'forecast', agency))
                continue
            block = deepcopy(record['analysis'])
            if agency == 'cwa':
                block.update(past_track_origin='source', past_track=deepcopy(record['source_track'] or []))
            else:
                block.update(past_track_origin='accumulated',
                             past_track=_accumulated(_saved_block(files, identity, 'analysis', agency), record))
            analysis[agency] = block
            # Only the latest report is kept; a report without a forecast leaves none.
            forecast[agency] = deepcopy(record.get('forecast'))
        output[storm_path(identity, 'analysis')] = {'schema_version': 1, 'cyclone_id': identity,
                                                    'fetched_at': fetched, 'agencies': analysis}
        output[storm_path(identity, 'forecast')] = {'schema_version': 1, 'cyclone_id': identity,
                                                    'fetched_at': fetched, 'agencies': forecast}
    return output


def _size(data):
    # Same layout as publication.atomic_write_json.
    return len((json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def _halve_tracks(data):
    shortened = False
    for block in data['agencies'].values():
        if block is not None and 'past_track' in block and block['past_track']:
            block['past_track'] = block['past_track'][len(block['past_track']) // 2 + len(block['past_track']) % 2:]
            shortened = True
    return shortened


def limit_sizes(index, outputs):
    """design.md 6.1: per-file limits, then the 1 MB prefix limit. Mutates and returns both."""
    for path, data in outputs.items():
        if path.endswith('/analysis.json'):
            while _size(data) > MAX_ANALYSIS_BYTES and _halve_tracks(data):
                pass
    for path in [path for path, data in outputs.items()
                 if _size(data) > (MAX_ANALYSIS_BYTES if path.endswith('/analysis.json') else MAX_FORECAST_BYTES)]:
        del outputs[path]  # Not written; any saved file stays.

    def total():
        return _size(index) + sum(_size(data) for data in outputs.values())

    # Ended systems leave first, the longest ended first. Dropping them changes
    # neither the overall status nor any active_count (they have no active agency).
    while total() > MAX_OFFICIAL_BYTES:
        ended = sorted((storm for storm in index['storms'] if storm['status'] == 'ended'),
                       key=lambda storm: (storm['ended_at'], storm['cyclone_id']))
        if not ended:
            break
        index['storms'].remove(ended[0])
        for kind in ('analysis', 'forecast'):
            outputs.pop(storm_path(ended[0]['cyclone_id'], kind), None)
    # Then every past track is halved, oldest points first; still too big fails the task.
    while total() > MAX_OFFICIAL_BYTES:
        if not [path for path, data in outputs.items() if _halve_tracks(data)]:
            raise ValueError('tropical/official exceeds its size limit')
    return index, outputs


def _guarded(fetch, *arguments):
    try:
        return fetch(*arguments)
    except Exception:  # noqa: BLE001 - a source bug is that source's failure only.
        return SourceResult().fail('source_error')


def collect(previous, now, *, transport=None, wait=time.sleep, clock=time.monotonic,
            api_key=None, policy=None, files=None):
    """Fetch the three sources inside this task's own request budget (design.md 5.4)."""
    with http_scope(policy):
        client = TropicalClient(transport, wait=wait, clock=clock)
        return {'cwa': _guarded(fetch_cwa, client, api_key),
                'jma': _guarded(fetch_jma, client, _known_jma(previous, files), now),
                'jtwc': _guarded(fetch_jtwc, client)}


def update_tropical_official(data_root, *, now=None, transport=None, wait=time.sleep,
                             clock=time.monotonic, api_key=None, policy=None):
    """Write the per-storm files and then ``tropical/official/index.json``; return the index.

    Raises when every source failed; the caller then keeps the previous files.
    The task never deletes a file: removal is the prune step's job (design.md 3.6).
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    if api_key is None:
        api_key = os.environ.get('CWA_API_KEY', '')
    root = Path(data_root)
    path = root / OFFICIAL_INDEX_PATH
    previous = read_previous(path)
    files = read_previous_files(root, previous)
    results = collect(previous, now, transport=transport, wait=wait, clock=clock,
                      api_key=api_key, policy=policy, files=files)
    applied = {}
    index = build_index(previous, results, now, applied)
    outputs = build_storm_files(index, applied, files, now)
    index, outputs = limit_sizes(index, outputs)
    index = validate_official_index(index)
    for name, data in sorted(outputs.items()):
        try:
            validate_storm_file(name, data)
        except ValueError:
            continue  # Should not happen; the saved file (if any) stays (design.md 11b #1).
        atomic_write_json(data, root / name, prefix='.tropical-official-')
    # The index goes last, so a failure above leaves the previous index in place.
    return atomic_write_json(index, path, prefix='.tropical-official-')
