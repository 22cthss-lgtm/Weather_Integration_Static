"""CWA W-C0034-005 (datastore API) reduced to index records (design.md 5.3).

The API key travels only in ``params``. Nothing here logs, stores or raises
anything derived from the request URL.
"""
from datetime import datetime, timedelta, timezone
import json
import re

from .tropical_common import (COMPASS_16, RSMC_LON, SourceFailure, SourceResult, clean_name, in_box,
                              make_record, normalize_lat, normalize_lon, note_of, optional, stamp)

CWA_TROPICAL_API_URL = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005'
# The only CWA address that may appear in public data.
CWA_DATASET_PAGE = 'https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005'
# Thresholds named by the API's own field names (design.md 11b #3).
WIND_CIRCLES = (('Circle25ms', 25), ('Circle15ms', 15))
MAX_PAST_TRACK = 160
MAX_FORECAST_POINTS = 24


def _number(value, low, high, *, optional=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ValueError('missing number')
    number = float(value)
    if not low <= number <= high:
        raise ValueError('number out of range')
    return int(number) if number == int(number) else round(number, 1)


def _digits(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip()
    if not re.fullmatch(r'[0-9]{1,3}', text):
        raise ValueError('invalid number code')
    return str(int(text))


def _moment(value):
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError('naive time')
    return moment.astimezone(timezone.utc)


def _wind(value):
    wind = _number(value, 0, 200, optional=True)
    return None if wind is None else {'kt': None, 'ms': wind, 'averaging_min': 10}


def _radii(fix):
    """Quadrants when given, otherwise one radius for all directions (design.md 11b #6).

    A circle that does not look as expected is left out (11b #3); it never fails the record.
    """
    radii = []
    for field, threshold in WIND_CIRCLES:
        circle = fix.get(field)
        if circle is None:
            continue
        item = optional(lambda: _circle(circle, threshold))
        if item is not None:
            radii.append(item)
    return radii


def _circle(circle, threshold):
    if not isinstance(circle, dict):
        raise ValueError('circle')
    holder = circle.get('QuadrantRadii')
    quadrants = holder.get('Radius') if isinstance(holder, dict) else None
    if quadrants:
        sectors = []
        for item in quadrants:
            if not isinstance(item, dict) or item.get('dir') not in ('NE', 'SE', 'SW', 'NW'):
                raise ValueError('quadrant')
            sectors.append({'dir': item['dir'], 'radius': _number(item.get('value'), 0, 2000, optional=True)})
        if len({item['dir'] for item in sectors}) != len(sectors):
            raise ValueError('quadrant')
    else:
        radius = _number(circle.get('Radius'), 0, 2000, optional=True)
        if radius is None:
            return None
        sectors = [{'dir': 'ALL', 'radius': radius}]
    return {'threshold': {'value': threshold, 'unit': 'm/s'}, 'unit': 'km', 'sectors': sectors}


def _point(fix):
    return {'lat': normalize_lat(fix['CoordinateLatitude']), 'lon': normalize_lon(fix['CoordinateLongitude']),
            'category': None, 'max_wind': _wind(fix.get('MaxWindSpeed')),
            'pressure_hpa': _number(fix.get('Pressure'), 850, 1100, optional=True)}


def _english(values):
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict) and item.get('lang') == 'en-us':
                return item.get('value')
    return None


def _forecast(entry):
    fixes = (entry.get('ForecastData') or {}).get('Fix') if isinstance(entry.get('ForecastData'), dict) else None
    if not fixes:
        return None
    if not isinstance(fixes, list) or len(fixes) > MAX_FORECAST_POINTS:
        raise ValueError('forecast')
    inits = {_moment(fix['InitialTime']) for fix in fixes}
    if len(inits) != 1:
        raise ValueError('forecast init')
    init = inits.pop()
    points = []
    for fix in fixes:
        tau = int(str(fix['ForecastHour']).strip())
        if not 1 <= tau <= 240:
            raise ValueError('tau')
        gust = _number(fix.get('MaxGustSpeed'), 0, 250, optional=True)
        probability = _number(fix.get('Radius70PercentProbability'), 0, 2000, optional=True)
        point = _point(fix)
        points.append({'tau_h': tau, 'valid_time': stamp(init + timedelta(hours=tau)),
                       'lat': point['lat'], 'lon': point['lon'], 'category': None,
                       'max_wind': point['max_wind'], 'gust': None if gust is None else {'kt': None, 'ms': gust},
                       'pressure_hpa': point['pressure_hpa'],
                       'probability_circle': None if probability is None else
                       {'radius': probability, 'unit': 'km', 'probability_pct': 70},
                       'radii': _radii(fix), 'note': note_of(_english(fix.get('StateTransfer')))})
    points.sort(key=lambda item: item['tau_h'])
    if len({item['tau_h'] for item in points}) != len(points):
        raise ValueError('duplicate tau')
    return {'product_url': CWA_DATASET_PAGE, 'issued_at': None, 'bulletin': None,
            'init_time': stamp(init), 'points': points}


def _record(entry):
    if not isinstance(entry, dict):
        raise ValueError('entry')
    year = str(entry['Year']).strip()
    if not re.fullmatch(r'20[0-9]{2}', year):
        raise ValueError('year')
    typhoon, depression = _digits(entry.get('CwaTyNo')), _digits(entry.get('CwaTdNo'))
    if typhoon is None and depression is None:
        raise ValueError('no CWA number')
    fixes = entry['AnalysisData']['Fix']
    if not isinstance(fixes, list) or not fixes:
        raise ValueError('no analysis')
    # Every analysis time must parse, as in S4; a repeated time keeps its last entry.
    by_time = {}
    for fix in fixes:
        by_time[_moment(fix['DateTime'])] = fix
    stamped = sorted(by_time.items(), key=lambda item: item[0])
    moment, fix = stamped[-1]
    lat = normalize_lat(fix['CoordinateLatitude'])
    lon = normalize_lon(fix['CoordinateLongitude'])
    wind = _number(fix.get('MaxWindSpeed'), 0, 200, optional=True)
    chinese = entry.get('CwaTyphoonName')
    chinese = chinese.strip() if isinstance(chinese, str) and chinese.strip() else None
    if chinese is not None and (len(chinese) > 40 or re.search(r'[\x00-\x1f\x7f:/?=&<>\\]', chinese)):
        chinese = None
    record = make_record(
        'cwa', key=('td', depression) if depression is not None else ('ty', typhoon),
        season=int(year), ids={'cwa_ty': typhoon, 'cwa_td': depression},
        name=clean_name(entry.get('TyphoonName')), name_zh=chinese,
        analysis_time=moment, lat=lat, lon=lon,
        # The datastore response has no classification field; never derived from wind.
        category=None,
        max_wind=None if wind is None else {'kt': None, 'ms': wind, 'averaging_min': 10},
        pressure_hpa=_number(fix.get('Pressure'), 850, 1100, optional=True),
        # No known end marker: StateTransfer only annotates forecast points.
        ended=False, in_scope=in_box(lat, lon, RSMC_LON))
    # The datastore response has no issue time: the analysis time stands in (11a, design.md #4).
    issued = stamp(moment)
    gust = optional(lambda: _number(fix.get('MaxGustSpeed'), 0, 250, optional=True))
    direction = fix.get('MovingDirection')
    direction = direction.strip() if isinstance(direction, str) and direction.strip() in COMPASS_16 else None
    speed = optional(lambda: _number(fix.get('MovingSpeed'), 0, 400, optional=True))
    record['analysis'] = {
        'product_url': CWA_DATASET_PAGE, 'graphic_url': None, 'issued_at': issued, 'bulletin': None,
        'final': False,
        'fix': {'analysis_time': issued, 'lat': lat, 'lon': lon, 'category': None,
                'max_wind': record['max_wind'], 'gust': None if gust is None else {'kt': None, 'ms': gust},
                'pressure_hpa': record['pressure_hpa'],
                'movement': None if direction is None and speed is None else
                {'direction_deg': None, 'direction_text': direction, 'speed_kt': None, 'speed_kmh': speed},
                'radii': _radii(fix)}}
    # CWA provides the whole past track itself (design.md 1.4 "source").
    # A past point that cannot be read is left out; it never fails the record.
    track = (optional(lambda: dict({'analysis_time': stamp(when)}, **_point(item))) for when, item in stamped[:-1])
    record['source_track'] = [point for point in track if point is not None][-MAX_PAST_TRACK:]
    # An unusable forecast part means no forecast for this report.
    record['forecast'] = optional(lambda: _forecast(entry))
    if record['forecast'] is not None:
        record['forecast']['issued_at'] = issued
    return record


def parse_cwa(body):
    """Return a SourceResult. Only an existing cyclone array counts as success."""
    result = SourceResult(listed=set())
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or str(payload.get('success')).lower() != 'true':
            raise ValueError('not successful')
        cyclones = payload['records']['TropicalCyclones']['TropicalCyclone']
        if not isinstance(cyclones, list):
            raise ValueError('unexpected shape')
    except Exception:  # noqa: BLE001 - any other shape is a parse error, never "no cyclone".
        return result.fail('parse_error')
    for entry in cyclones:
        try:
            record = _record(entry)
        except Exception:  # noqa: BLE001
            result.fail('parse_error')
            continue
        result.records.append(record)
        for kind in ('td', 'ty'):
            value = record['ids']['cwa_' + kind]
            if value is not None:
                result.listed.add((record['season'], kind, value))
    return result


def fetch_cwa(client, api_key):
    if not isinstance(api_key, str) or not api_key.strip():
        return SourceResult(listed=set()).fail('source_error')
    try:
        body = client.get(CWA_TROPICAL_API_URL, params={'Authorization': api_key.strip(), 'format': 'JSON'})
    except SourceFailure as failure:
        return SourceResult(listed=set()).fail(failure.code)
    except Exception:  # noqa: BLE001
        return SourceResult(listed=set()).fail('source_error')
    return parse_cwa(body)
