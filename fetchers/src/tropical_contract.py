"""Strict public contract for tropical cyclone JSON (design.md sections 1.2, 1.3, 4.1).

Every validator raises only ``ValueError``: ``snapshots.read_resources`` treats
any other exception as a crash of the whole run, including the image products.
"""
from datetime import datetime, timedelta, timezone
import math
import re

OFFICIAL_INDEX_PATH = 'tropical/official/index.json'
AGENCIES = ('jtwc', 'jma', 'cwa')
REQUIRED_SOURCES = {'cwa': True, 'jma': True, 'jtwc': False}
STATUSES = ('OK_WITH_STORMS', 'OK_NO_STORMS', 'PARTIAL')
# Mirrors scheduling.SAFE_ERRORS; a test keeps the two in step.
SAFE_ERROR_CODES = frozenset(('source_error', 'timeout', 'http_error', 'parse_error',
                              'validation_error', 'write_error', 'network_error'))
MATCH_VALUES = ('origin', 'id', 'name', 'position')
ORIGIN_BASINS = ('WP', 'CP', 'EP')
AVERAGING_MINUTES = {'jtwc': 1, 'jma': 10, 'cwa': 10}
MAX_STORMS = 12
MAX_TEXT = 40

UTC_STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
CYCLONE_ID = re.compile(r'([0-9]{4})-(jma|jtwc|cwa)-[a-z0-9]{1,8}')
NAME = re.compile(r'[A-Z][A-Z \-]{0,39}')
ID_PATTERNS = {
    'jtwc': re.compile(r'[0-9]{2}[WCE]'),
    'jma_tc': re.compile(r'TC[0-9]{4}'),
    'jma_number': re.compile(r'[0-9]{4}'),
    'cwa_ty': re.compile(r'[0-9]{1,3}'),
    'cwa_td': re.compile(r'[0-9]{1,3}'),
}
# Free text is short and cannot carry a URL, query string or control character.
FORBIDDEN_TEXT = re.compile(r'[\x00-\x1f\x7f:/?=&<>\\]')


def _fail(message):
    raise ValueError(message)


def _exact(data, fields):
    if type(data) is not dict or set(data) != set(fields):
        _fail('Unexpected tropical resource fields')


def parse_stamp(value):
    """Return an aware UTC datetime for the only accepted form, YYYY-MM-DDTHH:MM:SSZ."""
    if type(value) is not str or not UTC_STAMP.fullmatch(value):
        _fail('Invalid UTC timestamp')
    return datetime.fromisoformat(value[:-1] + '+00:00').astimezone(timezone.utc)


def format_stamp(value):
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _number(value, low, high, *, optional=False, high_exclusive=False):
    if value is None and optional:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or value < low or value > high:
        _fail('Number out of range')
    if high_exclusive and value == high:
        _fail('Number out of range')


def _text(value, *, optional=False):
    if value is None and optional:
        return
    if (type(value) is not str or not value.strip() or len(value) > MAX_TEXT
            or FORBIDDEN_TEXT.search(value)):
        _fail('Invalid text field')


def _max_wind(agency, value):
    if value is None:
        return
    _exact(value, ('kt', 'ms', 'averaging_min'))
    _number(value['kt'], 0, 200, optional=True)
    _number(value['ms'], 0, 200, optional=True)
    if type(value['averaging_min']) is not int or value['averaging_min'] != AVERAGING_MINUTES[agency]:
        _fail('Invalid averaging period')
    # Only units the agency really provides; never a converted value.
    if (agency == 'jtwc' and value['ms'] is not None) or (agency == 'cwa' and value['kt'] is not None):
        _fail('Wind unit not provided by this agency')


def _summary(agency, value):
    """Return (analysis_time, active) or None for an absent agency."""
    if value is None:
        return None
    _exact(value, ('analysis_time', 'active', 'lat', 'lon', 'category', 'max_wind', 'pressure_hpa'))
    stamp = parse_stamp(value['analysis_time'])
    if type(value['active']) is not bool:
        _fail('Invalid active flag')
    _number(value['lat'], -90, 90)
    _number(value['lon'], -180, 180, high_exclusive=True)
    _text(value['category'], optional=True)
    _max_wind(agency, value['max_wind'])
    _number(value['pressure_hpa'], 850, 1100, optional=True)
    return stamp, value['active']


def _minute_stamp(value):
    stamp = parse_stamp(value)
    if stamp.second:
        _fail('Minute precision required')
    return stamp


def _storm(storm):
    _exact(storm, ('cyclone_id', 'status', 'season', 'name', 'name_zh', 'origin_basin', 'ids',
                   'match', 'last_fix_time', 'ended_at', 'summary'))
    identity = storm['cyclone_id']
    matched = CYCLONE_ID.fullmatch(identity) if type(identity) is str else None
    if not matched:
        _fail('Invalid cyclone_id')
    if type(storm['season']) is not int or storm['season'] != int(matched[1]):
        _fail('Season does not match cyclone_id')
    if storm['name'] is not None and (type(storm['name']) is not str or not NAME.fullmatch(storm['name'])):
        _fail('Invalid international name')
    _text(storm['name_zh'], optional=True)
    if type(storm['origin_basin']) is not str or storm['origin_basin'] not in ORIGIN_BASINS:
        _fail('Invalid origin basin')
    _exact(storm['ids'], ID_PATTERNS)
    for key, pattern in ID_PATTERNS.items():
        value = storm['ids'][key]
        if value is not None and (type(value) is not str or not pattern.fullmatch(value)):
            _fail('Invalid agency identifier')
    _exact(storm['match'], AGENCIES)
    _exact(storm['summary'], AGENCIES)
    times, active = [], False
    for agency in AGENCIES:
        how = storm['match'][agency]
        if how is not None and (type(how) is not str or how not in MATCH_VALUES):
            _fail('Invalid match value')
        summary = _summary(agency, storm['summary'][agency])
        if (summary is None) != (how is None):
            _fail('Match and summary disagree')
        if (how == 'origin') != (agency == matched[2]):
            _fail('Origin agency does not match cyclone_id')
        if summary is not None:
            times.append(summary[0])
            active = active or summary[1]
    if not times or parse_stamp(storm['last_fix_time']) != max(times):
        _fail('Invalid last_fix_time')
    if type(storm['status']) is not str or storm['status'] != ('active' if active else 'ended'):
        _fail('Storm status disagrees with agency activity')
    if active:
        if storm['ended_at'] is not None:
            _fail('Active storm cannot have ended_at')
    else:
        _minute_stamp(storm['ended_at'])
    return identity, active


def expected_status(states, any_active):
    """design.md 3.3: overall status from source states. None means 'do not write'."""
    if all(states[agency] == 'failed' for agency in AGENCIES):
        return None
    if any(states[agency] == 'failed' for agency, required in REQUIRED_SOURCES.items() if required):
        return 'PARTIAL'
    if not any_active:
        return 'OK_NO_STORMS'
    return 'PARTIAL' if states['jtwc'] == 'failed' else 'OK_WITH_STORMS'


def _official_index(data):
    _exact(data, ('schema_version', 'basin', 'status', 'fetched_at', 'sources', 'storms'))
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        _fail('Unsupported tropical schema version')
    if data['basin'] != 'WP':
        _fail('Invalid basin')
    fetched = parse_stamp(data['fetched_at'])
    _exact(data['sources'], AGENCIES)
    states = {}
    for agency in AGENCIES:
        source = data['sources'][agency]
        _exact(source, ('required', 'state', 'error_code', 'last_ok_at', 'active_count'))
        if type(source['required']) is not bool or source['required'] != REQUIRED_SOURCES[agency]:
            _fail('Invalid required flag')
        last_ok = None if source['last_ok_at'] is None else _minute_stamp(source['last_ok_at'])
        if last_ok is not None and last_ok > fetched:
            _fail('last_ok_at is in the future')
        if source['state'] == 'ok':
            if source['error_code'] is not None:
                _fail('Successful source cannot carry an error code')
            if last_ok is None or fetched - last_ok >= timedelta(minutes=1):
                _fail('Successful source requires the current last_ok_at')
            if type(source['active_count']) is not int or not 0 <= source['active_count'] <= MAX_STORMS:
                _fail('Invalid active count')
        elif source['state'] == 'failed':
            if type(source['error_code']) is not str or source['error_code'] not in SAFE_ERROR_CODES:
                _fail('Invalid error code')
            if source['active_count'] is not None:
                _fail('Failed source cannot report an active count')
        else:
            _fail('Invalid source state')
        states[agency] = source['state']
    storms = data['storms']
    if type(storms) is not list or len(storms) > MAX_STORMS:
        _fail('Invalid storm list')
    identities, any_active = [], False
    for storm in storms:
        identity, active = _storm(storm)
        identities.append(identity)
        any_active = any_active or active
    if identities != sorted(set(identities)):
        _fail('Storms must be unique and ordered by cyclone_id')
    if type(data['status']) is not str or data['status'] not in STATUSES:
        _fail('Invalid overall status')
    if data['status'] != expected_status(states, any_active):
        _fail('Overall status disagrees with sources and storms')


def validate_official_index(data):
    try:
        _official_index(data)
    except ValueError:
        raise ValueError('Invalid tropical official index') from None
    except Exception:  # noqa: BLE001 - see module docstring: nothing else may escape.
        raise ValueError('Invalid tropical official index') from None
    return data
