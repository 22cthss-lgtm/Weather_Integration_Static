"""Shared pieces of the tropical cyclone official sources (design.md 5.3, 5.7).

Failures are reduced to fixed codes here. No exception text, URL or response
body may travel further: a CWA request URL contains the API key.
"""
from dataclasses import dataclass, field
from datetime import timezone
import re
import time
from types import SimpleNamespace

import requests

from ..http_client import SourceBudgetExceeded, http_get, source_name

# One fixed, honest identity. A blocked request is a failed source; the agent
# is never varied and no header is added to get past a block.
USER_AGENT = 'weather-integration-static/1.0 (tropical cyclone data fetcher)'
MIN_REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 15

# Western North Pacific as used for inclusion (design.md 3.1).
WNP_LAT = (0.0, 60.0)
WNP_LON = (100.0, 180.0)
# Safety net for JMA and CWA, which are assumed to publish this basin only.
RSMC_LON = (90.0, 180.0)


class SourceFailure(Exception):
    """Carries one of scheduling.SAFE_ERRORS and nothing else."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class SourceResult:
    state: str = 'ok'
    error_code: str | None = None
    records: list = field(default_factory=list)
    # Agency identifiers the source still lists; None when listing does not apply.
    listed: set | None = None

    def fail(self, code):
        """Keep the first failure; records parsed so far stay usable."""
        if self.state == 'ok':
            self.state, self.error_code = 'failed', code
        return self


class TropicalClient:
    """All tropical requests: fixed agent, spacing per source, fixed error codes."""

    def __init__(self, transport=None, *, wait=time.sleep, clock=time.monotonic):
        self.session = None if transport is None else SimpleNamespace(get=transport)
        self.wait, self.clock = wait, clock
        self.last_request = {}
        self.requested = []

    def get(self, url, *, params=None):
        source = source_name(url)
        previous = self.last_request.get(source)
        if previous is not None:
            remaining = MIN_REQUEST_INTERVAL_SECONDS - (self.clock() - previous)
            if remaining > 0:
                self.wait(remaining)
        self.requested.append(url)
        try:
            response = http_get(url, session=self.session, params=params,
                                headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
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
            body = response.content if status == 200 else b''
        except Exception:  # noqa: BLE001
            raise SourceFailure('network_error') from None
        finally:
            try:
                response.close()
            except Exception:  # noqa: BLE001
                pass
        # 403/404/5xx are failures of the source, never "no cyclone".
        if status != 200:
            raise SourceFailure('http_error')
        if not isinstance(body, bytes):
            raise SourceFailure('parse_error')
        return body


def normalize_lon(value):
    """East positive in [-180, 180); exactly 180 becomes -180.0 (design.md 1.2)."""
    value = float(value)
    # NaN, infinity or anything beyond +-180 is a broken source value, not a
    # position to fold back into range.
    if not -180.0 <= value <= 180.0:
        raise ValueError('longitude out of range')
    value = round(value, 1)
    return -180.0 if value >= 180.0 else value


def normalize_lat(value):
    value = float(value)
    if not -90.0 <= value <= 90.0:
        raise ValueError('latitude out of range')
    return round(value, 1)


def in_box(lat, lon, lon_range):
    return WNP_LAT[0] <= lat <= WNP_LAT[1] and lon_range[0] <= lon < lon_range[1]


def clean_name(value):
    """Upper-case ASCII international name or None when absent or unusable."""
    if not isinstance(value, str):
        return None
    name = re.sub(r'\s+', ' ', value.strip().upper())
    if not re.fullmatch(r'[A-Z][A-Z \-]{0,39}', name):
        return None
    return name


def name_key(value):
    """Comparison key for names: letters A-Z only (design.md 2.3 rule 2)."""
    return re.sub(r'[^A-Z]', '', value.upper()) if isinstance(value, str) else ''


def reject_dtd(body):
    """XML with a DTD or entities is refused before parsing (design.md 5.3, 8)."""
    if b'<!DOCTYPE' in body or b'<!ENTITY' in body:
        raise SourceFailure('parse_error')


def make_record(agency, *, key, season, ids, name, analysis_time, lat, lon, category,
                max_wind, pressure_hpa, ended, in_scope, name_zh=None, origin_basin='WP'):
    return {'agency': agency, 'key': key, 'season': season, 'ids': ids, 'name': name,
            'name_zh': name_zh, 'origin_basin': origin_basin, 'analysis_time': analysis_time,
            'lat': lat, 'lon': lon, 'category': category, 'max_wind': max_wind,
            'pressure_hpa': pressure_hpa, 'ended': ended, 'in_scope': in_scope,
            # Per-storm file content (design.md 1.4, 1.5). Parsers fill these;
            # ``analysis`` has no past_track: tropical_official assembles it.
            'analysis': None, 'forecast': None, 'source_track': None, 'extra_points': []}


def stamp(moment):
    """UTC, seconds, trailing Z (design.md 1.2)."""
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def past_point(record):
    """The subset of a fix kept in past_track."""
    return {'analysis_time': stamp(record['analysis_time']), 'lat': record['lat'], 'lon': record['lon'],
            'category': record['category'], 'max_wind': record['max_wind'],
            'pressure_hpa': record['pressure_hpa']}


def optional(build, default=None):
    """Per-storm file extras never fail the record the index needs (S6a review finding A).

    Radii, movement, gusts, past and forecast points are optional content: when
    one cannot be read it is left out, and the summary record stays usable.
    """
    try:
        return build()
    except Exception:  # noqa: BLE001 - any parse problem means "not available".
        return default


COMPASS_16 = ('N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
              'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW')


def note_of(text):
    """Fixed vocabulary for forecast notes (design.md 1.5, 11b #9); anything else is None."""
    if not isinstance(text, str):
        return None
    text = text.upper()
    if 'POST-TROP' in text:
        return 'POST_TROPICAL'
    if 'BECOMING EXTRATROPICAL' in text:
        return 'EXTRATROPICAL'
    if 'DISSIPATED' in text:
        return 'DISSIPATED'
    if 'DISSIPATING' in text:
        return 'DISSIPATING'
    return None
