"""JMA VPTW60 bulletins through the Atom feeds, reduced to index records.

Flow and source state follow design.md 5.3 and the JMA table in 3.3, with the
S4 interim of section 11a item 3: the index stores no bulletin URL or feed
time, so ``analysis_time`` stands in for both. It is earlier than the feed
time, which can only cause an extra long-feed download, never a missed one.
"""
from datetime import datetime, timedelta, timezone
import json
import re
import xml.etree.ElementTree as ET

from .tropical_common import (RSMC_LON, SourceFailure, SourceResult, clean_name, in_box,
                              make_record, normalize_lat, normalize_lon, reject_dtd)

JMA_EXTRA_FEED_URL = 'https://www.data.jma.go.jp/developer/xml/feed/extra.xml'
JMA_LONG_FEED_URL = 'https://www.data.jma.go.jp/developer/xml/feed/extra_l.xml'
JMA_TARGET_URL = 'https://www.jma.go.jp/bosai/typhoon/data/targetTc.json'
VPTW60_LINK = re.compile(r'https://www\.data\.jma\.go\.jp/developer/xml/data/[0-9]{14}_[0-9]+_VPTW60_[0-9]{6}\.xml')

# Initial values from design.md 5.3 / 3.3; tune here.
FEED_WINDOW = timedelta(hours=4)
LONG_FEED_WINDOW = timedelta(hours=6)
HELD_WINDOW = timedelta(hours=6)
COVERAGE_ALLOWANCE = timedelta(hours=3, minutes=30)
STALE_BULLETIN = timedelta(hours=4)
MAX_BULLETINS_PER_RUN = 12
ENDED_CLASS_CODE = 'LOW'
NORMAL_STATUS = '通常'
CANCEL_INFO_TYPE = '取消'


def _local(element):
    return element.tag.rsplit('}', 1)[-1]


def _first(root, name, **attributes):
    for element in root.iter():
        if _local(element) == name and all(element.get(k) == v for k, v in attributes.items()):
            return element
    return None


def _text(root, name, **attributes):
    element = _first(root, name, **attributes)
    return (element.text or '').strip() if element is not None else ''


def _aware(value):
    moment = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    if moment.utcoffset() is None:
        raise ValueError('naive time')
    return moment.astimezone(timezone.utc)


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


def _coordinate(info):
    degrees = _text(info, 'Coordinate', type='中心位置（度）')
    match = re.fullmatch(r'([+-][0-9]{1,2}(?:\.[0-9]+)?)([+-][0-9]{1,3}(?:\.[0-9]+)?)/', degrees)
    if match:
        return float(match[1]), float(match[2])
    minutes = _text(info, 'Coordinate', type='中心位置（度分）')
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


def parse_vptw60(body):
    """Return a record, or None for training/cancelled bulletins that carry no analysis."""
    reject_dtd(body)
    root = ET.fromstring(body)
    if _text(root, 'Status') != NORMAL_STATUS or _text(root, 'InfoType') == CANCEL_INFO_TYPE:
        return None
    event = _text(root, 'EventID')
    if not re.fullmatch(r'TC[0-9]{4}', event):
        raise ValueError('event id')
    report = _aware(_text(root, 'ReportDateTime'))
    info = None
    for candidate in root.iter():
        if _local(candidate) == 'MeteorologicalInfo':
            stamp = _first(candidate, 'DateTime')
            if stamp is not None and stamp.get('type') == '実況':
                info = candidate
                break
    if info is None:
        raise ValueError('no analysis')
    moment = _aware(_text(info, 'DateTime'))
    lat, lon = _coordinate(info)
    lat, lon = normalize_lat(lat), normalize_lon(lon)
    grade = _text(info, 'TyphoonClass')
    code = re.search(r'\(([A-Z]{1,10})\)', grade)
    code = code[1] if code else None
    knots = _optional_number(_text(info, 'WindSpeed', type='最大風速', unit='ノット'), 0, 200)
    metres = _optional_number(_text(info, 'WindSpeed', type='最大風速', unit='m/s'), 0, 200)
    naming = _first(info, 'TyphoonNamePart')
    number = _text(naming, 'Number') if naming is not None else ''
    name = _text(naming, 'Name') if naming is not None else ''
    record = make_record(
        # Assumption from the only sample (TC2638 in 2026): the two digits
        # after TC are the year of the season.
        'jma', key=event, season=2000 + int(event[2:4]),
        ids={'jma_tc': event, 'jma_number': number if re.fullmatch(r'[0-9]{4}', number) else None},
        name=clean_name(name), analysis_time=moment, lat=lat, lon=lon, category=code,
        max_wind=None if knots is None and metres is None else {'kt': knots, 'ms': metres, 'averaging_min': 10},
        pressure_hpa=_optional_number(_text(info, 'Pressure', type='中心気圧'), 850, 1100),
        # Only TyphoonClass ends a system; Remark alone does not (design.md 3.2).
        # An unknown class stays active.
        ended=code == ENDED_CLASS_CODE, in_scope=in_box(lat, lon, RSMC_LON))
    record['report_time'] = report
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


def fetch_jma(client, known, now):
    """``known``: [{'event': 'TC2638', 'analysis_time': datetime, 'active': bool}] from the previous index."""
    result = SourceResult()
    try:
        entries, oldest = parse_feed(client.get(JMA_EXTRA_FEED_URL))
    except SourceFailure as failure:
        return result.fail(failure.code)
    except Exception:  # noqa: BLE001
        return result.fail('parse_error')
    bulletins, downloaded = {}, set()

    def take(candidates, window):
        recent = sorted((item for item in candidates if now - window <= item[1]),
                        key=lambda item: item[1], reverse=True)
        for url, _ in recent:
            if url in downloaded:
                continue
            if len(downloaded) >= MAX_BULLETINS_PER_RUN:
                break
            downloaded.add(url)
            try:
                record = parse_vptw60(client.get(url))
            except SourceFailure as failure:
                result.fail(failure.code)
                continue
            except Exception:  # noqa: BLE001
                result.fail('parse_error')
                continue
            if record is None:
                continue
            current = bulletins.get(record['key'])
            if current is None or record['report_time'] > current['report_time']:
                bulletins[record['key']] = record

    take(entries, FEED_WINDOW)
    try:
        target = parse_target(client.get(JMA_TARGET_URL))
    except Exception:  # noqa: BLE001 - undocumented endpoint: fall back to the documented feeds.
        target = None

    def latest():
        times = {item['event']: item['analysis_time'] for item in known}
        for event, record in bulletins.items():
            if event not in times or record['analysis_time'] > times[event]:
                times[event] = record['analysis_time']
        return times

    def unheld():
        times = latest()
        return [event for event, category in target or () if category != ENDED_CLASS_CODE
                and (event not in times or now - times[event] > HELD_WINDOW)]

    if target is not None:
        need_long = bool(unheld())
    else:
        # Coverage is measured against what was held before this run: a bulletin
        # downloaded just now says nothing about what left the feed earlier.
        newest = max((item['analysis_time'] for item in known), default=None)
        need_long = newest is None or oldest is None or oldest > newest + COVERAGE_ALLOWANCE
    for item in known:
        fresh = bulletins.get(item['event'])
        if (item['active'] and now - item['analysis_time'] > STALE_BULLETIN
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
    result.records = list(bulletins.values())
    return result
