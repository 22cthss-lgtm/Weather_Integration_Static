"""JMA VPTW60 bulletins through the Atom feeds (design.md 5.3, 3.3, 1.4, 1.5).

Since S6 the saved ``analysis.json`` carries each system's bulletin URL, so the
flow is the one of 5.3: bulletins already saved are not downloaded again, and
coverage is measured from the saved bulletin's feed time, read from the
14-digit UTC stamp of its URL (design.md 11b #4). A system with no saved URL
(first run after the upgrade) falls back to the S4 interim of 11a #3, where
``analysis_time`` stands in for the feed time; it is earlier, which can only
cause an extra long-feed download, never a missed one.
"""
from datetime import datetime, timedelta, timezone
import json
import re
import unicodedata
import xml.etree.ElementTree as ET

from .tropical_common import (COMPASS_16, RSMC_LON, SourceFailure, SourceResult, clean_name, in_box,
                              make_record, normalize_lat, normalize_lon, optional, past_point, reject_dtd,
                              stamp)

JMA_EXTRA_FEED_URL = 'https://www.data.jma.go.jp/developer/xml/feed/extra.xml'
JMA_LONG_FEED_URL = 'https://www.data.jma.go.jp/developer/xml/feed/extra_l.xml'
JMA_TARGET_URL = 'https://www.jma.go.jp/bosai/typhoon/data/targetTc.json'
VPTW60_LINK = re.compile(r'https://www\.data\.jma\.go\.jp/developer/xml/data/([0-9]{14})_[0-9]+_VPTW60_[0-9]{6}\.xml')

# Initial values from design.md 5.3 / 3.3; tune here.
FEED_WINDOW = timedelta(hours=4)
LONG_FEED_WINDOW = timedelta(hours=6)
HELD_WINDOW = timedelta(hours=6)
COVERAGE_ALLOWANCE = timedelta(hours=3, minutes=30)
STALE_BULLETIN = timedelta(hours=4)
MAX_BULLETINS_PER_RUN = 12
MAX_FORECAST_POINTS = 24
ENDED_CLASS_CODE = 'LOW'
NORMAL_STATUS = '通常'
CANCEL_INFO_TYPE = '取消'
ANALYSIS_TYPE = '実況'
FORECAST_TYPE = re.compile(r'予報\s*([0-9]{1,3})時間後')
# 16-point kanji; the 8-point subset is used for wind-area axes. Other words
# (stationary, variable) have no sample and are not mapped (design.md 11b #11).
KANJI_16 = dict(zip(('北', '北北東', '北東', '東北東', '東', '東南東', '南東', '南南東',
                     '南', '南南西', '南西', '西南西', '西', '西北西', '北西', '北北西'), COMPASS_16))
AXIS_ALL = '全域'
# Wind areas whose threshold the bulletin states itself (design.md 11b #3).
WIND_AREAS = ('暴風域', '強風域')


def _local(element):
    return element.tag.rsplit('}', 1)[-1]


def _first(root, name, **attributes):
    for element in root.iter():
        if _local(element) == name and all(element.get(k) == v for k, v in attributes.items()):
            return element
    return None


def _all(root, name):
    return [element for element in root.iter() if _local(element) == name]


def _text(root, name, **attributes):
    element = _first(root, name, **attributes)
    return (element.text or '').strip() if element is not None else ''


def _aware(value):
    moment = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    if moment.utcoffset() is None:
        raise ValueError('naive time')
    return moment.astimezone(timezone.utc)


def feed_time_of(url):
    """Feed time of a bulletin from the UTC stamp in its URL, or None (design.md 11b #4)."""
    match = VPTW60_LINK.fullmatch(url) if isinstance(url, str) else None
    if not match:
        return None
    try:
        return datetime.strptime(match[1], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_feed(body):
    """Return (VPTW60 entries as (url, feed time), oldest feed time of any entry)."""
    reject_dtd(body)
    try:
        root = ET.fromstring(body)
        if _local(root) != 'feed':
            raise ValueError('not a feed')
        entries, times = [], []
        for entry in root:
            if _local(entry) != 'entry':
                continue
            updated = _aware(_text(entry, 'updated'))
            times.append(updated)
            link = _first(entry, 'link')
            href = link.get('href', '') if link is not None else ''
            if VPTW60_LINK.fullmatch(href):
                entries.append((href, updated))
    except SourceFailure:
        raise
    except Exception:  # noqa: BLE001
        raise SourceFailure('parse_error') from None
    return entries, (min(times) if times else None)


def _coordinate(info, tag='Coordinate'):
    degrees = _text(info, tag, type='中心位置（度）')
    match = re.fullmatch(r'([+-][0-9]{1,2}(?:\.[0-9]+)?)([+-][0-9]{1,3}(?:\.[0-9]+)?)/', degrees)
    if match:
        return float(match[1]), float(match[2])
    minutes = _text(info, tag, type='中心位置（度分）')
    match = re.fullmatch(r'([+-])([0-9]{2})([0-9]{2})([+-])([0-9]{3})([0-9]{2})/', minutes)
    if not match:
        raise ValueError('coordinate')
    lat = (int(match[2]) + int(match[3]) / 60) * (1 if match[1] == '+' else -1)
    lon = (int(match[5]) + int(match[6]) / 60) * (1 if match[4] == '+' else -1)
    return lat, lon


def _optional_number(text, low, high):
    if not text:
        return None
    number = float(text)
    if not low <= number <= high:
        raise ValueError('number out of range')
    return int(number) if number == int(number) else round(number, 1)


def _wind(info, kind):
    # Maximum wind keeps the S4 range (0-200, as the contract); gusts may reach 250.
    high = 250 if kind == '最大瞬間風速' else 200
    knots = _optional_number(_text(info, 'WindSpeed', type=kind, unit='ノット'), 0, high)
    metres = _optional_number(_text(info, 'WindSpeed', type=kind, unit='m/s'), 0, high)
    return knots, metres


def _class_code(info):
    code = re.search(r'\(([A-Z]{1,10})\)', _text(info, 'TyphoonClass'))
    return code[1] if code else None


def _radii(info):
    """Wind areas with the threshold the bulletin states; unrecognised areas are left out."""
    radii = []
    for part in _all(info, 'WarningAreaPart'):
        if part.get('type') not in WIND_AREAS:
            continue
        try:
            threshold = _optional_number(_text(part, 'WindSpeed', type='風速', unit='ノット'), 1, 200)
            sectors = []
            for axis in _all(part, 'Axis'):
                direction = _first(axis, 'Direction')
                word = ((direction.text or '').strip() or direction.get('condition', '')) if direction is not None else ''
                code = 'ALL' if word == AXIS_ALL else KANJI_16.get(word)
                if code is None or code not in ('ALL', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'):
                    raise ValueError('axis direction')
                sectors.append({'dir': code, 'radius': _optional_number(
                    _text(axis, 'Radius', unit='海里'), 0, 2000)})
            if threshold is None or not sectors or len({item['dir'] for item in sectors}) != len(sectors):
                raise ValueError('wind area')
        except ValueError:
            continue
        radii.append({'threshold': {'value': threshold, 'unit': 'kt'}, 'unit': 'nm', 'sectors': sectors})
    if len({item['threshold']['value'] for item in radii}) != len(radii):
        return []
    return sorted(radii, key=lambda item: -item['threshold']['value'])


def _movement(info):
    word = _text(info, 'Direction', type='移動方向')
    knots = _optional_number(_text(info, 'Speed', type='移動速度', unit='ノット'), 0, 200)
    kmh = _optional_number(_text(info, 'Speed', type='移動速度', unit='km/h'), 0, 400)
    text = KANJI_16.get(word)
    if text is None and knots is None and kmh is None:
        return None
    return {'direction_deg': None, 'direction_text': text, 'speed_kt': knots, 'speed_kmh': kmh}


def _max_wind(knots, metres):
    return None if knots is None and metres is None else {'kt': knots, 'ms': metres, 'averaging_min': 10}


def _gust(knots, metres):
    return None if knots is None and metres is None else {'kt': knots, 'ms': metres}


def _forecast_point(info, tau, init):
    circle = _first(info, 'ProbabilityCircle')
    if circle is None:
        raise ValueError('forecast without centre')
    lat, lon = _coordinate(circle, 'BasePoint')
    probability = None
    for radius in _all(circle, 'Radius'):
        label = unicodedata.normalize('NFKC', radius.get('type', ''))
        percent = re.fullmatch(r'([0-9]{1,3})パーセント確率半径', label)
        if radius.get('unit') == 'km' and percent:
            probability = {'radius': _optional_number((radius.text or '').strip(), 0, 2000), 'unit': 'km',
                           'probability_pct': int(percent[1])}
            if probability['radius'] is None or not 1 <= probability['probability_pct'] <= 100:
                raise ValueError('probability circle')
            break
    return {'tau_h': tau, 'valid_time': stamp(init + timedelta(hours=tau)),
            'lat': normalize_lat(lat), 'lon': normalize_lon(lon), 'category': _class_code(info),
            'max_wind': _max_wind(*_wind(info, '最大風速')), 'gust': _gust(*_wind(info, '最大瞬間風速')),
            'pressure_hpa': _optional_number(_text(info, 'Pressure', type='中心気圧'), 850, 1100),
            # 暴風警戒域 is a warning area, not a wind radius (design.md 11b #7).
            'probability_circle': probability, 'radii': [], 'note': None}


def parse_vptw60(body, url=None):
    """Return a record, or None for training/cancelled bulletins that carry no analysis."""
    reject_dtd(body)
    root = ET.fromstring(body)
    if _text(root, 'Status') != NORMAL_STATUS or _text(root, 'InfoType') == CANCEL_INFO_TYPE:
        return None
    event = _text(root, 'EventID')
    if not re.fullmatch(r'TC[0-9]{4}', event):
        raise ValueError('event id')
    report = _aware(_text(root, 'ReportDateTime'))
    info, forecasts, forecast_ok = None, {}, True
    for candidate in _all(root, 'MeteorologicalInfo'):
        moment = _first(candidate, 'DateTime')
        if moment is None:
            continue
        label = unicodedata.normalize('NFKC', moment.get('type', ''))
        if label == ANALYSIS_TYPE and info is None:
            info = candidate
        elif FORECAST_TYPE.fullmatch(label):
            tau = int(FORECAST_TYPE.fullmatch(label)[1])
            if tau in forecasts or not 1 <= tau <= 240:
                forecast_ok = False  # the forecast part is unusable, the analysis is not
            forecasts[tau] = candidate
        # Other kinds (for example estimates) are not forecast points.
    if info is None:
        raise ValueError('no analysis')
    moment = _aware(_text(info, 'DateTime'))
    lat, lon = _coordinate(info)
    lat, lon = normalize_lat(lat), normalize_lon(lon)
    code = _class_code(info)
    knots, metres = _wind(info, '最大風速')
    naming = _first(info, 'TyphoonNamePart')
    number = _text(naming, 'Number') if naming is not None else ''
    name = _text(naming, 'Name') if naming is not None else ''
    record = make_record(
        # Assumption from the only sample (TC2638 in 2026): the two digits
        # after TC are the year of the season.
        'jma', key=event, season=2000 + int(event[2:4]),
        ids={'jma_tc': event, 'jma_number': number if re.fullmatch(r'[0-9]{4}', number) else None},
        name=clean_name(name), analysis_time=moment, lat=lat, lon=lon, category=code,
        max_wind=_max_wind(knots, metres),
        pressure_hpa=_optional_number(_text(info, 'Pressure', type='中心気圧'), 850, 1100),
        # Only TyphoonClass ends a system; Remark alone does not (design.md 3.2).
        # An unknown class stays active.
        ended=code == ENDED_CLASS_CODE, in_scope=in_box(lat, lon, RSMC_LON))
    record['report_time'] = report
    record['feed_time'] = feed_time_of(url)
    if url is not None:
        serial = _text(root, 'Serial')
        bulletin = serial if re.fullmatch(r'[0-9A-Za-z]{1,8}', serial) else None
        record['analysis'] = {
            'product_url': url, 'graphic_url': None, 'issued_at': stamp(report), 'bulletin': bulletin,
            'final': record['ended'],
            'fix': {'analysis_time': stamp(moment), 'lat': lat, 'lon': lon, 'category': code,
                    'max_wind': record['max_wind'],
                    'gust': optional(lambda: _gust(*_wind(info, '最大瞬間風速'))),
                    'pressure_hpa': record['pressure_hpa'], 'movement': optional(lambda: _movement(info)),
                    'radii': optional(lambda: _radii(info), [])}}

        def forecast():
            if not forecast_ok or len(forecasts) > MAX_FORECAST_POINTS:
                raise ValueError('too many forecast points')
            return {'product_url': url, 'issued_at': stamp(report), 'bulletin': bulletin,
                    'init_time': stamp(moment),
                    'points': [_forecast_point(forecasts[tau], tau, moment) for tau in sorted(forecasts)]}
        # An unusable forecast part leaves this report without a forecast; the analysis still counts.
        record['forecast'] = optional(forecast)
    return record


def parse_target(body):
    """Return [(event id, category)] or raise ValueError for any unexpected shape."""
    payload = json.loads(body)
    if not isinstance(payload, list):
        raise ValueError('unexpected shape')
    listed = []
    for item in payload:
        event, category = item['tropicalCyclone'], item['category']
        if not isinstance(event, str) or not re.fullmatch(r'TC[0-9]{4}', event) or not isinstance(category, str):
            raise ValueError('unexpected item')
        listed.append((event, category))
    return listed


def _held_time(item):
    """Feed time of the saved bulletin; analysis_time when no URL was saved (11a #3 interim)."""
    return item.get('feed_time') or item['analysis_time']


def fetch_jma(client, known, now):
    """``known``: one dict per JMA system held before this run.

    Keys: ``event``, ``analysis_time``, ``active`` and, when ``analysis.json``
    holds a JMA bulletin, ``product_url``, ``feed_time`` and ``issued_at``.
    """
    result = SourceResult()
    try:
        entries, oldest = parse_feed(client.get(JMA_EXTRA_FEED_URL))
    except SourceFailure as failure:
        return result.fail(failure.code)
    except Exception:  # noqa: BLE001
        return result.fail('parse_error')
    saved = {item['product_url'] for item in known if item.get('product_url')}
    issued = {item['event']: item['issued_at'] for item in known if item.get('issued_at')}
    parsed, downloaded = {}, set()

    def take(candidates, window):
        recent = sorted((item for item in candidates if now - window <= item[1]),
                        key=lambda item: item[1], reverse=True)
        for url, _ in recent:
            # A bulletin already saved for one of our systems is never fetched again (5.3 step 2).
            if url in downloaded or url in saved:
                continue
            if len(downloaded) >= MAX_BULLETINS_PER_RUN:
                break
            downloaded.add(url)
            try:
                record = parse_vptw60(client.get(url), url)
            except SourceFailure as failure:
                result.fail(failure.code)
                continue
            except Exception:  # noqa: BLE001
                result.fail('parse_error')
                continue
            if record is not None:
                parsed.setdefault(record['key'], []).append(record)

    def newest():
        """Latest report per system, dropping what is not newer than the saved bulletin."""
        chosen = {}
        for event, records in parsed.items():
            record = max(records, key=lambda item: item['report_time'])
            if event in issued and record['report_time'] <= issued[event]:
                continue
            chosen[event] = record
        return chosen

    take(entries, FEED_WINDOW)
    try:
        target = parse_target(client.get(JMA_TARGET_URL))
    except Exception:  # noqa: BLE001 - undocumented endpoint: fall back to the documented feeds.
        target = None

    def held():
        times = {item['event']: _held_time(item) for item in known}
        for event, record in newest().items():
            moment = record['feed_time'] or record['analysis_time']
            if event not in times or moment > times[event]:
                times[event] = moment
        return times

    def unheld():
        times = held()
        return [event for event, category in target or () if category != ENDED_CLASS_CODE
                and (event not in times or now - times[event] > HELD_WINDOW)]

    if target is not None:
        need_long = bool(unheld())
    else:
        # Coverage is measured against what was held before this run: a bulletin
        # downloaded just now says nothing about what left the feed earlier.
        latest = max((_held_time(item) for item in known), default=None)
        need_long = latest is None or oldest is None or oldest > latest + COVERAGE_ALLOWANCE
    fresh_now = newest()
    for item in known:
        fresh = fresh_now.get(item['event'])
        if (item['active'] and now - _held_time(item) > STALE_BULLETIN
                and (fresh is None or fresh['analysis_time'] <= item['analysis_time'])):
            # The final bulletin may have been issued while this task was not running.
            need_long = True
    if need_long:
        try:
            long_entries, _ = parse_feed(client.get(JMA_LONG_FEED_URL))
        except SourceFailure as failure:
            result.fail(failure.code)
        except Exception:  # noqa: BLE001
            result.fail('parse_error')
        else:
            take(long_entries, LONG_FEED_WINDOW)
    if target is not None and unheld():
        # JMA lists a system we hold no bulletin for: never "ok and no systems".
        result.fail('validation_error')
    records = newest()
    for event, record in records.items():
        # Other bulletins of the same system seen this run join the accumulated track (11b #10).
        record['extra_points'] = [past_point(item) for item in parsed[event]
                                  if item['analysis_time'] < record['analysis_time']]
    result.records = list(records.values())
    return result
