"""JTWC RSS and the .tcw products it links, reduced to index records (design.md 5.3).

Only the RSS and product files linked from it are requested: no HTML, no
guessed file names.
"""
from datetime import datetime, timedelta, timezone
import html
import re
import xml.etree.ElementTree as ET

from .tropical_common import (WNP_LON, SourceFailure, SourceResult, clean_name, in_box,
                              make_record, normalize_lat, normalize_lon, note_of, optional, reject_dtd,
                              stamp)

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
GRAPHIC_LINK = re.compile(r'https://www\.metoc\.navy\.mil/jtwc/products/[A-Za-z0-9_.-]+\.gif')
ISSUED_TEXT = re.compile(r'Issued\s+at\s+([0-9]{2})/([0-9]{2})([0-9]{2})Z')
# First line "WTPN51 PGTW 110900" (day-hour-minute); second line ends with
# yymmddHHMMSS. Year and month come from the second line [assumption, design.md #19].
DTG_LINE = re.compile(r'\A\s*[A-Z]{4}[0-9]{2}\s+[A-Z]{4}\s+([0-9]{2})([0-9]{2})([0-9]{2})\b')
STAMP_LINE = re.compile(r'\A[^\n]*\n[^\n]*?\b([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})[ \t]*$', re.M)
MOVE_PART = re.compile(r'^[0-9]{10}\s+[0-9]{2}[A-Z]\s+\S+\s+[0-9]{3}\s+[0-9]{2}\s+([0-9]{3})\s+([0-9]{2,3})\b', re.M)
TRACK_LINE = re.compile(r'^T([0-9]{3})\s+([0-9]{2,3})([NS])\s+([0-9]{3,4})([EW])(?:[ \t]+([0-9]{3})\b)?([^\n]*)$', re.M)
RADII_PART = re.compile(r'R([0-9]{3})\s+([0-9]{3})\s+NE\s+QD\s+([0-9]{3})\s+SE\s+QD\s+([0-9]{3})\s+SW\s+QD\s+([0-9]{3})\s+NW\s+QD')
AMP_LINE = re.compile(r'^(?:AMP)?[ \t]*([0-9]{3})HR[ \t]+([^\n]+?)[ \t]*$', re.M)
GUST_TEXT = re.compile(r'MAX\s+SUSTAINED\s+WINDS\s+-\s+([0-9]{2,3})\s+KT,\s+GUSTS\s+([0-9]{2,3})\s+KT')

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
            graphics = sorted(set(GRAPHIC_LINK.findall(block)))
            issued = ISSUED_TEXT.search(block)
            systems.append({'number': number, 'final': FINAL_WARNING_TEXT in block.lower(),
                            'link': links[0] if len(links) == 1 else None,
                            'graphic': graphics[0] if len(graphics) == 1 else None,
                            'issued': issued.groups() if issued else None})
    return systems, complete


def _nearest_month(day, hour, minute, reference):
    """The day/hour/minute closest to ``reference`` in the previous, same or next month."""
    best = None
    for shift in (-1, 0, 1):
        year, month = reference.year, reference.month + shift
        if month == 0:
            year, month = year - 1, 12
        elif month == 13:
            year, month = year + 1, 1
        try:
            moment = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            continue
        if best is None or abs(moment - reference) < abs(best - reference):
            best = moment
    if best is None:
        raise ValueError('issue time')
    return best


def issued_time(text, rss_issued, analysis_time):
    """design.md 1.4 / #19: first-line DTG with the second line's month; else the RSS text."""
    dtg, created = DTG_LINE.search(text), STAMP_LINE.search(text)
    if dtg and created:
        reference = datetime(2000 + int(created[1]), int(created[2]), int(created[3]), int(created[4]),
                             int(created[5]), int(created[6]), tzinfo=timezone.utc)
        return _nearest_month(int(dtg[1]), int(dtg[2]), int(dtg[3]), reference)
    if rss_issued:
        return _nearest_month(int(rss_issued[0]), int(rss_issued[1]), int(rss_issued[2]), analysis_time)
    raise ValueError('no issue time')


def _radii(rest):
    """Wind radii of one track line; anything unexpected gives no radii, never a failed record."""
    radii = []
    for part in RADII_PART.finditer(rest):
        # ATCF writes 0 for "no radius of this strength" (design.md 1.2).
        sectors = [{'dir': direction, 'radius': int(value) or None}
                   for direction, value in zip(('NE', 'SE', 'SW', 'NW'), part.groups()[1:])]
        radii.append({'threshold': {'value': int(part[1]), 'unit': 'kt'}, 'unit': 'nm', 'sectors': sectors})
    thresholds = [item['threshold']['value'] for item in radii]
    if len(set(thresholds)) != len(radii) or len(radii) > 4 or not all(1 <= value <= 200 for value in thresholds):
        return []
    return sorted(radii, key=lambda item: -item['threshold']['value'])


def _position(lat, hemisphere, lon, side):
    return (normalize_lat(int(lat) / 10 * (1 if hemisphere == 'N' else -1)),
            normalize_lon(int(lon) / 10 * (1 if side == 'E' else -1)))


def parse_tcw(body, link, *, final, graphic=None, rss_issued=None):
    """Parse the header, track lines and remarks of a .tcw file (latin-1 text)."""
    text = body.decode('latin-1').replace('\r\n', '\n').replace('\r', '\n')
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
    record = make_record(
        'jtwc', key=number, season=2000 + int(season[1]) if season else moment.year,
        ids={'jtwc': number}, name=storm_name(number, header[3]), origin_basin=basin,
        analysis_time=moment, lat=lat, lon=lon,
        category=re.sub(r'\s+', ' ', subject[1]).strip() if subject else None,
        max_wind={'kt': wind, 'ms': None, 'averaging_min': 1}, pressure_hpa=pressure,
        ended=final,
        # Central/eastern Pacific systems count only once inside the basin.
        in_scope=basin == 'WP' or in_box(lat, lon, WNP_LON))
    issued = stamp(issued_time(text, rss_issued, moment))
    # Remarks before the warning text; the 000HR remark describes the fix and is not kept.
    notes = {int(line[1]): note_of(line[2]) for line in AMP_LINE.finditer(text.split('SUBJ:')[0])}
    lines = {}
    for line in TRACK_LINE.finditer(text):
        lines.setdefault(int(line[1]), line)
    move = MOVE_PART.search(text)
    position = text.find('WARNING POSITION')
    gust = GUST_TEXT.search(text, position) if position >= 0 else None
    movement = None
    if move and int(move[1]) <= 360 and int(move[2]) <= 200:
        movement = {'direction_deg': int(move[1]), 'direction_text': None,
                    'speed_kt': int(move[2]), 'speed_kmh': None}
    record['analysis'] = {
        'product_url': link, 'graphic_url': graphic, 'issued_at': issued, 'bulletin': header[4],
        'final': final,
        'fix': {'analysis_time': stamp(moment), 'lat': lat, 'lon': lon, 'category': record['category'],
                'max_wind': record['max_wind'],
                'gust': {'kt': int(gust[2]), 'ms': None} if gust and int(gust[2]) <= 250 else None,
                'pressure_hpa': pressure, 'movement': movement,
                'radii': _radii(lines[0][7]) if 0 in lines else []}}
    def forecast():
        points = []
        for tau in sorted(lines):
            if tau == 0:
                continue
            line = lines[tau]
            if not 1 <= tau <= 240:
                raise ValueError('tau')
            point_lat, point_lon = _position(line[2], line[3], line[4], line[5])
            knots = int(line[6]) if line[6] is not None else None
            if knots is not None and not 0 <= knots <= 200:
                raise ValueError('tcw values')
            points.append({'tau_h': tau, 'valid_time': stamp(moment + timedelta(hours=tau)),
                           'lat': point_lat, 'lon': point_lon, 'category': None,
                           'max_wind': None if knots is None else {'kt': knots, 'ms': None, 'averaging_min': 1},
                           'gust': None, 'pressure_hpa': None, 'probability_circle': None,
                           'radii': _radii(line[7]), 'note': notes.get(tau)})
        if len(points) > 24:
            raise ValueError('too many forecast points')
        return {'product_url': link, 'issued_at': issued, 'bulletin': header[4],
                'init_time': stamp(moment), 'points': points}
    # An unusable forecast part leaves this report without a forecast; the
    # analysis (and the index) still use the product.
    record['forecast'] = optional(forecast)
    return record


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
            record = parse_tcw(client.get(system['link']), system['link'], final=system['final'],
                               graphic=system['graphic'], rss_issued=system['issued'])
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
