"""NOAA NCEP ens_tracker ATCF tracks and GFS tcvitals (design.md 1.7, 2.4, 5.4, 11e).

Plain text, standard library only. Parsers take bytes and return neutral data;
they never request anything and raise ``ValueError`` on a broken file.
"""
from datetime import datetime, timezone
import re

from .tropical_common import clean_name, normalize_lat, normalize_lon

BASE = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com'
# model -> (ens_tracker system directory, file code). Only the main files:
# never the ``p`` variants, ``avnx`` or the ensemble means (design.md 1.9, 7.7).
DETERMINISTIC = {'gfs': ('gfs', 'avno'), 'aigfs': ('aigfs', 'agfs')}
BASIN_SUFFIX = {'WP': 'W', 'CP': 'C', 'EP': 'E'}
MAX_TAU_H = 480


def track_url(model, cycle):
    system, code = DETERMINISTIC[model]
    day, hour = cycle[:8], cycle[8:]
    return f'{BASE}/ens_tracker/prod/{system}.{day}/{hour}/tctrack/{code}.t{hour}z.cyclone.trackatcfunix'


def tcvitals_url(cycle):
    day, hour = cycle[:8], cycle[8:]
    return f'{BASE}/gfs/prod/gfs.{day}/{hour}/atmos/gfs.t{hour}z.syndata.tcvitals.tm00'


def _coordinate(text, positive, negative):
    match = re.fullmatch(r'(\d{1,4})([' + positive + negative + '])', text)
    if not match:
        raise ValueError('Invalid ATCF coordinate')
    value = int(match[1]) / 10
    return value if match[2] == positive else -value


def _value(text, low, high):
    """ATCF integers: 0 (or anything outside the contract range) means no value (11e E6)."""
    try:
        value = int(text)
    except ValueError:
        raise ValueError('Invalid ATCF number') from None
    return value if value and low <= value <= high else None


def jtwc_style(basin, number):
    """``WP, 31`` -> ``31W``; other basins -> None (design.md 2.4 step 1 and 5)."""
    suffix = BASIN_SUFFIX.get(basin)
    if suffix is None or not re.fullmatch(r'\d{2}', number):
        return None
    return number + suffix


def parse_atcf(body, model, cycle):
    """Return ``{(basin, number): [[tau, lat, lon, pressure, wind], ...]}`` for one file.

    Several lines per tau (one per wind threshold) become one point; only the
    position, pressure and maximum wind are kept. Rows of another model code or
    cycle are ignored; a tau that is not a multiple of 6 or beyond 480 is dropped.
    """
    code = DETERMINISTIC[model][1].upper()
    text = body.decode('ascii')
    tracks = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(',')]
        if len(fields) < 10:
            raise ValueError('Short ATCF line')
        basin, number, stamp, _, tech, tau = fields[:6]
        if tech != code or stamp != cycle:
            continue
        tau = int(tau)
        if tau < 0 or tau > MAX_TAU_H or tau % 6:
            continue
        lat = normalize_lat(_coordinate(fields[6], 'N', 'S'))
        lon = normalize_lon(_coordinate(fields[7], 'E', 'W'))
        point = [tau, lat, lon, _value(fields[9], 850, 1100), _value(fields[8], 0, 200)]
        points = tracks.setdefault((basin, number), {})
        known = points.get(tau)
        if known is None:
            points[tau] = point
        elif known[1:3] != point[1:3]:
            raise ValueError('Conflicting ATCF positions for one tau')
    return {key: [points[tau] for tau in sorted(points)] for key, points in tracks.items()}


TCVITALS = re.compile(r'(\S{3,4})\s+(\d{2}[A-Z])\s+(\S+)\s+(\d{8})\s+(\d{4})\s+(\d{3}[NS])\s+(\d{4}[EW])\s')


def parse_tcvitals(body):
    """Return ``[{'id': '31W', 'name': 'CEMPAKA' or None, 'time': datetime, 'lat', 'lon'}]``."""
    entries = []
    for line in body.decode('ascii').splitlines():
        match = TCVITALS.match(line + ' ')
        if not match:
            continue
        try:
            moment = datetime.strptime(match[4] + match[5], '%Y%m%d%H%M').replace(tzinfo=timezone.utc)
            lat = normalize_lat(_coordinate(match[6], 'N', 'S'))
            lon = normalize_lon(_coordinate(match[7], 'E', 'W'))
        except ValueError:
            continue  # One unusable line, like an unmatched one, is skipped (review M2).
        entries.append({'id': match[2], 'name': clean_name(match[3]), 'time': moment, 'lat': lat, 'lon': lon})
    return entries
