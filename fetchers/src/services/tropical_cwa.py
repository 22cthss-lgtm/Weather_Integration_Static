"""CWA W-C0034-005 (datastore API) reduced to index records (design.md 5.3).

The API key travels only in ``params``. Nothing here logs, stores or raises
anything derived from the request URL.
"""
from datetime import datetime, timezone
import json
import re

from .tropical_common import (RSMC_LON, SourceFailure, SourceResult, clean_name, in_box,
                              make_record, normalize_lat, normalize_lon)

CWA_TROPICAL_API_URL = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005'
# The only CWA address that may appear in public data.
CWA_DATASET_PAGE = 'https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005'


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
    stamped = []
    for fix in fixes:
        moment = datetime.fromisoformat(fix['DateTime'])
        if moment.utcoffset() is None:
            raise ValueError('naive time')
        stamped.append((moment.astimezone(timezone.utc), fix))
    moment, fix = max(stamped, key=lambda item: item[0])
    lat = normalize_lat(fix['CoordinateLatitude'])
    lon = normalize_lon(fix['CoordinateLongitude'])
    wind = _number(fix.get('MaxWindSpeed'), 0, 200, optional=True)
    chinese = entry.get('CwaTyphoonName')
    chinese = chinese.strip() if isinstance(chinese, str) and chinese.strip() else None
    if chinese is not None and (len(chinese) > 40 or re.search(r'[\x00-\x1f\x7f:/?=&<>\\]', chinese)):
        chinese = None
    return make_record(
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
