"""ECMWF open-data tropical cyclone tracks in BUFR (design.md 1.7, 2.4, 5.4, 8, 11e).

``decode_tracks`` is the only function that touches the BUFR package: it turns
bytes into neutral dictionaries, so swapping ``pybufrkit`` for another decoder
changes nothing else (design.md 8). The package is imported lazily, so a broken
install fails only this source, never the import of the other tasks.
"""
from datetime import datetime, timezone
import re

from .tropical_common import clean_name, normalize_lat, normalize_lon

BASE = 'https://data.ecmwf.int/forecasts'
# model -> (model directory, stream) for the deterministic tf products.
DETERMINISTIC = {'ifs': ('ifs', 'oper'), 'aifs': ('aifs-single', 'oper')}
STORM_ID = re.compile(r'([0-9]{2})([A-Z])')
GENERATED_FROM = 70  # [實測] model-generated systems; the boundary is [待驗證] (design.md 12 #7)
MAX_TAU_H = 480

# Descriptors of template 3 16 082.
STORM_IDENTIFIER, LONG_NAME, MEMBER, ENSEMBLE_TYPE = 1025, 1027, 1091, 1092
YEAR, MONTH, DAY, HOUR, MINUTE = 4001, 4002, 4003, 4004, 4005
SIGNIFICANCE, LATITUDE, LONGITUDE = 8005, 5002, 6002
PRESSURE, WIND_10M, REPLICATION, PERIOD = 10051, 11012, 31001, 4024
CENTRE, MAX_WIND_LOCATION, OWN_ANALYSIS = 1, 3, 5


def step_hours(model, cycle):
    """IFS: 360 h at 00/12Z, 144 h at 06/18Z; AIFS: 360 h every cycle [實測]."""
    return 360 if model == 'aifs' or cycle[8:] in ('00', '12') else 144


def track_url(model, cycle):
    directory, stream = DETERMINISTIC[model]
    day, hour = cycle[:8], cycle[8:]
    return (f'{BASE}/{day}/{hour}z/{directory}/0p25/{stream}/'
            f'{cycle}0000-{step_hours(model, cycle)}h-{stream}-tf.bufr')


def _text(value):
    if isinstance(value, bytes):
        value = value.decode('ascii', 'replace')
    return value.replace('\x00', ' ').strip() if isinstance(value, str) else None


def _subset(pairs):
    """Walk one subset in order. Before the first replication factor is the
    analysis (time 0); after it, every ``4024`` starts a forecast step."""
    info = {'id': None, 'name': None, 'member': None, 'type': None, 'time': [None] * 5,
            'analysis': None, 'own': None, 'pressure0': None, 'wind0': None, 'steps': []}
    significance, latitude, step, in_steps = None, None, None, False
    times = {YEAR: 0, MONTH: 1, DAY: 2, HOUR: 3, MINUTE: 4}
    for descriptor, value in pairs:
        if descriptor == STORM_IDENTIFIER:
            info['id'] = _text(value)
        elif descriptor == LONG_NAME:
            info['name'] = _text(value)
        elif descriptor == MEMBER:
            info['member'] = value
        elif descriptor == ENSEMBLE_TYPE:
            info['type'] = value
        elif descriptor in times and not in_steps:
            info['time'][times[descriptor]] = value
        elif descriptor == REPLICATION:
            in_steps = True
        elif descriptor == PERIOD and in_steps:
            step = {'tau': value, 'centre': None, 'pressure': None, 'wind': None}
            info['steps'].append(step)
        elif descriptor == SIGNIFICANCE:
            significance = value
        elif descriptor == LATITUDE:
            latitude = value
        elif descriptor == LONGITUDE:
            position = None if latitude is None or value is None else (latitude, value)
            latitude = None
            if not in_steps:
                if significance == CENTRE:
                    info['analysis'] = position
                elif significance == OWN_ANALYSIS:
                    info['own'] = position
            elif step is not None and significance == CENTRE:
                step['centre'] = position
        elif descriptor == PRESSURE:
            if not in_steps:
                info['pressure0'] = value
            elif step is not None:
                step['pressure'] = value
        elif descriptor == WIND_10M:
            if not in_steps:
                info['wind0'] = value
            elif step is not None:
                step['wind'] = value
    return info


def _decode_messages(body):
    """Yield one list of ``(descriptor, value)`` pairs per subset."""
    from pybufrkit.decoder import Decoder, generate_bufr_message  # lazy (module docstring)
    for message in generate_bufr_message(Decoder(), body):
        template = message.template_data.value
        for descriptors, values in zip(template.decoded_descriptors_all_subsets,
                                       template.decoded_values_all_subsets):
            yield [(getattr(d, 'id', None), v) for d, v in zip(descriptors, values)]


def _pressure(pa):
    if pa is None:
        return None
    value = round(pa / 100, 1)  # Pa -> hPa is a unit conversion (design.md 1.2)
    return value if 850 <= value <= 1100 else None


def _wind(ms):
    if ms is None:
        return None
    value = round(ms, 1)
    return value if 0 <= value <= 200 else None


def _point(tau, position, pressure, wind):
    return [tau, normalize_lat(position[0]), normalize_lon(position[1]), _pressure(pressure), _wind(wind)]


def neutral_track(info):
    """Filter and shape one decoded subset (design.md 2.4 ECMWF steps 1-2, 1.9).

    Returns None for generated systems, systems without a forecast step and
    unusable rows; otherwise ``{'id', 'name', 'member', 'type', 'init_time', 'analysis', 'track'}``.
    """
    identifier = info['id'] or ''
    matched = STORM_ID.fullmatch(identifier)
    if not matched or int(matched[1]) >= GENERATED_FROM:
        return None
    name = clean_name(info['name'])
    if name is not None and name == identifier.upper():
        name = None  # The name field repeats the identifier: no international name.
    if name is None and info['analysis'] is None:
        return None
    if any(part is None for part in info['time']):
        return None
    year, month, day, hour, minute = (int(part) for part in info['time'])
    init_time = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    track = []
    start = info['own'] or info['analysis']
    if start is not None:
        track.append(_point(0, start, info['pressure0'], info['wind0']))
    for step in info['steps']:
        tau = step['tau']
        if (type(tau) is not int or tau <= 0 or tau > MAX_TAU_H or tau % 6 or step['centre'] is None
                or (track and tau <= track[-1][0])):
            continue
        track.append(_point(tau, step['centre'], step['pressure'], step['wind']))
    if not any(point[0] > 0 for point in track):
        return None  # Only time 0: a stale analysis left after dissipation (design.md 2.4 step 2).
    return {'id': identifier, 'name': name, 'member': info['member'], 'type': info['type'],
            'init_time': init_time, 'analysis': info['analysis'], 'track': track}


def decode_tracks(body):
    """All usable tracks of one tf.bufr file. Raises ``ValueError`` on a broken file."""
    try:
        tracks = []
        for pairs in _decode_messages(body):
            track = neutral_track(_subset(pairs))
            if track is not None:
                tracks.append(track)
        return tracks
    except Exception:  # noqa: BLE001 - any decoder failure is this file's parse error.
        raise ValueError('Invalid ECMWF tropical cyclone BUFR') from None
