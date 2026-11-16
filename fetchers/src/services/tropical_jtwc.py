"""JTWC RSS and the .tcw products it links, reduced to index records (design.md 5.3).

Only the RSS and product files linked from it are requested: no HTML, no
guessed file names.
"""
from datetime import datetime, timezone
import html
import re
import xml.etree.ElementTree as ET

from .tropical_common import (WNP_LON, SourceFailure, SourceResult, clean_name, in_box,
                              make_record, normalize_lat, normalize_lon, reject_dtd)

JTWC_RSS_URL = 'https://www.metoc.navy.mil/jtwc/rss/jtwc.rss'
PRODUCT_LINK = re.compile(r'https://www\.metoc\.navy\.mil/jtwc/products/[A-Za-z0-9_.-]+')
WNP_GUID = 'NWPAC-NIO-WARNINGS'
CPAC_GUID = 'EPAC-CPAC-WARNINGS'
NO_WARNINGS_TEXT = 'No Current Tropical Cyclone Warnings.'
FINAL_WARNING_TEXT = 'final warning'
SYSTEM_HEADER = re.compile(r'\b([0-9]{2}[A-Z])\s*\(([^)]*)\)\s*Warning\s*#\s*([0-9]+)')
# W: western North Pacific. C/E: central/eastern Pacific, included only once
# the analysis position is inside the basin. A/B (North Indian Ocean) share the
# western item and are excluded by suffix.
BASIN_BY_SUFFIX = {'W': 'WP', 'C': 'CP', 'E': 'EP'}
HEADER_LINE = re.compile(r'^([0-9]{10})\s+([0-9]{2}[A-Z])\s+(\S+)\s+([0-9]{3})\b', re.M)
FIX_LINE = re.compile(r'^T000\s+([0-9]{2,3})([NS])\s+([0-9]{3,4})([EW])\s+([0-9]{3})\b', re.M)
SUBJECT_LINE = re.compile(r'^SUBJ:\s+([A-Z][A-Z \-]{1,38}?)\s+[0-9]{2}[A-Z]\s+\(', re.M)
PRESSURE_TEXT = re.compile(r'MINIMUM\s+CENTRAL\s+PRESSURE\s+AT\s+[0-9]{6}Z\s+IS\s+([0-9]{3,4})\s+MB')
SEASON_IN_FILE = re.compile(r'/[a-z]{2}[0-9]{2}([0-9]{2})\.tcw')

_ONES = ('ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN FOURTEEN '
         'FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN').split()
_TENS = 'TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY'.split()


def number_words(value):
    if value < 20:
        return _ONES[value]
    tens, ones = divmod(value, 10)
    return _TENS[tens - 2] + (_ONES[ones] if ones else '')


def storm_name(number, raw):
    """Unnamed systems are assumed to carry the spelled-out number as a name.

    That convention is not confirmed by a saved sample. The check only removes
    a name that is exactly the system's own number in words, so a wrong
    assumption leaves real names untouched.
    """
    name = clean_name(raw)
    if name is None or re.sub(r'[^A-Z]', '', name) == number_words(int(number[:2])):
        return None
    return name


def parse_rss(body):
    """Return (systems, complete). Raises SourceFailure when the feed is unusable.

    ``systems`` is a list of dicts with number, final and the .tcw link (or None).
    ``complete`` is False when a listed system could not be read in full.
    """
    reject_dtd(body)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise SourceFailure('parse_error') from None
    items = {}
    for item in root.iter('item'):
        guid = (item.findtext('guid') or '').strip()
        if guid in (WNP_GUID, CPAC_GUID):
            items[guid] = item.findtext('description') or ''
    if WNP_GUID not in items:
        raise SourceFailure('parse_error')
    # Without the central/eastern item a system that crossed 180 would be missed silently.
    systems, complete = [], CPAC_GUID in items
    for guid, description in items.items():
        headers = list(SYSTEM_HEADER.finditer(description))
        if not headers:
            # Any other text is not a confirmed "no systems" answer.
            plain = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', description)))
            if NO_WARNINGS_TEXT not in plain:
                if guid == WNP_GUID:
                    raise SourceFailure('parse_error')
                complete = False
            continue
        # Split the description at each system so links stay with their system.
        starts = [header.start() for header in headers]
        for index, header in enumerate(headers):
            number = header[1]
            if number[2] not in BASIN_BY_SUFFIX:
                continue
            block = description[starts[index]:starts[index + 1] if index + 1 < len(starts) else len(description)]
            links = sorted({link for link in PRODUCT_LINK.findall(block) if link.endswith('.tcw')})
            systems.append({'number': number, 'final': FINAL_WARNING_TEXT in block.lower(),
                            'link': links[0] if len(links) == 1 else None})
    return systems, complete


def parse_tcw(body, link, *, final):
    """Parse the header and T000 line of a .tcw file (latin-1 text)."""
    text = body.decode('latin-1')
    header, fix = HEADER_LINE.search(text), FIX_LINE.search(text)
    if not header or not fix:
        raise ValueError('tcw layout')
    moment = datetime.strptime(header[1], '%Y%m%d%H').replace(tzinfo=timezone.utc)
    number = header[2]
    lat = normalize_lat(int(fix[1]) / 10 * (1 if fix[2] == 'N' else -1))
    lon = normalize_lon(int(fix[3]) / 10 * (1 if fix[4] == 'E' else -1))
    wind = int(fix[5])
    if not 0 <= wind <= 200:
        raise ValueError('tcw values')
    season = SEASON_IN_FILE.search(link)
    subject = SUBJECT_LINE.search(text)
    pressure = PRESSURE_TEXT.search(text)
    pressure = int(pressure[1]) if pressure and 850 <= int(pressure[1]) <= 1100 else None
    basin = BASIN_BY_SUFFIX[number[2]]
    return make_record(
        'jtwc', key=number, season=2000 + int(season[1]) if season else moment.year,
        ids={'jtwc': number}, name=storm_name(number, header[3]), origin_basin=basin,
        analysis_time=moment, lat=lat, lon=lon,
        category=re.sub(r'\s+', ' ', subject[1]).strip() if subject else None,
        max_wind={'kt': wind, 'ms': None, 'averaging_min': 1}, pressure_hpa=pressure,
        ended=final,
        # Central/eastern Pacific systems count only once inside the basin.
        in_scope=basin == 'WP' or in_box(lat, lon, WNP_LON))


def fetch_jtwc(client):
    result = SourceResult(listed=set())
    try:
        systems, complete = parse_rss(client.get(JTWC_RSS_URL))
    except SourceFailure as failure:
        return result.fail(failure.code)
    except Exception:  # noqa: BLE001
        return result.fail('parse_error')
    if not complete:
        result.fail('parse_error')
    for system in systems:
        result.listed.add(system['number'])
        if system['link'] is None:
            result.fail('parse_error')
            continue
        try:
            record = parse_tcw(client.get(system['link']), system['link'], final=system['final'])
            if record['key'] != system['number']:
                raise ValueError('tcw does not match the RSS system')
        except SourceFailure as failure:
            # Without the .tcw the position is unknown, so the source cannot be "ok".
            result.fail(failure.code)
        except Exception:  # noqa: BLE001
            result.fail('parse_error')
        else:
            result.records.append(record)
    return result
