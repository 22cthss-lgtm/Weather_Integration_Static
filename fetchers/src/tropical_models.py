"""tropical_models task: deterministic model tracks from NOAA and ECMWF (S8).

Design: docs/tropical-cyclone/design.md 1.6, 1.7, 2.4, 3.5, 3.6, 5.1, 5.4, 6.1, 6.2, 11e.
Every decision function takes ``now``; only ``update_tropical_models`` reads the clock.
The task writes only ``tropical/models/``; it reads the official index and the
official ``analysis.json`` files (11e E5) and never writes them.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import time

import requests

from .http_client import SourceBudgetExceeded, http_get, http_scope, source_name
from .publication import atomic_write_compact_json, atomic_write_json
from .services import tropical_ecmwf, tropical_noaa
from .services.tropical_common import (MIN_REQUEST_INTERVAL_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT,
                                       SourceFailure, name_key)
from .tropical_contract import (AGENCIES, MAX_CHECKED_CYCLES, MAX_MODEL_CYCLES, MODEL_PROVIDER, MODELS,
                                MODELS_INDEX_PATH, OFFICIAL_INDEX_PATH, WIND_UNIT, cycle_time, format_cycle,
                                format_stamp, parse_stamp, validate_models_file, validate_models_index,
                                validate_official_index)
from .tropical_official import distance_km, position_gap, read_previous_files

SOURCE_OF = {'gfs': 'noaa', 'aigfs': 'noaa', 'ifs': 'ecmwf', 'aifs': 'ecmwf'}
# Initial values of design.md 5.4 ([初值]). Earliest wait after the cycle time,
# when to give a cycle up, and when "not published yet" becomes overdue.
EARLIEST_WAIT = {'aigfs': timedelta(hours=3.75), 'gfs': timedelta(hours=4.5),
                 'ifs': timedelta(hours=6), 'aifs': timedelta(hours=6.25)}
ABANDON_AFTER = {'aigfs': timedelta(hours=24), 'gfs': timedelta(hours=24),
                 'ifs': timedelta(hours=48), 'aifs': timedelta(hours=48)}
OVERDUE_AFTER_WAIT = timedelta(hours=6)
TCVITALS_MAX_GAP = timedelta(hours=6)
ECMWF_NAME_MAX_KM = 500.0
SEASON_GAP = 1  # 11e E9, as 11c #7
NOT_PUBLISHED = (403, 404)
CYCLE_STEP = timedelta(hours=6)
# Byte limits of design.md 6.1, measured in the published layouts.
MAX_INDEX_BYTES = 16 * 1024
MAX_CYCLE_BYTES = 24 * 1024
MAX_PREFIX_BYTES = 512 * 1024
STORMS_DIR = 'tropical/models/storms'


class AllSourcesFailed(RuntimeError):
    """Both sources failed: nothing is written and the previous index stays (design.md 5.4)."""


class ModelClient:
    """Fixed agent, one-second spacing per source; 403/404 are returned, not raised."""

    def __init__(self, transport=None, *, wait=time.sleep, clock=time.monotonic):
        self.session = None if transport is None else SimpleNamespace(get=transport)
        self.wait, self.clock = wait, clock
        self.last_request = {}
        self.requested = []

    def get(self, url):
        """Return ``(status, body)`` for 200/403/404; raise ``SourceFailure`` otherwise."""
        source = source_name(url)
        previous = self.last_request.get(source)
        if previous is not None:
            remaining = MIN_REQUEST_INTERVAL_SECONDS - (self.clock() - previous)
            if remaining > 0:
                self.wait(remaining)
        self.requested.append(url)
        try:
            response = http_get(url, session=self.session, headers={'User-Agent': USER_AGENT},
                                timeout=REQUEST_TIMEOUT_SECONDS)
        except SourceBudgetExceeded:
            raise SourceFailure('timeout') from None
        except requests.RequestException:
            raise SourceFailure('network_error') from None
        except Exception:  # noqa: BLE001 - never let a URL-bearing message out.
            raise SourceFailure('source_error') from None
        finally:
            self.last_request[source] = self.clock()
        try:
            status = response.status_code
            # The 403 bodies of NOMADS carry the client IP: they are never kept,
            # logged or parsed (5.4); http_client has already read them into memory.
            body = response.content if status == 200 else b''
        except Exception:  # noqa: BLE001
            raise SourceFailure('network_error') from None
        finally:
            try:
                response.close()
            except Exception:  # noqa: BLE001
                pass
        if status == 200 and isinstance(body, bytes):
            return 200, body
        if status in NOT_PUBLISHED:
            return status, b''
        raise SourceFailure('http_error')


def _read_valid(path, validate):
    try:
        return validate(json.loads(Path(path).read_bytes()))
    except Exception:  # noqa: BLE001 - unreadable or invalid both mean "none".
        return None


def empty_index(now):
    return {'schema_version': 1, 'fetched_at': format_stamp(now),
            'sources': {source: {'state': 'idle', 'error_code': None} for source in ('noaa', 'ecmwf')},
            'match_basis': [], 'checked': {}, 'storms': {}}


def cycle_path(identity, cycle):
    return f'{STORMS_DIR}/{identity}/{cycle}.json'


def read_previous_cycles(data_root, previous):
    """Saved cycle files the previous valid models index lists (11e E12); others are never read."""
    files = {}
    for identity, storm in (previous or {}).get('storms', {}).items():
        for item in storm['cycles']:
            path = cycle_path(identity, item['cycle'])
            try:
                files[(identity, item['cycle'])] = validate_models_file(
                    path, json.loads((Path(data_root) / path).read_bytes()))
            except Exception:  # noqa: BLE001 - unreadable means "not saved".
                continue
    return files


def due_cycles(model, now):
    """The four latest cycles whose earliest wait has passed (11e E10), oldest first."""
    latest = now - EARLIEST_WAIT[model]
    latest = latest.replace(hour=latest.hour - latest.hour % 6, minute=0, second=0, microsecond=0)
    return [latest - CYCLE_STEP * back for back in range(MAX_MODEL_CYCLES - 1, -1, -1)]


def _bridges(official, previous):
    """``bridge.jtwc`` carried for systems without an official JTWC number (design.md 1.6)."""
    saved = (previous or {}).get('storms', {})
    return {storm['cyclone_id']: (None if storm['ids']['jtwc'] is not None
                                  else saved.get(storm['cyclone_id'], {}).get('bridge', {}).get('jtwc'))
            for storm in official['storms']}


def _jtwc_of(storm, bridges):
    return storm['ids']['jtwc'] or bridges.get(storm['cyclone_id'])


def match_basis(active, bridges):
    return sorted(f"{storm['cyclone_id']}|{_jtwc_of(storm, bridges) or ''}|{storm['name'] or ''}"
                  for storm in active)


def bridge_from_tcvitals(entries, storm, cycle):
    """The JTWC number of a named system from tcvitals lines within 6 h of the cycle,
    or None when no line or more than one number fits (design.md 2.4 NOAA step 3)."""
    moment = cycle_time(cycle)
    found = {entry['id'] for entry in entries
             if entry['name'] is not None and name_key(entry['name']) == name_key(storm['name'])
             and abs(entry['time'] - moment) <= TCVITALS_MAX_GAP and entry['id'][-1] in 'WCE'}
    return found.pop() if len(found) == 1 else None


def known_positions(storm, official_files):
    """Official summaries plus the saved fix and past track of each agency (11e E5)."""
    points = []
    identity = storm['cyclone_id']
    analysis = (official_files or {}).get(identity, {}).get('analysis')
    for agency in AGENCIES:
        summary = storm['summary'][agency]
        if summary is not None:
            points.append((parse_stamp(summary['analysis_time']), summary['lat'], summary['lon']))
        block = None if analysis is None else analysis['agencies'][agency]
        if block is not None:
            for point in block['past_track'] + [block['fix']]:
                points.append((parse_stamp(point['analysis_time']), point['lat'], point['lon']))
    return points


def _origin(track, init_time):
    first = track[0]
    return None if first[0] != 0 else {'analysis_time': init_time, 'lat': first[1], 'lon': first[2]}


def position_target(record, eligible, pool, positions):
    """Exactly one eligible system within its own D and no other pool system within
    its own 2D (design.md 2.3 rule 3, 11c #2-#4, 11e E8); otherwise None."""
    if record is None:
        return None
    measured = {}
    for identity in pool:
        value = position_gap(positions[identity], record)
        if value is not None:
            measured[identity] = value
    within = [identity for identity in eligible if identity in measured
              and measured[identity][0] <= measured[identity][1]]
    if len(within) != 1:
        return None
    target = within[0]
    if any(identity != target and distance <= 2 * limit for identity, (distance, limit) in measured.items()):
        return None
    return target


def _nearest_distance(record, points):
    if record is None or not points:
        return None
    moment, lat, lon = min(points, key=lambda point: (abs(point[0] - record['analysis_time']),
                                                      distance_km(record['lat'], record['lon'], point[1], point[2])))
    return distance_km(record['lat'], record['lon'], lat, lon)


def match_noaa(tracks, active, bridges, positions, init_time, known_numbers=frozenset()):
    """``{cyclone_id: [(match, source_id, track)]}`` for one ATCF file (design.md 2.4).

    ``known_numbers``: JTWC numbers of every system in the official index (ended ones
    too, and their bridges). Such a track belongs to that system, so it is never
    matched by position to another one (review M3)."""
    by_jtwc = {storm['ids']['jtwc']: storm['cyclone_id'] for storm in active if storm['ids']['jtwc']}
    by_bridge = {bridges[storm['cyclone_id']]: storm['cyclone_id'] for storm in active
                 if storm['ids']['jtwc'] is None and bridges.get(storm['cyclone_id'])}
    unnumbered = [storm['cyclone_id'] for storm in active if _jtwc_of(storm, bridges) is None]
    pool = [storm['cyclone_id'] for storm in active]
    found = {}
    for (basin, number), track in sorted(tracks.items()):
        jtwc = tropical_noaa.jtwc_style(basin, number)
        if jtwc is None or not track:
            continue  # Other basins are skipped before any position check (step 5).
        if jtwc in by_jtwc:
            identity, how = by_jtwc[jtwc], 'jtwc_id'
        elif jtwc in by_bridge:
            identity, how = by_bridge[jtwc], 'tcvitals'
        elif jtwc in known_numbers:
            continue  # The number of a listed but not active system.
        else:
            identity = position_target(_origin(track, init_time), unnumbered, pool, positions)
            how = 'position'
        if identity is not None:
            found.setdefault(identity, []).append((how, basin + number, track))
    return found


def match_ecmwf(tracks, active, positions, cycle):
    """``{cyclone_id: [(match, source_id, track)]}`` for one tf.bufr file (design.md 2.4, 11e E9, E15).

    A named track first looks for the same name (500 km). Without a name match it
    may still match by position, but only an official system without a name; a
    system with another name is neither a target nor a second candidate (11c #6)."""
    year = cycle_time(cycle).year
    found = {}
    for item in tracks:
        record = _origin(item['track'], item['init_time'])
        identity, how = None, None
        named = item['name'] is not None
        if named:
            for storm in active:
                distance = _nearest_distance(record, positions[storm['cyclone_id']])
                if (storm['name'] is not None and name_key(storm['name']) == name_key(item['name'])
                        and abs(storm['season'] - year) <= SEASON_GAP
                        and distance is not None and distance <= ECMWF_NAME_MAX_KM):
                    if identity is not None:
                        identity = None
                        break
                    identity, how = storm['cyclone_id'], 'name'
        if how is None:
            other_name = [storm['cyclone_id'] for storm in active if named and storm['name'] is not None
                          and name_key(storm['name']) != name_key(item['name'])]
            pool = [storm['cyclone_id'] for storm in active if storm['cyclone_id'] not in other_name]
            eligible = pool if not named else [storm['cyclone_id'] for storm in active if storm['name'] is None]
            identity = position_target(record, eligible, pool, positions)
            how = 'position'
        if identity is not None:
            found.setdefault(identity, []).append((how, item['id'], item['track']))
    return found


def _source_state(stats, products):
    """design.md 5.4, 11e E14: a hard failure fails the source. "Not published"
    fails it only when EVERY product of the source is missing past its overdue
    time in this run (an overdue 403/404 and no 200 for that product). A product
    not requested this run (all its cycles already checked) counts as healthy, so
    one stopped product (e.g. AIFS tf) never fails a source whose other product works."""
    if stats['requests'] == 0:
        return {'state': 'idle', 'error_code': None}
    if stats['failure'] is not None:
        return {'state': 'failed', 'error_code': stats['failure']}
    if all(product['overdue'] > 0 and product['ok'] == 0 for product in products):
        return {'state': 'failed', 'error_code': 'http_error'}
    return {'state': 'ok', 'error_code': None}


def _size(data, compact):
    """UTF-8 bytes of the published layout (design.md 6.1)."""
    options = {'separators': (',', ':')} if compact else {'indent': 2}
    return len(json.dumps(data, ensure_ascii=False, allow_nan=False, **options).encode('utf-8')) + 1


def run_models(official, previous, saved, official_files, now, get):
    """Return ``(index, outputs)``; ``outputs`` maps changed cycle-file paths to data.

    ``get(url)`` returns ``(status, body)`` or raises ``SourceFailure``.
    Raises ``AllSourcesFailed`` when both sources failed.
    """
    previous = previous or empty_index(now)
    stamp_now = format_stamp(now)
    listed = {storm['cyclone_id']: storm for storm in official['storms']}
    active = [storm for storm in official['storms'] if storm['status'] == 'active']
    bridges = _bridges(official, previous)
    positions = {storm['cyclone_id']: known_positions(storm, official_files) for storm in active}
    stats = {source: {'requests': 0, 'ok': 0, 'not_yet': 0, 'overdue': 0, 'failure': None, 'stopped': False}
             for source in ('noaa', 'ecmwf')}
    per_model = {model: {'ok': 0, 'overdue': 0} for model in SOURCE_OF}

    def request(source, url):
        # After any failure other than 200/403/404 the rest of this source's
        # requests are skipped this run (design.md 11e E13).
        if stats[source]['stopped']:
            return None, b''
        stats[source]['requests'] += 1
        try:
            return get(url)
        except SourceFailure as failure:
            if stats[source]['failure'] is None:
                stats[source]['failure'] = failure.code
            stats[source]['stopped'] = True
            return None, b''

    # tcvitals bridge (11e E11): at most once, for named active systems without a number.
    needed = [storm for storm in active if storm['name'] and _jtwc_of(storm, bridges) is None]
    if needed:
        cycle = format_cycle(due_cycles('gfs', now)[-1])
        status, body = request('noaa', tropical_noaa.tcvitals_url(cycle))
        if status == 200:
            try:
                entries = tropical_noaa.parse_tcvitals(body)
            except ValueError:
                stats['noaa']['failure'] = stats['noaa']['failure'] or 'parse_error'
                entries = []
            stats['noaa']['ok'] += 1
            taken = {value for value in bridges.values() if value} | {
                storm['ids']['jtwc'] for storm in official['storms'] if storm['ids']['jtwc']}
            for storm in needed:
                number = bridge_from_tcvitals(entries, storm, cycle)
                if number is not None and number not in taken:
                    bridges[storm['cyclone_id']] = number
                    taken.add(number)
        elif status in NOT_PUBLISHED:
            stats['noaa']['not_yet'] += 1

    basis = match_basis(active, bridges)
    known_numbers = frozenset(number for storm in official['storms'] for number in
                              (storm['ids']['jtwc'], bridges.get(storm['cyclone_id'])) if number)
    checked = {} if set(basis) - set(previous['match_basis']) else {
        cycle: list(models) for cycle, models in previous['checked'].items()}

    results = {}  # (cycle, model) -> {cyclone_id: [(match, source_id, track)]}
    if active:
        for model in ('gfs', 'aigfs', 'ifs', 'aifs'):
            source = SOURCE_OF[model]
            for moment in due_cycles(model, now):
                cycle = format_cycle(moment)
                if model in checked.get(cycle, []):
                    continue
                if now > moment + ABANDON_AFTER[model]:
                    checked[cycle] = sorted(set(checked.get(cycle, [])) | {model})
                    continue
                module = tropical_noaa if source == 'noaa' else tropical_ecmwf
                status, body = request(source, module.track_url(model, cycle))
                if status in NOT_PUBLISHED:
                    overdue = now >= moment + EARLIEST_WAIT[model] + OVERDUE_AFTER_WAIT
                    stats[source]['overdue' if overdue else 'not_yet'] += 1
                    per_model[model]['overdue'] += overdue
                    continue
                if status != 200:
                    continue
                try:
                    if source == 'noaa':
                        found = match_noaa(tropical_noaa.parse_atcf(body, model, cycle), active, bridges,
                                           positions, moment, known_numbers)
                    else:
                        found = match_ecmwf([track for track in tropical_ecmwf.decode_tracks(body)
                                             if track['init_time'] == moment], active, positions, cycle)
                except ValueError:
                    stats[source]['failure'] = stats[source]['failure'] or 'parse_error'
                    continue
                stats[source]['ok'] += 1
                per_model[model]['ok'] += 1
                results[(cycle, model)] = found
                checked[cycle] = sorted(set(checked.get(cycle, [])) | {model})

    sources = {source: _source_state(stats[source], [per_model[model] for model in SOURCE_OF
                                                     if SOURCE_OF[model] == source])
               for source in ('noaa', 'ecmwf')}
    if all(value['state'] == 'failed' for value in sources.values()):
        raise AllSourcesFailed('Both model sources failed')

    # Merge: saved cycle files of systems still in the official index, then new tracks.
    files = {}
    for (identity, cycle), data in saved.items():
        if identity in listed:
            files[(identity, cycle)] = dict(data, models=dict(data['models']))
    changed = set()
    for (cycle, model), found in sorted(results.items()):
        provider = MODEL_PROVIDER[model]
        for identity, paths in found.items():
            if len(paths) != 1:
                continue  # Two tracks of one model for one system: use neither (2.4).
            how, source_id, track = paths[0]
            key = (identity, cycle)
            data = files.get(key) or {'schema_version': 1, 'cyclone_id': identity, 'cycle': cycle,
                                      'init_time': format_stamp(cycle_time(cycle)), 'fetched_at': stamp_now,
                                      'models': {}}
            data['models'][model] = {'provider': provider, 'source_id': source_id, 'match': how,
                                     'wind_unit': WIND_UNIT[provider], 'track': track}
            data['models'] = {name: data['models'][name] for name in MODELS if name in data['models']}
            data['fetched_at'] = stamp_now
            files[key] = data
            changed.add(key)
    for key in sorted(changed):
        if _size(files[key], True) > MAX_CYCLE_BYTES:
            changed.discard(key)  # Not written; the saved file (if any) stays as it was.
            if key in saved and key[0] in listed:
                files[key] = saved[key]
            else:
                files.pop(key)

    def cycles_of(identity):
        return sorted(cycle for (owner, cycle) in files if owner == identity)

    for identity in listed:
        for cycle in cycles_of(identity)[:-MAX_MODEL_CYCLES]:
            files.pop((identity, cycle))
            changed.discard((identity, cycle))

    def build_index():
        storms = {}
        for identity in sorted(listed):
            cycles = cycles_of(identity)
            if cycles or bridges.get(identity):
                storms[identity] = {'bridge': {'jtwc': bridges.get(identity)},
                                    'cycles': [{'cycle': cycle, 'models': sorted(files[(identity, cycle)]['models'])}
                                               for cycle in cycles]}
        newest = sorted(checked)[-MAX_CHECKED_CYCLES:]
        return {'schema_version': 1, 'fetched_at': stamp_now, 'sources': sources, 'match_basis': basis,
                'checked': {cycle: checked[cycle] for cycle in newest}, 'storms': storms}

    # Prefix limit (6.1): oldest cycle of an ended system first, then of an active one.
    index = build_index()
    while (_size(index, False) + sum(_size(data, True) for data in files.values())) > MAX_PREFIX_BYTES:
        candidates = sorted(((listed[identity]['status'] != 'ended', cycle, identity)
                             for (identity, cycle) in files), key=lambda item: (item[0], item[1]))
        if not candidates:
            break
        _, cycle, identity = candidates[0]
        files.pop((identity, cycle))
        changed.discard((identity, cycle))
        index = build_index()
    if _size(index, False) > MAX_INDEX_BYTES:
        raise ValueError('tropical/models index exceeds its size limit')
    outputs = {cycle_path(identity, cycle): files[(identity, cycle)] for identity, cycle in sorted(changed)}
    return index, outputs


def update_tropical_models(data_root, *, now=None, transport=None, wait=time.sleep,
                           clock=time.monotonic, policy=None):
    """Write changed cycle files (compact) and then ``tropical/models/index.json``.

    An unreadable or invalid official index changes nothing (and writes an empty
    index only when none exists yet). Never deletes a file: removal is the prune
    step's job (design.md 3.6). Raises ``AllSourcesFailed`` when both sources failed.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    root = Path(data_root)
    path = root / MODELS_INDEX_PATH
    previous = _read_valid(path, validate_models_index)
    official = _read_valid(root / OFFICIAL_INDEX_PATH, validate_official_index)
    if official is None:
        if previous is not None:
            return previous
        return atomic_write_json(validate_models_index(empty_index(now)), path, prefix='.tropical-models-')
    saved = read_previous_cycles(root, previous)
    official_files = read_previous_files(root, official)
    with http_scope(policy):
        client = ModelClient(transport, wait=wait, clock=clock)
        index, outputs = run_models(official, previous, saved, official_files, now, client.get)
    index = validate_models_index(index)
    for name, data in sorted(outputs.items()):
        try:
            validate_models_file(name, data)
        except ValueError:
            continue  # Should not happen; the saved file (if any) stays.
        atomic_write_compact_json(data, root / name, prefix='.tropical-models-')
    return atomic_write_json(index, path, prefix='.tropical-models-')
