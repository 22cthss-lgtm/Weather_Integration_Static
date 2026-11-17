"""Helpers for tropical cyclone tests: fixtures, a strict fake transport, no network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'tropical'
UTC = timezone.utc
# Matches the real samples: CEMPAKA on 2026-11-11.
NOW = datetime(2026, 11, 11, 10, 30, tzinfo=UTC)
SECRET = 'CWA-TESTKEY-0000-NEVER-PUBLISH'

CWA_URL = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005'
JMA_FEED = 'https://www.data.jma.go.jp/developer/xml/feed/extra.xml'
JMA_LONG = 'https://www.data.jma.go.jp/developer/xml/feed/extra_l.xml'
JMA_TARGET = 'https://www.jma.go.jp/bosai/typhoon/data/targetTc.json'
JMA_BULLETIN = 'https://www.data.jma.go.jp/developer/xml/data/{}_0_VPTW60_010000.xml'
JTWC_RSS = 'https://www.metoc.navy.mil/jtwc/rss/jtwc.rss'
JTWC_PRODUCT = 'https://www.metoc.navy.mil/jtwc/products/{}'

_original_request = None


class UnexpectedRequest(BaseException):
    """Not an Exception on purpose: no ``except Exception`` in the code under
    test can turn a forbidden request into an ordinary source failure."""


def block_network():
    """Any code path that forgot to inject a transport fails loudly instead of going online."""
    global _original_request
    if _original_request is None:
        _original_request = requests.sessions.Session.request

        def refuse(self, method, url, *args, **kwargs):
            raise UnexpectedRequest('Network access attempted in a blocked test')
        requests.sessions.Session.request = refuse


def unblock_network():
    global _original_request
    if _original_request is not None:
        requests.sessions.Session.request = _original_request
        _original_request = None


def fixture(name):
    return (FIXTURES / name).read_bytes()


class FakeResponse:
    def __init__(self, status=200, content=b'', headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}
        self.closed = False

    def close(self):
        self.closed = True


class FakeTransport:
    """Maps URLs to responses. An unregistered URL is an error: nothing outside the design is requested."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def __call__(self, url, **options):
        self.calls.append((url, options))
        if url not in self.routes:
            raise UnexpectedRequest(f'Unregistered URL requested: {url}')
        route = self.routes[url]
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, BaseException):
            raise route
        if isinstance(route, FakeResponse):
            return route
        if isinstance(route, int):
            return FakeResponse(route)
        return FakeResponse(200, route)

    @property
    def urls(self):
        return [url for url, _ in self.calls]


def quiet_policy(**limits):
    """A real HttpPolicy whose retry waits return immediately."""
    from src.http_client import HttpPolicy
    return HttpPolicy(wait=lambda seconds: None, jitter=lambda: 0, **limits)


def stamp(moment):
    return moment.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def minute(moment):
    return stamp(moment.replace(second=0, microsecond=0))


def record(agency, *, when, name='CEMPAKA', lat=29.0, lon=150.0, ended=False, in_scope=True,
           number=None, season=2026, origin_basin='WP'):
    """A parsed source record as the services produce it."""
    if agency == 'jma':
        number = number or 'TC2638'
        ids, key = {'jma_tc': number, 'jma_number': None}, number
        wind = {'kt': 60, 'ms': 30, 'averaging_min': 10}
    elif agency == 'jtwc':
        number = number or '31W'
        ids, key = {'jtwc': number}, number
        wind = {'kt': 65, 'ms': None, 'averaging_min': 1}
    else:
        number = number or '35'
        ids, key = {'cwa_ty': None, 'cwa_td': number}, ('td', number)
        wind = {'kt': None, 'ms': 30, 'averaging_min': 10}
    return {'agency': agency, 'key': key, 'season': season, 'ids': ids, 'name': name, 'name_zh': None,
            'origin_basin': origin_basin, 'analysis_time': when, 'lat': lat, 'lon': lon,
            'category': 'LOW' if ended and agency == 'jma' else None, 'max_wind': wind,
            'pressure_hpa': 985, 'ended': ended, 'in_scope': in_scope}


def result(*records, state='ok', code=None, listed=None):
    from src.services.tropical_common import SourceResult
    out = SourceResult(listed=set() if listed is None else set(listed))
    out.records = list(records)
    for item in records:
        if item['agency'] == 'jtwc':
            out.listed.add(item['key'])
        elif item['agency'] == 'cwa':
            out.listed.add((item['season'], *item['key']))
    if state == 'failed':
        out.fail(code or 'http_error')
    return out


def results(cwa=None, jma=None, jtwc=None):
    return {'cwa': cwa or result(), 'jma': jma or result(), 'jtwc': jtwc or result()}


def valid_index():
    """The example of design.md 1.3 (CWA category is null: the API has no such field)."""
    return deepcopy({
        'schema_version': 1, 'basin': 'WP', 'status': 'PARTIAL', 'fetched_at': '2026-11-11T10:33:07Z',
        'sources': {
            'cwa': {'required': True, 'state': 'ok', 'error_code': None,
                    'last_ok_at': '2026-11-11T10:33:00Z', 'active_count': 1},
            'jma': {'required': True, 'state': 'ok', 'error_code': None,
                    'last_ok_at': '2026-11-11T10:33:00Z', 'active_count': 1},
            'jtwc': {'required': False, 'state': 'failed', 'error_code': 'http_error',
                     'last_ok_at': '2026-11-11T09:03:00Z', 'active_count': None}},
        'storms': [{
            'cyclone_id': '2026-jma-tc2638', 'status': 'active', 'season': 2026, 'name': 'CEMPAKA',
            'name_zh': '查帕卡', 'origin_basin': 'WP',
            'ids': {'jtwc': '31W', 'jma_tc': 'TC2638', 'jma_number': '2632', 'cwa_ty': '31', 'cwa_td': '35'},
            'match': {'jtwc': 'name', 'jma': 'origin', 'cwa': 'name'},
            'last_fix_time': '2026-11-11T09:00:00Z', 'ended_at': None,
            'summary': {
                'jtwc': {'analysis_time': '2026-11-11T06:00:00Z', 'active': True, 'lat': 29.1, 'lon': 150.2,
                         'category': 'TYPHOON', 'max_wind': {'kt': 65, 'ms': None, 'averaging_min': 1},
                         'pressure_hpa': 983},
                'jma': {'analysis_time': '2026-11-11T09:00:00Z', 'active': True, 'lat': 29.2, 'lon': 151.0,
                        'category': 'STS', 'max_wind': {'kt': 60, 'ms': 30, 'averaging_min': 10},
                        'pressure_hpa': 985},
                'cwa': {'analysis_time': '2026-11-11T06:00:00Z', 'active': True, 'lat': 28.9, 'lon': 149.9,
                        'category': None, 'max_wind': {'kt': None, 'ms': 30, 'averaging_min': 10},
                        'pressure_hpa': 975}}}]})


ANALYSIS_PATH = 'tropical/official/storms/2026-jma-tc2638/analysis.json'
FORECAST_PATH = 'tropical/official/storms/2026-jma-tc2638/forecast.json'


def _sectors(*values):
    return [{'dir': direction, 'radius': value} for direction, value in zip(('NE', 'SE', 'SW', 'NW'), values)]


def valid_analysis():
    """design.md 1.4 with all three agencies, values from the 2026-11-11 samples."""
    return deepcopy({
        'schema_version': 1, 'cyclone_id': '2026-jma-tc2638', 'fetched_at': '2026-11-11T10:33:07Z',
        'agencies': {
            'jtwc': {
                'product_url': 'https://www.metoc.navy.mil/jtwc/products/wp3126.tcw',
                'graphic_url': 'https://www.metoc.navy.mil/jtwc/products/wp3126.gif',
                'issued_at': '2026-11-11T09:00:00Z', 'bulletin': '021', 'final': False,
                'fix': {'analysis_time': '2026-11-11T06:00:00Z', 'lat': 29.1, 'lon': 150.2, 'category': 'TYPHOON',
                        'max_wind': {'kt': 65, 'ms': None, 'averaging_min': 1}, 'gust': {'kt': 80, 'ms': None},
                        'pressure_hpa': 983,
                        'movement': {'direction_deg': 70, 'direction_text': None, 'speed_kt': 33, 'speed_kmh': None},
                        'radii': [{'threshold': {'value': 34, 'unit': 'kt'}, 'unit': 'nm',
                                   'sectors': _sectors(100, 105, 95, None)}]},
                'past_track_origin': 'accumulated',
                'past_track': [{'analysis_time': '2026-11-11T00:00:00Z', 'lat': 27.9, 'lon': 147.0,
                                'category': 'TYPHOON', 'max_wind': {'kt': 70, 'ms': None, 'averaging_min': 1},
                                'pressure_hpa': None}]},
            'jma': {
                'product_url': JMA_BULLETIN.format('20261111094118'), 'graphic_url': None,
                'issued_at': '2026-11-11T09:45:00Z', 'bulletin': '52', 'final': False,
                'fix': {'analysis_time': '2026-11-11T09:00:00Z', 'lat': 29.2, 'lon': 151.0, 'category': 'STS',
                        'max_wind': {'kt': 60, 'ms': 30, 'averaging_min': 10}, 'gust': {'kt': 85, 'ms': 45},
                        'pressure_hpa': 985,
                        'movement': {'direction_deg': None, 'direction_text': 'ENE', 'speed_kt': 27, 'speed_kmh': 50},
                        'radii': [{'threshold': {'value': 50, 'unit': 'kt'}, 'unit': 'nm',
                                   'sectors': [{'dir': 'ALL', 'radius': 60}]}]},
                'past_track_origin': 'accumulated', 'past_track': []},
            'cwa': {
                'product_url': 'https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005', 'graphic_url': None,
                'issued_at': '2026-11-11T06:00:00Z', 'bulletin': None, 'final': False,
                'fix': {'analysis_time': '2026-11-11T06:00:00Z', 'lat': 28.9, 'lon': 149.9, 'category': None,
                        'max_wind': {'kt': None, 'ms': 30, 'averaging_min': 10}, 'gust': {'kt': None, 'ms': 38},
                        'pressure_hpa': 975,
                        'movement': {'direction_deg': None, 'direction_text': 'ENE', 'speed_kt': None, 'speed_kmh': 54},
                        'radii': [{'threshold': {'value': 15, 'unit': 'm/s'}, 'unit': 'km',
                                   'sectors': _sectors(180, 120, 120, 160)}]},
                'past_track_origin': 'source',
                'past_track': [{'analysis_time': '2026-11-11T00:00:00Z', 'lat': 27.5, 'lon': 147.6, 'category': None,
                                'max_wind': {'kt': None, 'ms': 30, 'averaging_min': 10}, 'pressure_hpa': 975}]}}})


def valid_forecast():
    """design.md 1.5 with all three agencies; crosses a day and 180 degrees."""
    def point(tau, valid, lat, lon, **extra):
        base = {'tau_h': tau, 'valid_time': valid, 'lat': lat, 'lon': lon, 'category': None, 'max_wind': None,
                'gust': None, 'pressure_hpa': None, 'probability_circle': None, 'radii': [], 'note': None}
        base.update(extra)
        return base
    return deepcopy({
        'schema_version': 1, 'cyclone_id': '2026-jma-tc2638', 'fetched_at': '2026-11-11T10:33:07Z',
        'agencies': {
            'jtwc': {'product_url': 'https://www.metoc.navy.mil/jtwc/products/wp3126.tcw',
                     'issued_at': '2026-11-11T09:00:00Z', 'bulletin': '021', 'init_time': '2026-11-11T06:00:00Z',
                     'points': [point(12, '2026-11-11T18:00:00Z', 31.2, 157.0,
                                      max_wind={'kt': 55, 'ms': None, 'averaging_min': 1}, note='DISSIPATING'),
                                point(36, '2026-11-12T18:00:00Z', 10.2, -180.0, note='POST_TROPICAL')]},
            'jma': {'product_url': JMA_BULLETIN.format('20261111094118'), 'issued_at': '2026-11-11T09:45:00Z',
                    'bulletin': '52', 'init_time': '2026-11-11T09:00:00Z',
                    'points': [point(24, '2026-11-12T09:00:00Z', 37.6, 168.7, category='LOW', pressure_hpa=992,
                                     max_wind={'kt': 55, 'ms': 30, 'averaging_min': 10}, gust={'kt': 80, 'ms': 40},
                                     probability_circle={'radius': 120, 'unit': 'km', 'probability_pct': 70})]},
            'cwa': {'product_url': 'https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005',
                    'issued_at': '2026-11-11T06:00:00Z', 'bulletin': None, 'init_time': '2026-11-11T06:00:00Z',
                    'points': [point(6, '2026-11-11T12:00:00Z', 30.2, 153.7,
                                     probability_circle={'radius': 40, 'unit': 'km', 'probability_pct': 70},
                                     radii=[{'threshold': {'value': 15, 'unit': 'm/s'}, 'unit': 'km',
                                             'sectors': [{'dir': 'ALL', 'radius': 150}]}],
                                     note='EXTRATROPICAL')]}}})


def no_storm_index(moment=NOW):
    source = {'state': 'ok', 'error_code': None, 'last_ok_at': minute(moment), 'active_count': 0}
    return {'schema_version': 1, 'basin': 'WP', 'status': 'OK_NO_STORMS', 'fetched_at': stamp(moment),
            'sources': {'cwa': dict(source, required=True), 'jma': dict(source, required=True),
                        'jtwc': dict(source, required=False)}, 'storms': []}


# --- Synthetic "no system" responses -------------------------------------------------
# No real no-system response had been captured when these tests were written;
# every body below is hand-made after the real formats (see fixtures/tropical/README.md).
SYNTHETIC_CWA_NO_STORM = (b'{"success":"true","result":{"resource_id":"W-C0034-005","fields":[]},'
                          b'"records":{"dataid":"C0034-005","note":"synthetic",'
                          b'"TropicalCyclones":{"TropicalCyclone":[]}}}')
SYNTHETIC_JMA_FEED_NO_VPTW = ('<?xml version="1.0" encoding="utf-8"?>\n'
                              '<feed xmlns="http://www.w3.org/2005/Atom" lang="ja"><title>synthetic</title>'
                              '<entry><title>x</title><id>https://www.data.jma.go.jp/developer/xml/data/'
                              '20261111091352_0_VPWW53_240000.xml</id><updated>2026-11-11T00:15:59Z</updated>'
                              '<link type="application/xml" href="https://www.data.jma.go.jp/developer/xml/data/'
                              '20261111091352_0_VPWW53_240000.xml"/></entry></feed>').encode()
SYNTHETIC_JMA_TARGET_EMPTY = b'[]'


def synthetic_rss(west, central='<ul><li><font color=\'red\'>No Current Tropical Cyclone Warnings.</font></li></ul>'):
    def item(guid, body):
        return (f'<item><title>t</title><description><![CDATA[{body}]]></description>'
                f'<guid>{guid}</guid></item>')
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>synthetic</title>'
            + item('NWPAC-NIO-WARNINGS', west) + item('EPAC-CPAC-WARNINGS', central)
            + '</channel></rss>').encode()


SYNTHETIC_JTWC_RSS_NO_STORM = synthetic_rss(
    "<ul><li><font color='red'>No Current Tropical Cyclone Warnings.</font></li></ul>")


def rss_system(label, number, name, warning, product, *, final=False):
    mark = ' <font color=red><b>Final Warning</b></font>' if final else ''
    return (f"<p><b>{label} {number} ({name}) Warning #{warning}{mark}</b><br><b>Issued at 11/0900Z<b><ul>"
            f"<li><a href='{JTWC_PRODUCT.format(product + 'web.txt')}'>TC Warning Text</a></li>"
            f"<li><a href='{JTWC_PRODUCT.format(product + '.tcw')}'>JMV 3.0 Data</a></li></ul>")


def synthetic_tcw(*, when, number, name, lat='291N', lon='1502E', wind='065', label='TYPHOON'):
    return (f'WTPN51 PGTW 110900\nWARNING    ATCG MIL {number} NWP 261111073859\n'
            f'{when:%Y%m%d%H} {number} {name:<10} 021  01 070 33 SATL 030\n'
            f'T000 {lat} {lon} {wind} R034 100 NE QD 105 SE QD 095 SW QD 070 NW QD \n'
            f'T012 312N 1570E 055 \nSUBJ:  {label} {number} ({name}) WARNING NR 021\n').encode('latin-1')


def no_storm_routes():
    return {CWA_URL: SYNTHETIC_CWA_NO_STORM, JMA_FEED: SYNTHETIC_JMA_FEED_NO_VPTW,
            JMA_TARGET: SYNTHETIC_JMA_TARGET_EMPTY, JTWC_RSS: SYNTHETIC_JTWC_RSS_NO_STORM}


def cempaka_routes():
    """Real samples of 2026-11-11: one active system seen by all three agencies, plus PENA east of 180."""
    routes = {CWA_URL: fixture('cwa_datastore_cempaka.json'),
              JMA_FEED: fixture('jma_extra_feed_cropped.xml'),
              JMA_TARGET: fixture('jma_targetTc_active.json'),
              JTWC_RSS: fixture('jtwc_rss_active.xml'),
              JTWC_PRODUCT.format('wp3126.tcw'): fixture('jtwc_wp3126_warning21.tcw'),
              # The saved PENA product is a day later (11-12 06Z); at this instant it would be
              # an analysis from the future, so the same position is rebuilt for 11-11 06Z.
              JTWC_PRODUCT.format('cp0426.tcw'): synthetic_tcw(
                  when=datetime(2026, 11, 11, 6, tzinfo=UTC), number='04C', name='PENA', lat='098N',
                  lon='1713W', wind='035', label='TROPICAL STORM')}
    bulletin = fixture('jma_vptw60_tc2638_serial52.xml')
    for code in ('20261111094118', '20261111064050'):
        routes[JMA_BULLETIN.format(code)] = bulletin
    return routes


def hours(value):
    return timedelta(hours=value)
