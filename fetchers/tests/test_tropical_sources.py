"""CWA, JMA and JTWC tropical sources with real cropped samples and a strict fake transport.

"synthetic" in a test name means the response body was hand-made: no real
no-system response had been captured when the test was written.
"""
from datetime import datetime, timedelta, timezone
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import unittest

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tropical_testing as tt
from tropical_testing import (CWA_URL, JMA_BULLETIN, JMA_FEED, JMA_LONG, JMA_TARGET, JTWC_PRODUCT, JTWC_RSS,
                              NOW, SECRET, FakeResponse, FakeTransport, fixture, hours, quiet_policy)

from src.http_client import http_scope
from src.services import tropical_cwa, tropical_jma, tropical_jtwc
from src.services.tropical_common import USER_AGENT, SourceFailure, TropicalClient, normalize_lon

UTC = timezone.utc
WP3126 = JTWC_PRODUCT.format('wp3126.tcw')
CP0426 = JTWC_PRODUCT.format('cp0426.tcw')


def setUpModule():
    tt.block_network()


def tearDownModule():
    tt.unblock_network()


def client_for(routes):
    transport = FakeTransport(routes)
    return TropicalClient(transport, wait=lambda seconds: None, clock=lambda: 0.0), transport


def run(fetch, routes, *arguments):
    client, transport = client_for(routes)
    with http_scope(quiet_policy()):
        return fetch(client, *arguments), transport


FAILURES = {
    '403': (403, 'http_error'), '404': (404, 'http_error'), '500 after retries': (500, 'network_error'),
    '503 after retries': (503, 'network_error'), '429 after retries': (429, 'network_error'),
    'timeout': (requests.Timeout('boom'), 'network_error'),
    'connection error': (requests.ConnectionError('boom'), 'network_error'),
    'other transport error': (requests.RequestException('boom'), 'network_error'),
}


class ClientTests(unittest.TestCase):
    def test_fixed_user_agent_and_no_other_headers(self):
        client, transport = client_for({JTWC_RSS: b'x'})
        with http_scope(quiet_policy()):
            client.get(JTWC_RSS)
        self.assertEqual(transport.calls[0][1]['headers'], {'User-Agent': USER_AGENT})
        self.assertEqual(USER_AGENT, 'weather-integration-static/1.0 (tropical cyclone data fetcher)')

    def test_blocked_request_is_not_retried_with_another_identity(self):
        client, transport = client_for({JTWC_RSS: 403})
        with http_scope(quiet_policy()), self.assertRaises(SourceFailure):
            client.get(JTWC_RSS)
        self.assertEqual(len(transport.calls), 1)

    def test_one_second_spacing_per_source_uses_injected_wait(self):
        waits, clock = [], [100.0]
        transport = FakeTransport({JTWC_RSS: b'x', WP3126: b'y', JMA_FEED: b'z'})
        client = TropicalClient(transport, wait=waits.append, clock=lambda: clock[0])
        with http_scope(quiet_policy()):
            client.get(JTWC_RSS)
            clock[0] += 0.25
            client.get(WP3126)      # same source 0.25 s later: wait the rest
            client.get(JMA_FEED)    # other source: no wait
            clock[0] += 5
            client.get(JTWC_RSS)    # long enough ago: no wait
        self.assertEqual(waits, [0.75])

    def test_unregistered_url_fails_the_fake_transport(self):
        client, _ = client_for({})
        with http_scope(quiet_policy()), self.assertRaises(tt.UnexpectedRequest):
            client.get('https://www.metoc.navy.mil/jtwc/jtwc.html')

    def test_forgotten_transport_cannot_reach_the_network(self):
        with http_scope(quiet_policy()), self.assertRaises(tt.UnexpectedRequest):
            TropicalClient(None, wait=lambda seconds: None).get(JTWC_RSS)

    def test_longitude_180_is_minus_180(self):
        self.assertEqual(normalize_lon(180.0), -180.0)
        self.assertEqual(normalize_lon(-180.0), -180.0)
        self.assertEqual(normalize_lon(179.9), 179.9)
        self.assertEqual(normalize_lon(-171.3), -171.3)


class CwaTests(unittest.TestCase):
    def test_real_sample_with_one_system(self):
        result, transport = run(tropical_cwa.fetch_cwa, {CWA_URL: fixture('cwa_datastore_cempaka.json')}, SECRET)
        self.assertEqual((result.state, result.error_code, len(result.records)), ('ok', None, 1))
        record = result.records[0]
        self.assertEqual(record['analysis_time'], datetime(2026, 11, 11, 6, tzinfo=UTC))  # 14:00 +08:00
        self.assertEqual((record['lat'], record['lon'], record['pressure_hpa']), (28.9, 149.9, 975))
        self.assertEqual(record['max_wind'], {'kt': None, 'ms': 30, 'averaging_min': 10})
        self.assertEqual((record['name'], record['name_zh'], record['season']), ('CEMPAKA', '查帕卡', 2026))
        self.assertEqual(record['ids'], {'cwa_ty': '31', 'cwa_td': '35'})
        self.assertIsNone(record['category'])
        self.assertFalse(record['ended'])
        self.assertEqual(result.listed, {(2026, 'td', '35'), (2026, 'ty', '31')})
        # The key goes in params only, never in the URL string.
        url, options = transport.calls[0]
        self.assertEqual(url, CWA_URL)
        self.assertEqual(options['params'], {'Authorization': SECRET, 'format': 'JSON'})

    def test_synthetic_empty_array_is_ok_without_systems(self):
        result, _ = run(tropical_cwa.fetch_cwa, {CWA_URL: tt.SYNTHETIC_CWA_NO_STORM}, SECRET)
        self.assertEqual((result.state, result.records, result.listed), ('ok', [], set()))

    def test_any_other_shape_is_a_parse_error_never_no_storm(self):
        shapes = [b'', b'not json', b'[]', b'{}', b'{"success":"true","records":{}}',
                  b'{"success":"true","records":{"TropicalCyclones":{}}}',
                  b'{"success":"true","records":{"TropicalCyclones":{"TropicalCyclone":{}}}}',
                  b'{"success":"true","records":{"TropicalCyclones":{"TropicalCyclone":null}}}',
                  b'{"success":"false","records":{"TropicalCyclones":{"TropicalCyclone":[]}}}',
                  b'<html>maintenance</html>']
        for body in shapes:
            with self.subTest(body=body[:40]):
                result, _ = run(tropical_cwa.fetch_cwa, {CWA_URL: body}, SECRET)
                self.assertEqual((result.state, result.error_code, result.records), ('failed', 'parse_error', []))

    def test_http_and_transport_failures(self):
        for label, (route, code) in FAILURES.items():
            with self.subTest(label):
                result, _ = run(tropical_cwa.fetch_cwa, {CWA_URL: route}, SECRET)
                self.assertEqual((result.state, result.error_code), ('failed', code))

    def test_missing_key_fails_without_any_request(self):
        for key in (None, '', '   '):
            result, transport = run(tropical_cwa.fetch_cwa, {}, key)
            self.assertEqual((result.state, result.error_code, transport.calls), ('failed', 'source_error', []))

    def test_bad_entry_fails_the_source_but_keeps_good_entries(self):
        payload = json.loads(fixture('cwa_datastore_cempaka.json'))
        cyclones = payload['records']['TropicalCyclones']['TropicalCyclone']
        cyclones.append({'Year': '2026', 'CwaTdNo': '36'})  # no analysis
        result, _ = run(tropical_cwa.fetch_cwa, {CWA_URL: json.dumps(payload).encode()}, SECRET)
        self.assertEqual((result.state, result.error_code, len(result.records)), ('failed', 'parse_error', 1))

    def test_unnamed_synthetic_depression_has_no_name(self):
        payload = json.loads(fixture('cwa_datastore_cempaka.json'))
        cyclone = payload['records']['TropicalCyclones']['TropicalCyclone'][0]
        for raw in (None, '', '  ', '熱帶性低氣壓', 'TD35'):
            with self.subTest(raw=raw):
                cyclone['TyphoonName'] = raw
                cyclone.pop('CwaTyNo', None)
                result = tropical_cwa.parse_cwa(json.dumps(payload).encode())
                self.assertEqual(result.state, 'ok')
                self.assertIsNone(result.records[0]['name'])
                self.assertEqual(result.records[0]['key'], ('td', '35'))

    def test_key_never_appears_in_results_or_output(self):
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured):
            texts = []
            for route in (403, 500, requests.ConnectionError(f'https://x/?Authorization={SECRET}'),
                          requests.Timeout(SECRET), b'garbage ' + SECRET.encode(),
                          fixture('cwa_datastore_cempaka.json')):
                result, _ = run(tropical_cwa.fetch_cwa, {CWA_URL: route}, SECRET)
                texts.append(repr((result.state, result.error_code, result.records, result.listed)))
        self.assertNotIn(SECRET, ''.join(texts) + captured.getvalue())

    def test_client_failure_carries_no_cause_or_secret(self):
        client, _ = client_for({CWA_URL: requests.ConnectionError(f'{CWA_URL}?Authorization={SECRET}')})
        with http_scope(quiet_policy()):
            try:
                client.get(CWA_URL, params={'Authorization': SECRET})
            except SourceFailure as failure:
                self.assertEqual(str(failure), 'network_error')
                self.assertIsNone(failure.__cause__)
                self.assertTrue(failure.__suppress_context__)
            else:
                self.fail('expected failure')


class JtwcTests(unittest.TestCase):
    def test_real_active_rss_and_products(self):
        routes = {JTWC_RSS: fixture('jtwc_rss_active.xml'), WP3126: fixture('jtwc_wp3126_warning21.tcw'),
                  CP0426: fixture('jtwc_cp0426_warning23.tcw')}
        result, transport = run(tropical_jtwc.fetch_jtwc, routes)
        self.assertEqual(result.state, 'ok')
        # Only the RSS and the .tcw it links: no HTML, no text bulletin, no graphic.
        self.assertEqual(transport.urls, [JTWC_RSS, WP3126, CP0426])
        west, central = result.records
        self.assertEqual((west['key'], west['name'], west['season'], west['origin_basin']), ('31W', 'CEMPAKA', 2026, 'WP'))
        self.assertEqual(west['analysis_time'], datetime(2026, 11, 11, 6, tzinfo=UTC))
        self.assertEqual((west['lat'], west['lon'], west['category'], west['pressure_hpa']), (29.1, 150.2, 'TYPHOON', 983))
        self.assertEqual(west['max_wind'], {'kt': 65, 'ms': None, 'averaging_min': 1})
        self.assertTrue(west['in_scope'])
        # PENA at 171.3W: a central Pacific number outside the basin.
        self.assertEqual((central['key'], central['origin_basin'], central['lon'], central['in_scope']),
                         ('04C', 'CP', -171.3, False))
        self.assertEqual(result.listed, {'31W', '04C'})

    def test_real_final_warning_is_listed_but_ended(self):
        routes = {JTWC_RSS: fixture('jtwc_rss_final.xml'), WP3126: fixture('jtwc_wp3126_final.tcw'),
                  CP0426: fixture('jtwc_cp0426_warning23.tcw')}
        result, _ = run(tropical_jtwc.fetch_jtwc, routes)
        self.assertEqual(result.state, 'ok')
        self.assertTrue(result.records[0]['ended'])
        self.assertFalse(result.records[1]['ended'])
        self.assertEqual(result.records[0]['analysis_time'], datetime(2026, 11, 11, 12, tzinfo=UTC))

    def test_tcw_is_decoded_as_latin1(self):
        body = fixture('jtwc_wp3126_warning21.tcw') + b'\nREMARK \xe9\xff\x80\n'
        record = tropical_jtwc.parse_tcw(body, WP3126, final=False)
        self.assertEqual(record['key'], '31W')

    def test_synthetic_no_warnings_text_is_ok_without_systems(self):
        result, transport = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: tt.SYNTHETIC_JTWC_RSS_NO_STORM})
        self.assertEqual((result.state, result.records, result.listed), ('ok', [], set()))
        self.assertEqual(transport.urls, [JTWC_RSS])

    def test_unknown_western_text_is_a_parse_error(self):
        for west in ('', '<p>Feed under maintenance</p>', '<ul><li>NONE</li></ul>'):
            with self.subTest(west=west):
                result, _ = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: tt.synthetic_rss(west)})
                self.assertEqual((result.state, result.error_code), ('failed', 'parse_error'))

    def test_missing_western_item_dtd_and_broken_xml_are_parse_errors(self):
        bodies = [b'<rss><channel></channel></rss>', b'<rss', b'',
                  b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x "y">]><rss/>']
        for body in bodies:
            with self.subTest(body=body[:30]):
                result, _ = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: body})
                self.assertEqual((result.state, result.error_code), ('failed', 'parse_error'))

    def test_rss_failures(self):
        for label, (route, code) in FAILURES.items():
            with self.subTest(label):
                result, _ = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: route})
                self.assertEqual((result.state, result.error_code, result.records), ('failed', code, []))

    def test_one_failed_product_fails_the_source_but_keeps_other_systems(self):
        # Missing JTWC products answer 403, which is a failure, not "no cyclone".
        routes = {JTWC_RSS: fixture('jtwc_rss_active.xml'), WP3126: fixture('jtwc_wp3126_warning21.tcw'), CP0426: 403}
        result, _ = run(tropical_jtwc.fetch_jtwc, routes)
        self.assertEqual((result.state, result.error_code), ('failed', 'http_error'))
        self.assertEqual([record['key'] for record in result.records], ['31W'])
        self.assertEqual(result.listed, {'31W', '04C'})

    def test_malformed_or_mismatched_product_fails_the_source(self):
        other = tt.synthetic_tcw(when=NOW, number='32W', name='OTHER')
        for body in (b'', b'<html>blocked</html>', other):
            with self.subTest(body=body[:20]):
                routes = {JTWC_RSS: fixture('jtwc_rss_active.xml'), WP3126: body, CP0426: fixture('jtwc_cp0426_warning23.tcw')}
                result, _ = run(tropical_jtwc.fetch_jtwc, routes)
                self.assertEqual((result.state, result.error_code), ('failed', 'parse_error'))
                self.assertEqual([record['key'] for record in result.records], ['04C'])

    def test_only_links_matching_the_fixed_pattern_are_requested(self):
        west = ("<p><b>Typhoon 31W (Cempaka) Warning #21 </b><ul>"
                "<li><a href='https://evil.example/jtwc/products/wp3126.tcw'>JMV 3.0 Data</a></li>"
                "<li><a href='http://www.metoc.navy.mil/jtwc/products/wp3126.tcw'>JMV</a></li></ul>")
        result, transport = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: tt.synthetic_rss(west)})
        self.assertEqual((result.state, result.error_code), ('failed', 'parse_error'))
        self.assertEqual(transport.urls, [JTWC_RSS])

    def test_north_indian_ocean_systems_are_excluded_by_suffix(self):
        west = (tt.rss_system('Tropical Cyclone', '05B', 'Mala', 3, 'io0526')
                + tt.rss_system('Tropical Cyclone', '02A', 'Asna', 1, 'io0226')
                + tt.rss_system('Typhoon', '31W', 'Cempaka', 21, 'wp3126'))
        result, transport = run(tropical_jtwc.fetch_jtwc,
                                {JTWC_RSS: tt.synthetic_rss(west), WP3126: fixture('jtwc_wp3126_warning21.tcw')})
        self.assertEqual(result.state, 'ok')
        self.assertEqual(transport.urls, [JTWC_RSS, WP3126])
        self.assertEqual(result.listed, {'31W'})

    def test_only_indian_ocean_systems_listed_is_ok_without_systems(self):
        west = tt.rss_system('Tropical Cyclone', '05B', 'Mala', 3, 'io0526')
        result, transport = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: tt.synthetic_rss(west)})
        self.assertEqual((result.state, result.records, transport.urls), ('ok', [], [JTWC_RSS]))

    def test_central_pacific_system_is_in_scope_only_after_crossing(self):
        link = JTWC_PRODUCT.format('cp0426.tcw')
        cases = [('1787W', False), ('1800E', False), ('1800W', False), ('1799E', True), ('0999E', False)]
        for lon, inside in cases:
            with self.subTest(lon=lon):
                body = tt.synthetic_tcw(when=NOW, number='04C', name='PENA', lat='102N', lon=lon, wind='030',
                                        label='TROPICAL DEPRESSION')
                record = tropical_jtwc.parse_tcw(body, link, final=False)
                self.assertEqual(record['in_scope'], inside)
                self.assertEqual(record['origin_basin'], 'CP')
        # Exactly 180 degrees is written -180.0 whichever hemisphere letter the source used.
        for lon in ('1800E', '1800W'):
            body = tt.synthetic_tcw(when=NOW, number='04C', name='PENA', lon=lon)
            self.assertEqual(tropical_jtwc.parse_tcw(body, link, final=False)['lon'], -180.0)

    def test_real_forecast_point_at_180_exists_in_sample(self):
        self.assertIn(b'T036 102N 1800E', fixture('jtwc_cp0426_warning23.tcw'))

    def test_season_comes_from_the_product_name_across_new_year(self):
        body = tt.synthetic_tcw(when=datetime(2027, 1, 1, 0, tzinfo=UTC), number='31W', name='CEMPAKA')
        self.assertEqual(tropical_jtwc.parse_tcw(body, WP3126, final=False)['season'], 2026)

    def test_number_word_placeholder_is_not_a_name(self):
        self.assertIsNone(tropical_jtwc.storm_name('32W', 'THIRTYTWO'))
        self.assertIsNone(tropical_jtwc.storm_name('04C', 'FOUR'))
        self.assertEqual(tropical_jtwc.storm_name('31W', 'CEMPAKA'), 'CEMPAKA')
        self.assertEqual(tropical_jtwc.storm_name('31W', 'THIRTYTWO'), 'THIRTYTWO')


def feed(*entries, extra=('2026-11-11T00:15:59Z',)):
    """Synthetic Atom feed: entries are (14-digit code, updated) for VPTW60 bulletins."""
    def entry(link, updated):
        return (f'<entry><title>x</title><id>{link}</id><updated>{updated}</updated>'
                f'<link type="application/xml" href="{link}"/></entry>')
    body = ''.join(entry(JMA_BULLETIN.format(code), updated) for code, updated in entries)
    body += ''.join(entry('https://www.data.jma.go.jp/developer/xml/data/20261111001600_0_VPWW61_280000.xml', stamp)
                    for stamp in extra)
    return f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode()


def bulletin(*, event='TC2638', analysis='2026-11-11T18:00:00+09:00', report='2026-11-11T18:45:00+09:00',
             grade='台風(STS)', name='CEMPAKA', status='通常', info='発表', coordinate='+29.2+151.0/'):
    """Synthetic VPTW60 derived from the real sample by text replacement."""
    text = fixture('jma_vptw60_tc2638_serial52.xml').decode('utf-8')
    text = text.replace('<EventID>TC2638</EventID>', f'<EventID>{event}</EventID>')
    text = text.replace('<ReportDateTime>2026-11-11T18:45:00+09:00</ReportDateTime>', f'<ReportDateTime>{report}</ReportDateTime>')
    text = text.replace('<DateTime type="実況">2026-11-11T18:00:00+09:00</DateTime>', f'<DateTime type="実況">{analysis}</DateTime>')
    text = text.replace('台風(STS)</jmx_eb:TyphoonClass>', f'{grade}</jmx_eb:TyphoonClass>', 1)
    text = text.replace('<Name>CEMPAKA</Name>', f'<Name>{name}</Name>')
    text = text.replace('<Status>通常</Status>', f'<Status>{status}</Status>')
    text = text.replace('<InfoType>発表</InfoType>', f'<InfoType>{info}</InfoType>')
    text = text.replace('type="中心位置（度）">+29.2+151.0/</jmx_eb:Coordinate>', f'type="中心位置（度）">{coordinate}</jmx_eb:Coordinate>', 1)
    return text.encode('utf-8')


def known(analysis, *, event='TC2638', active=True):
    return [{'event': event, 'analysis_time': analysis, 'active': active}]


B0941, B0640 = JMA_BULLETIN.format('20261111094118'), JMA_BULLETIN.format('20261111064050')
T09 = datetime(2026, 11, 11, 9, tzinfo=UTC)


class JmaParsingTests(unittest.TestCase):
    def test_real_active_bulletin(self):
        record = tropical_jma.parse_vptw60(fixture('jma_vptw60_tc2638_serial52.xml'))
        self.assertEqual(record['analysis_time'], T09)  # 18:00 JST
        self.assertEqual(record['report_time'], datetime(2026, 11, 11, 9, 45, tzinfo=UTC))
        self.assertEqual((record['key'], record['season'], record['name'], record['category']), ('TC2638', 2026, 'CEMPAKA', 'STS'))
        self.assertEqual(record['ids'], {'jma_tc': 'TC2638', 'jma_number': '2632'})
        self.assertEqual((record['lat'], record['lon'], record['pressure_hpa']), (29.2, 151.0, 985))
        self.assertEqual(record['max_wind'], {'kt': 60, 'ms': 30, 'averaging_min': 10})
        self.assertFalse(record['ended'])

    def test_real_final_bulletin_ends_by_class_only(self):
        record = tropical_jma.parse_vptw60(fixture('jma_vptw60_tc2638_final.xml'))
        self.assertTrue(record['ended'])
        self.assertEqual((record['category'], record['max_wind'], record['pressure_hpa']), ('LOW', None, 990))

    def test_remark_alone_does_not_end_a_system(self):
        text = fixture('jma_vptw60_tc2638_serial52.xml').decode().replace('<Remark/>', '<Remark>台風消滅（熱帯低気圧化）</Remark>')
        text = text.replace('台風(STS)</jmx_eb:TyphoonClass>', '熱帯低気圧(TD)</jmx_eb:TyphoonClass>', 1)
        record = tropical_jma.parse_vptw60(text.encode())
        self.assertEqual((record['category'], record['ended']), ('TD', False))

    def test_unknown_class_stays_active(self):
        for grade in ('未知の種類(XYZ)', '種類なし'):
            record = tropical_jma.parse_vptw60(bulletin(grade=grade))
            self.assertFalse(record['ended'])

    def test_unnamed_depression_and_degree_minute_fallback(self):
        record = tropical_jma.parse_vptw60(bulletin(name='', grade='熱帯低気圧(TD)', coordinate=''))
        self.assertIsNone(record['name'])
        self.assertEqual((record['lat'], record['lon']), (29.2, 151.0))  # +2910+15100/

    def test_training_and_cancelled_bulletins_are_ignored(self):
        self.assertIsNone(tropical_jma.parse_vptw60(bulletin(status='訓練')))
        self.assertIsNone(tropical_jma.parse_vptw60(bulletin(info='取消')))

    def test_year_boundary_time_and_season(self):
        record = tropical_jma.parse_vptw60(bulletin(event='TC2640', analysis='2027-01-01T03:00:00+09:00',
                                                    report='2027-01-01T03:45:00+09:00'))
        self.assertEqual(record['analysis_time'], datetime(2026, 12, 31, 18, tzinfo=UTC))
        self.assertEqual(record['season'], 2026)

    def test_feed_keeps_only_vptw60_links_of_the_documented_pattern(self):
        entries, oldest = tropical_jma.parse_feed(fixture('jma_extra_feed_cropped.xml'))
        self.assertEqual(len(entries), 4)
        self.assertTrue(all('_VPTW60_' in url for url, _ in entries))
        self.assertEqual(oldest, datetime(2026, 11, 11, 0, 15, 59, tzinfo=UTC))
        long_feed = feed(('20261105124055', '2026-11-05T12:40:54Z')).replace(b'VPTW60', b'VPTW61')
        self.assertEqual(tropical_jma.parse_feed(long_feed)[0], [])

    def test_dtd_is_refused(self):
        with self.assertRaises(SourceFailure):
            tropical_jma.parse_feed(b'<!DOCTYPE feed [<!ENTITY a "b">]><feed/>')
        with self.assertRaises(SourceFailure):
            tropical_jma.parse_vptw60(b'<!DOCTYPE Report><Report/>')


class JmaFlowTests(unittest.TestCase):
    """One test per row of the JMA table in design.md 3.3, plus the long-feed triggers of 5.3."""

    def fetch(self, routes, held=(), now=NOW):
        return run(tropical_jma.fetch_jma, routes, list(held), now)

    def test_row1_feed_failure_fails_the_source(self):
        for label, (route, code) in FAILURES.items():
            with self.subTest(label):
                result, transport = self.fetch({JMA_FEED: route})
                self.assertEqual((result.state, result.error_code, result.records), ('failed', code, []))
                self.assertEqual(set(transport.urls), {JMA_FEED})
        for body in (b'', b'<feed', b'<html/>'):
            result, _ = self.fetch({JMA_FEED: body})
            self.assertEqual((result.state, result.error_code), ('failed', 'parse_error'))

    def test_row2_target_ok_and_every_listed_system_held(self):
        result, transport = self.fetch(tt.cempaka_routes())
        self.assertEqual((result.state, len(result.records)), ('ok', 1))
        # 4-hour window at 10:30Z: the 09:41 and 06:40 bulletins, not 03:40 or 00:40. No long feed.
        self.assertEqual(transport.urls, [JMA_FEED, B0941, B0640, JMA_TARGET])

    def test_row2_synthetic_no_system_is_ok_with_two_requests(self):
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: tt.SYNTHETIC_JMA_TARGET_EMPTY}
        result, transport = self.fetch(routes)
        self.assertEqual((result.state, result.records, transport.urls), ('ok', [], [JMA_FEED, JMA_TARGET]))

    def test_row2_real_low_only_target_needs_no_bulletin(self):
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: fixture('jma_targetTc_low.json')}
        result, transport = self.fetch(routes, now=datetime(2026, 11, 12, 11, tzinfo=UTC))
        self.assertEqual((result.state, result.records, transport.urls), ('ok', [], [JMA_FEED, JMA_TARGET]))

    def test_row2_long_feed_supplies_the_missing_bulletin(self):
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: fixture('jma_targetTc_active.json'),
                  JMA_LONG: feed(('20261111094118', '2026-11-11T09:41:17Z'), ('20261111034034', '2026-11-11T03:40:34Z')),
                  B0941: fixture('jma_vptw60_tc2638_serial52.xml')}
        result, transport = self.fetch(routes)
        self.assertEqual((result.state, len(result.records)), ('ok', 1))
        # Only bulletins of the last 6 hours are taken from the long feed.
        self.assertEqual(transport.urls, [JMA_FEED, JMA_TARGET, JMA_LONG, B0941])

    def test_row3_listed_system_without_bulletin_is_a_validation_failure(self):
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: fixture('jma_targetTc_active.json'),
                  JMA_LONG: feed()}
        result, _ = self.fetch(routes)
        self.assertEqual((result.state, result.error_code, result.records), ('failed', 'validation_error', []))

    def test_row3_long_feed_failure_keeps_the_source_failed(self):
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: fixture('jma_targetTc_active.json'), JMA_LONG: 404}
        result, _ = self.fetch(routes)
        self.assertEqual((result.state, result.error_code), ('failed', 'http_error'))

    def test_row3_held_window_boundary(self):
        # Held analysis exactly 6 h old counts; one second older does not.
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: fixture('jma_targetTc_active.json'), JMA_LONG: feed()}
        result, transport = self.fetch(routes, known(NOW - hours(6), active=False))
        self.assertEqual((result.state, transport.urls), ('ok', [JMA_FEED, JMA_TARGET]))
        result, transport = self.fetch(routes, known(NOW - hours(6) - timedelta(seconds=1), active=False))
        self.assertEqual((result.state, result.error_code), ('failed', 'validation_error'))
        self.assertIn(JMA_LONG, transport.urls)

    def test_row4_bad_target_with_enough_coverage_relies_on_the_feed(self):
        # Oldest feed entry 00:15:59Z; held analysis 09:00Z: 00:15:59 <= 12:30 -> covered.
        for target in (500, 404, b'{"unexpected": true}', b'[{"tropicalCyclone": 1}]', b'not json'):
            with self.subTest(target=target):
                routes = dict(tt.cempaka_routes(), **{JMA_TARGET: target})
                result, transport = self.fetch(routes, known(T09))
                self.assertEqual(result.state, 'ok')
                self.assertNotIn(JMA_LONG, transport.urls)

    def test_row4_coverage_boundary(self):
        # Covered when the oldest entry is not later than held analysis + 3.5 h.
        held = datetime(2026, 11, 11, 3, tzinfo=UTC)
        for oldest, covered in (('2026-11-11T06:30:00Z', True), ('2026-11-11T06:30:01Z', False)):
            with self.subTest(oldest=oldest):
                routes = {JMA_FEED: feed(extra=(oldest,)), JMA_TARGET: 404, JMA_LONG: feed()}
                result, transport = self.fetch(routes, known(held, active=False), now=datetime(2026, 11, 11, 7, tzinfo=UTC))
                self.assertEqual(result.state, 'ok')
                self.assertEqual(JMA_LONG in transport.urls, not covered)

    def test_row5_bad_target_without_coverage_fetches_the_long_feed(self):
        # Nothing held at all counts as insufficient coverage.
        for target in (404, 403, b'{"unexpected": true}'):
            with self.subTest(target=target):
                routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: target, JMA_LONG: feed()}
                result, transport = self.fetch(routes)
                self.assertEqual((result.state, result.records), ('ok', []))
                self.assertEqual(transport.urls[-1], JMA_LONG)

    def test_row6_repeated_5xx_on_target_blocks_jma_for_this_run(self):
        # Existing http_client behaviour: three failed attempts block the whole
        # source (targetTc and the feeds are both "jma") for the rest of the scope,
        # so the long feed cannot be fetched and JMA is failed, never "no systems".
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: 500, JMA_LONG: feed()}
        result, transport = self.fetch(routes)
        self.assertEqual((result.state, result.error_code), ('failed', 'timeout'))
        self.assertNotIn(JMA_LONG, transport.urls)

    def test_row6_bad_target_and_failed_long_feed_fails_the_source(self):
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: b'{}', JMA_LONG: 503}
        result, _ = self.fetch(routes)
        self.assertEqual((result.state, result.error_code), ('failed', 'network_error'))

    def test_stale_active_system_triggers_the_long_feed_for_a_missed_final_bulletin(self):
        final_url = JMA_BULLETIN.format('20261111124152')
        now = datetime(2026, 11, 11, 18, tzinfo=UTC)  # task was down; final bulletin left the short feed
        routes = {JMA_FEED: feed(extra=('2026-11-11T17:00:00Z',)), JMA_TARGET: fixture('jma_targetTc_low.json'),
                  JMA_LONG: feed(('20261111124152', '2026-11-11T12:41:52Z')),
                  final_url: fixture('jma_vptw60_tc2638_final.xml')}
        result, transport = self.fetch(routes, known(T09), now=now)
        self.assertEqual(result.state, 'ok')
        self.assertTrue(result.records[0]['ended'])
        self.assertEqual(transport.urls, [JMA_FEED, JMA_TARGET, JMA_LONG, final_url])
        # Boundary: an analysis exactly 4 h old does not trigger it.
        routes = {JMA_FEED: feed(extra=('2026-11-11T12:00:00Z',)), JMA_TARGET: fixture('jma_targetTc_active.json')}
        result, transport = self.fetch(routes, known(T09), now=T09 + hours(4))
        self.assertEqual((result.state, transport.urls), ('ok', [JMA_FEED, JMA_TARGET]))

    def test_latest_report_wins_per_system_and_two_systems_are_kept(self):
        other = JMA_BULLETIN.format('20261111094200')
        routes = {JMA_FEED: feed(('20261111094118', '2026-11-11T09:41:17Z'), ('20261111064050', '2026-11-11T06:40:48Z'),
                                 ('20261111094200', '2026-11-11T09:42:00Z')),
                  JMA_TARGET: b'[{"tropicalCyclone":"TC2638","category":"STS"},{"tropicalCyclone":"TC2639","category":"TD"}]',
                  B0941: bulletin(), B0640: bulletin(analysis='2026-11-11T15:00:00+09:00', report='2026-11-11T15:45:00+09:00'),
                  other: bulletin(event='TC2639', name='', grade='熱帯低気圧(TD)', coordinate='+12.0+135.0/')}
        result, _ = self.fetch(routes)
        self.assertEqual(result.state, 'ok')
        by_event = {record['key']: record for record in result.records}
        self.assertEqual(set(by_event), {'TC2638', 'TC2639'})
        self.assertEqual(by_event['TC2638']['analysis_time'], T09)
        self.assertIsNone(by_event['TC2639']['name'])

    def test_failed_bulletin_fails_the_source_but_keeps_the_others(self):
        routes = dict(tt.cempaka_routes(), **{B0640: 404})
        result, _ = self.fetch(routes)
        self.assertEqual((result.state, result.error_code, len(result.records)), ('failed', 'http_error', 1))
        routes = dict(tt.cempaka_routes(), **{B0640: b'<Report>'})
        result, _ = self.fetch(routes)
        self.assertEqual((result.state, result.error_code, len(result.records)), ('failed', 'parse_error', 1))

    def test_at_most_twelve_bulletins_per_run(self):
        codes = [f'202611110{minute:02d}000' for minute in range(40, 60)]
        entries = [(code, '2026-11-11T09:%s:00Z' % code[9:11]) for code in codes]
        routes = {JMA_FEED: feed(*entries), JMA_TARGET: tt.SYNTHETIC_JMA_TARGET_EMPTY}
        routes.update({JMA_BULLETIN.format(code): bulletin() for code in codes})
        _, transport = self.fetch(routes)
        self.assertEqual(sum('_VPTW60_' in url for url in transport.urls), 12)

    def test_window_is_relative_to_now_across_taiwan_midnight_and_new_year(self):
        # 15:59:59Z..16:00:01Z is Taiwan midnight; 2026-12-31T23:30Z crosses the UTC year.
        for now, code, updated in (
                (datetime(2026, 11, 11, 16, 0, 1, tzinfo=UTC), '20261111130000', '2026-11-11T13:00:00Z'),
                (datetime(2027, 1, 1, 1, 0, tzinfo=UTC), '20261231233000', '2026-12-31T23:30:00Z')):
            with self.subTest(now=now):
                url = JMA_BULLETIN.format(code)
                routes = {JMA_FEED: feed((code, updated)), JMA_TARGET: tt.SYNTHETIC_JMA_TARGET_EMPTY,
                          url: bulletin(analysis='2026-12-31T23:00:00+00:00' if now.year == 2027 else '2026-11-11T21:00:00+09:00')}
                result, transport = self.fetch(routes, now=now)
                self.assertEqual(result.state, 'ok')
                self.assertIn(url, transport.urls)


class ReviewFindingTests(unittest.TestCase):
    """Cases raised by the independent review of S4."""

    def test_impossible_coordinates_fail_the_source_instead_of_being_folded_or_ignored(self):
        for raw in ('500', '-200', 'nan', 'inf', '180.1', ''):
            with self.subTest(source='cwa', raw=raw):
                payload = json.loads(fixture('cwa_datastore_cempaka.json'))
                payload['records']['TropicalCyclones']['TropicalCyclone'][0]['AnalysisData']['Fix'][-1]['CoordinateLongitude'] = raw
                result = tropical_cwa.parse_cwa(json.dumps(payload).encode())
                self.assertEqual((result.state, result.error_code, result.records), ('failed', 'parse_error', []))
        for raw in ('nan', '95', '-91'):
            with self.subTest(source='cwa lat', raw=raw):
                payload = json.loads(fixture('cwa_datastore_cempaka.json'))
                payload['records']['TropicalCyclones']['TropicalCyclone'][0]['AnalysisData']['Fix'][-1]['CoordinateLatitude'] = raw
                self.assertEqual(tropical_cwa.parse_cwa(json.dumps(payload).encode()).state, 'failed')
        for lat, lon in (('291N', '9999E'), ('291N', '1801E'), ('999N', '1502E')):
            with self.subTest(source='jtwc', lat=lat, lon=lon):
                routes = {JTWC_RSS: tt.synthetic_rss(tt.rss_system('Typhoon', '31W', 'Cempaka', 21, 'wp3126')),
                          WP3126: tt.synthetic_tcw(when=NOW, number='31W', name='CEMPAKA', lat=lat, lon=lon)}
                result, _ = run(tropical_jtwc.fetch_jtwc, routes)
                self.assertEqual((result.state, result.error_code, result.records), ('failed', 'parse_error', []))
        for coordinate in ('+29.2+500.0/', '+95.0+151.0/'):
            with self.subTest(source='jma', coordinate=coordinate), self.assertRaises(ValueError):
                tropical_jma.parse_vptw60(bulletin(coordinate=coordinate).replace('+2910+15100/'.encode(), b'bad'))
        with self.assertRaises(ValueError):
            normalize_lon(float('nan'))

    def test_missing_central_pacific_item_fails_jtwc(self):
        body = tt.SYNTHETIC_JTWC_RSS_NO_STORM.replace(b'EPAC-CPAC-WARNINGS', b'SOMETHING-ELSE')
        result, _ = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: body})
        self.assertEqual((result.state, result.error_code), ('failed', 'parse_error'))

    def test_repeated_product_link_in_one_system_is_one_link(self):
        west = ("<p><b>Typhoon 31W (Cempaka) Warning #21 </b><ul><li><a href='" + WP3126 + "'>" + WP3126 + "</a></li></ul>")
        result, transport = run(tropical_jtwc.fetch_jtwc,
                                {JTWC_RSS: tt.synthetic_rss(west), WP3126: fixture('jtwc_wp3126_warning21.tcw')})
        self.assertEqual((result.state, transport.urls), ('ok', [JTWC_RSS, WP3126]))

    def test_coverage_ignores_bulletins_downloaded_in_this_run(self):
        # Nothing held before, targetTc unusable, short feed with one bulletin: the long feed is still needed.
        routes = {JMA_FEED: feed(('20261111094118', '2026-11-11T09:41:17Z'), extra=('2026-11-11T09:40:00Z',)),
                  B0941: fixture('jma_vptw60_tc2638_serial52.xml'), JMA_TARGET: 404, JMA_LONG: feed()}
        result, transport = run(tropical_jma.fetch_jma, routes, [], NOW)
        self.assertEqual((result.state, len(result.records)), ('ok', 1))
        self.assertEqual(transport.urls, [JMA_FEED, B0941, JMA_TARGET, JMA_LONG])


REAL_NO_SYSTEM_TIME = datetime(2026, 11, 15, 17, 44, tzinfo=UTC)


class RealNoSystemTests(unittest.TestCase):
    """Real responses of 2026-11-15 17:43Z, when no agency had a western North Pacific system."""

    def test_real_jtwc_rss_without_wp_systems(self):
        result, transport = run(tropical_jtwc.fetch_jtwc, {JTWC_RSS: fixture('jtwc_rss_no_wp_systems_20261115.xml')})
        self.assertEqual((result.state, result.records, result.listed), ('ok', [], set()))
        # The southern hemisphere item lists 04P at that time; it is not ours and nothing is fetched for it.
        self.assertIn(b'04P (Four)', fixture('jtwc_rss_no_wp_systems_20261115.xml'))
        self.assertEqual(transport.urls, [JTWC_RSS])

    def test_real_jma_empty_target_and_feed_without_vptw60(self):
        self.assertEqual(fixture('jma_targetTc_empty_20261115.json'), b'[]')
        routes = {JMA_FEED: fixture('jma_extra_feed_no_vptw_cropped_20261115.xml'),
                  JMA_TARGET: fixture('jma_targetTc_empty_20261115.json')}
        result, transport = run(tropical_jma.fetch_jma, routes, [], REAL_NO_SYSTEM_TIME)
        self.assertEqual((result.state, result.records, transport.urls), ('ok', [], [JMA_FEED, JMA_TARGET]))

    def test_real_cwa_still_serves_the_ended_system_four_days_later(self):
        # On 2026-11-15 the CWA response was byte-identical to the 2026-11-11 CEMPAKA sample:
        # the array is not empty when there is no cyclone, so only the analysis time can tell.
        result, _ = run(tropical_cwa.fetch_cwa, {CWA_URL: fixture('cwa_datastore_cempaka.json')}, SECRET)
        self.assertEqual((result.state, len(result.records)), ('ok', 1))
        self.assertEqual(result.records[0]['analysis_time'], datetime(2026, 11, 11, 6, tzinfo=UTC))


# --- S6: per-storm file content --------------------------------------------------------

def assert_blocks_valid(test, record):
    """The parsed blocks must pass the public contract as they are (design.md 1.4, 1.5)."""
    from src.tropical_contract import validate_storm_file
    agency = record['agency']
    analysis = dict(record['analysis'], past_track_origin='source' if agency == 'cwa' else 'accumulated',
                    past_track=record['source_track'] if agency == 'cwa' else [])
    for kind, block in (('analysis', analysis), ('forecast', record['forecast'])):
        agencies = dict.fromkeys(('jtwc', 'jma', 'cwa'))
        agencies[agency] = block
        validate_storm_file(f'tropical/official/storms/2026-jma-tc2638/{kind}.json',
                            {'schema_version': 1, 'cyclone_id': '2026-jma-tc2638',
                             'fetched_at': '2026-11-11T10:30:00Z', 'agencies': agencies})


def tcw_text(name):
    return fixture(name).decode('latin-1')


class JtwcDetailTests(unittest.TestCase):
    def test_real_warning_fix_radii_gust_movement_and_forecast(self):
        record = tropical_jtwc.parse_tcw(fixture('jtwc_wp3126_warning21.tcw'), WP3126, final=False,
                                         graphic=JTWC_PRODUCT.format('wp3126.gif'))
        analysis, forecast = record['analysis'], record['forecast']
        self.assertEqual((analysis['issued_at'], analysis['bulletin'], analysis['final']),
                         ('2026-11-11T09:00:00Z', '021', False))
        self.assertEqual(analysis['graphic_url'], JTWC_PRODUCT.format('wp3126.gif'))
        fix = analysis['fix']
        self.assertEqual((fix['gust'], fix['pressure_hpa']), ({'kt': 80, 'ms': None}, 983))
        self.assertEqual(fix['movement'], {'direction_deg': 70, 'direction_text': None, 'speed_kt': 33, 'speed_kmh': None})
        self.assertEqual([item['threshold']['value'] for item in fix['radii']], [64, 50, 34])
        self.assertEqual(fix['radii'][2]['sectors'][3], {'dir': 'NW', 'radius': 70})
        self.assertEqual(forecast['init_time'], '2026-11-11T06:00:00Z')
        self.assertEqual([(p['tau_h'], p['valid_time'], p['note']) for p in forecast['points']],
                         [(12, '2026-11-11T18:00:00Z', 'DISSIPATING'), (24, '2026-11-12T06:00:00Z', 'DISSIPATED')])
        self.assertEqual(forecast['points'][0]['max_wind'], {'kt': 55, 'ms': None, 'averaging_min': 1})
        self.assertTrue(all(p['gust'] is None and p['probability_circle'] is None for p in forecast['points']))
        assert_blocks_valid(self, record)

    def test_real_final_and_central_pacific_samples(self):
        final = tropical_jtwc.parse_tcw(fixture('jtwc_wp3126_final.tcw'), WP3126, final=True)
        self.assertEqual((final['analysis']['issued_at'], final['analysis']['bulletin'], final['analysis']['final']),
                         ('2026-11-11T15:00:00Z', '022', True))
        # ATCF 0 means "no radius of this strength" -> null (design.md 1.2).
        self.assertEqual(final['analysis']['fix']['radii'][0]['sectors'][0], {'dir': 'NE', 'radius': None})
        assert_blocks_valid(self, final)
        pena = tropical_jtwc.parse_tcw(fixture('jtwc_cp0426_warning23.tcw'), CP0426, final=False)
        points = pena['forecast']['points']
        self.assertEqual(points[-1]['tau_h'], 36)
        self.assertEqual(points[-1]['lon'], -180.0)  # T036 1800E
        self.assertEqual([p['note'] for p in points], [None, 'POST_TROPICAL', 'POST_TROPICAL'])
        self.assertEqual(pena['analysis']['issued_at'], '2026-11-12T10:00:00Z')
        assert_blocks_valid(self, pena)

    def test_issue_time_month_from_second_line_across_month_and_year(self):
        cases = (('WTPN51 PGTW 010300', '261130235959', '2026-12-01T03:00:00Z'),
                 ('WTPN51 PGTW 302100', '261201000500', '2026-11-30T21:00:00Z'),
                 ('WTPN51 PGTW 312100', '270101000100', '2026-12-31T21:00:00Z'),
                 ('WTPN51 PGTW 010300', '261231235959', '2027-01-01T03:00:00Z'),
                 ('WTPN51 PGTW 111500', '261111141257', '2026-11-11T15:00:00Z'))
        analysis = datetime(2026, 11, 11, 12, tzinfo=UTC)
        for first, second, expected in cases:
            with self.subTest(first=first, second=second):
                text = f'{first}    \nWARNING    ATCG MIL 31W NWP {second}\n2026111112 31W ...'
                self.assertEqual(tt.stamp(tropical_jtwc.issued_time(text, None, analysis)), expected)

    def test_issue_time_falls_back_to_rss_text_then_fails(self):
        text = 'garbled first line\n2026111106 31W CEMPAKA 021'
        analysis = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.assertEqual(tt.stamp(tropical_jtwc.issued_time(text, ('11', '09', '00'), analysis)), '2026-11-11T09:00:00Z')
        # Across a year: analysis 12-31 18Z, RSS "Issued at 01/0300Z".
        self.assertEqual(tt.stamp(tropical_jtwc.issued_time(text, ('01', '03', '00'), datetime(2026, 12, 31, 18, tzinfo=UTC))),
                         '2027-01-01T03:00:00Z')
        with self.assertRaises(ValueError):
            tropical_jtwc.issued_time(text, None, analysis)
        # Without any issue time the product is a parse failure of the source (design.md #19).
        body = tcw_text('jtwc_wp3126_warning21.tcw').split('\n', 2)[2].encode('latin-1')
        with self.assertRaises(ValueError):
            tropical_jtwc.parse_tcw(body, WP3126, final=False)

    def test_fetch_takes_graphic_and_issue_time_from_the_rss_block(self):
        result, _ = run(tropical_jtwc.fetch_jtwc, tt.cempaka_routes())
        record = next(item for item in result.records if item['key'] == '31W')
        self.assertEqual(record['analysis']['graphic_url'], JTWC_PRODUCT.format('wp3126.gif'))
        self.assertEqual(record['analysis']['product_url'], WP3126)

    def test_unusable_forecast_or_radii_never_fail_the_product(self):
        # S6a review finding A: optional content must not cost the index its record.
        base = tcw_text('jtwc_wp3126_warning21.tcw')
        for label, body, check in (
                ('point beyond 180', base.replace('T024 336N 1642E 045', 'T024 336N 1900E 045'),
                 lambda r: self.assertIsNone(r['forecast'])),
                ('tau above 240', base.replace('T024 336N', 'T264 336N'), lambda r: self.assertIsNone(r['forecast'])),
                ('duplicate radii threshold', base.replace('R064 020 NE', 'R050 020 NE', 1),
                 lambda r: self.assertEqual(r['analysis']['fix']['radii'], [])),
                ('threshold 000', base.replace('R064 020 NE', 'R000 020 NE', 1),
                 lambda r: self.assertEqual(r['analysis']['fix']['radii'], []))):
            with self.subTest(label):
                record = tropical_jtwc.parse_tcw(body.encode('latin-1'), WP3126, final=False)
                self.assertEqual((record['analysis_time'], record['lat']), (datetime(2026, 11, 11, 6, tzinfo=UTC), 29.1))
                check(record)
                if record['forecast'] is not None:
                    assert_blocks_valid(self, record)


def jma_text(name='jma_vptw60_tc2638_serial52.xml'):
    return fixture(name).decode('utf-8')


class JmaDetailTests(unittest.TestCase):
    def test_real_bulletin_fix_radii_and_forecast(self):
        record = tropical_jma.parse_vptw60(fixture('jma_vptw60_tc2638_serial52.xml'), B0941)
        analysis, forecast = record['analysis'], record['forecast']
        self.assertEqual(record['feed_time'], datetime(2026, 11, 11, 9, 41, 18, tzinfo=UTC))
        self.assertEqual((analysis['issued_at'], analysis['bulletin'], analysis['product_url']),
                         ('2026-11-11T09:45:00Z', '52', B0941))
        fix = analysis['fix']
        self.assertEqual(fix['gust'], {'kt': 85, 'ms': 45})
        self.assertEqual(fix['movement'], {'direction_deg': None, 'direction_text': 'ENE', 'speed_kt': 27, 'speed_kmh': 50})
        # Thresholds are the ones the bulletin states (design.md 11b #3).
        self.assertEqual(fix['radii'], [
            {'threshold': {'value': 50, 'unit': 'kt'}, 'unit': 'nm', 'sectors': [{'dir': 'ALL', 'radius': 60}]},
            {'threshold': {'value': 30, 'unit': 'kt'}, 'unit': 'nm', 'sectors': [{'dir': 'ALL', 'radius': 150}]}])
        self.assertEqual([(p['tau_h'], p['valid_time']) for p in forecast['points']],
                         [(12, '2026-11-11T21:00:00Z'), (24, '2026-11-12T09:00:00Z')])
        self.assertEqual(forecast['points'][1]['probability_circle'], {'radius': 120, 'unit': 'km', 'probability_pct': 70})
        # 暴風警戒域 is not a wind radius (design.md 11b #7).
        self.assertEqual(forecast['points'][1]['radii'], [])
        assert_blocks_valid(self, record)

    def test_real_final_bulletin_has_no_forecast_points(self):
        record = tropical_jma.parse_vptw60(fixture('jma_vptw60_tc2638_final.xml'), JMA_BULLETIN.format('20261111124152'))
        self.assertEqual((record['analysis']['final'], record['forecast']['points']), (True, []))
        self.assertEqual(record['analysis']['bulletin'], '53')
        assert_blocks_valid(self, record)

    def test_threshold_follows_the_bulletin_and_unknown_axes_are_left_out(self):
        text = jma_text().replace('description="風速５０ノット以上" condition="以上" unit="ノット" type="風速">50<',
                                  'description="x" condition="以上" unit="ノット" type="風速">48<', 1)
        text = text.replace('description="全域" condition="全域" unit="８方位漢字" type="方向"/>',
                            'unit="８方位漢字" type="方向">北北東</jmx_eb:Direction>', 1)
        record = tropical_jma.parse_vptw60(text.encode('utf-8'), B0941)
        # The first wind area lost its readable axis; the second is untouched.
        self.assertEqual([item['threshold']['value'] for item in record['analysis']['fix']['radii']], [30])
        text = jma_text().replace('type="風速">50<', 'type="風速">48<', 1)
        record = tropical_jma.parse_vptw60(text.encode('utf-8'), B0941)
        self.assertEqual([item['threshold']['value'] for item in record['analysis']['fix']['radii']], [48, 30])

    def test_unknown_direction_word_is_null(self):
        # No sample of the stationary or variable wording (design.md 11b #11).
        text = jma_text().replace('type="移動方向">東北東<', 'type="移動方向">ほとんど停滞<', 1)
        movement = tropical_jma.parse_vptw60(text.encode('utf-8'), B0941)['analysis']['fix']['movement']
        self.assertEqual(movement, {'direction_deg': None, 'direction_text': None, 'speed_kt': 27, 'speed_kmh': 50})

    def test_unusable_forecast_parts_keep_the_analysis(self):
        # S6a review finding A.
        base = jma_text()
        cases = (
            ('no probability circle', base.replace('<ProbabilityCircle type="予報円">', '<Other type="予報円">', 1)
             .replace('</ProbabilityCircle>', '</Other>', 1)),
            ('blank probability radius', base.replace('type="７０パーセント確率半径">120<', 'type="７０パーセント確率半径"><', 1)),
            ('odd base point', base.replace('type="中心位置（度）">+37.6+168.7/<', 'type="中心位置（度）">north<')
             .replace('type="中心位置（度分）">+3735+16840/<', 'type="中心位置（度分）">north<')),
            ('repeated forecast time', base.replace('予報　２４時間後', '予報　１２時間後')))
        for label, text in cases:
            with self.subTest(label):
                self.assertNotEqual(text, base)
                record = tropical_jma.parse_vptw60(text.encode('utf-8'), B0941)
                self.assertIsNone(record['forecast'])
                self.assertEqual((record['analysis_time'], record['lat']), (T09, 29.2))
                self.assertEqual(record['analysis']['fix']['radii'][0]['threshold']['value'], 50)

    def test_maximum_wind_keeps_the_s4_range(self):
        # S6a review finding B: 210 kt must be refused when parsed, as in S4, not reach the index.
        text = jma_text().replace('unit="ノット" type="最大風速">60<', 'unit="ノット" type="最大風速">210<', 1)
        self.assertNotEqual(text, jma_text())
        with self.assertRaises(ValueError):
            tropical_jma.parse_vptw60(text.encode('utf-8'), B0941)
        gust = jma_text().replace('unit="ノット" type="最大瞬間風速">85<', 'unit="ノット" type="最大瞬間風速">230<', 1)
        self.assertEqual(tropical_jma.parse_vptw60(gust.encode('utf-8'), B0941)['analysis']['fix']['gust']['kt'], 230)

    def test_feed_time_is_read_from_the_url_only(self):
        self.assertEqual(tropical_jma.feed_time_of(B0941), datetime(2026, 11, 11, 9, 41, 18, tzinfo=UTC))
        for url in (None, 'https://example.com/x.xml', JMA_BULLETIN.format('20261399000000')):
            self.assertIsNone(tropical_jma.feed_time_of(url))


def saved(url, *, analysis, issued, active=True, event='TC2638'):
    """A held JMA system whose analysis.json keeps a bulletin (the 5.3 flow)."""
    return [{'event': event, 'analysis_time': analysis, 'active': active, 'product_url': url,
             'feed_time': tropical_jma.feed_time_of(url), 'issued_at': issued}]


class JmaSavedBulletinTests(unittest.TestCase):
    """design.md 5.3 restored in S6 (11a #3): dedupe by saved URL, coverage by feed time."""

    def fetch(self, routes, held=(), now=NOW):
        return run(tropical_jma.fetch_jma, routes, list(held), now)

    def test_saved_bulletin_is_not_downloaded_again_and_older_reports_are_dropped(self):
        held = saved(B0941, analysis=T09, issued=datetime(2026, 11, 11, 9, 45, tzinfo=UTC))
        result, transport = self.fetch(tt.cempaka_routes(), held)
        # B0640 is re-read (accepted cost, 5.3) but is not newer than the saved report.
        self.assertEqual(transport.urls, [JMA_FEED, B0640, JMA_TARGET])
        self.assertEqual((result.state, result.records), ('ok', []))

    def test_newer_report_replaces_the_saved_one(self):
        held = saved(B0640, analysis=T09 - hours(3), issued=datetime(2026, 11, 11, 6, 45, tzinfo=UTC))
        result, transport = self.fetch(tt.cempaka_routes(), held)
        self.assertEqual(transport.urls, [JMA_FEED, B0941, JMA_TARGET])
        self.assertEqual([record['analysis']['product_url'] for record in result.records], [B0941])

    def test_two_systems_in_one_batch_are_both_taken(self):
        # The reason for URL dedupe (5.3): a global "newer than the newest" filter would skip the second.
        other = JMA_BULLETIN.format('20261111094120')
        routes = {JMA_FEED: feed(('20261111094118', '2026-11-11T09:41:17Z'), ('20261111094120', '2026-11-11T09:41:20Z')),
                  B0941: fixture('jma_vptw60_tc2638_serial52.xml'),
                  other: bulletin(event='TC2639', name='DOKSURI', coordinate='+15.0+135.0/',
                                  report='2026-11-11T18:40:00+09:00'),
                  JMA_TARGET: b'[{"tropicalCyclone":"TC2638","category":"STS"},{"tropicalCyclone":"TC2639","category":"TS"}]'}
        held = saved(other, analysis=T09, issued=datetime(2026, 11, 11, 9, 40, tzinfo=UTC), event='TC2639')
        held += saved(JMA_BULLETIN.format('20261111064050'), analysis=T09 - hours(3),
                      issued=datetime(2026, 11, 11, 6, 45, tzinfo=UTC))
        result, transport = self.fetch(routes, held)
        self.assertEqual(transport.urls, [JMA_FEED, B0941, JMA_TARGET])
        self.assertEqual(sorted(record['key'] for record in result.records), ['TC2638'])
        self.assertEqual(result.state, 'ok')

    def test_coverage_uses_the_saved_feed_time(self):
        # Analysis 01:00Z but bulletin in the feed at 03:00Z: the boundary is 03:00 + 3.5 h = 06:30.
        url = JMA_BULLETIN.format('20261111030000')
        for oldest, covered in (('2026-11-11T06:30:00Z', True), ('2026-11-11T06:30:01Z', False)):
            with self.subTest(oldest=oldest):
                routes = {JMA_FEED: feed(extra=(oldest,)), JMA_TARGET: 404, JMA_LONG: feed()}
                held = saved(url, analysis=datetime(2026, 11, 11, 1, tzinfo=UTC),
                             issued=datetime(2026, 11, 11, 3, 5, tzinfo=UTC), active=False)
                result, transport = self.fetch(routes, held, now=datetime(2026, 11, 11, 7, tzinfo=UTC))
                self.assertEqual(result.state, 'ok')
                self.assertEqual(JMA_LONG in transport.urls, not covered)

    def test_held_window_uses_the_saved_feed_time(self):
        routes = {JMA_FEED: tt.SYNTHETIC_JMA_FEED_NO_VPTW, JMA_TARGET: fixture('jma_targetTc_active.json'), JMA_LONG: feed()}
        for feed_at, ok in ((NOW - hours(6), True), (NOW - hours(6) - timedelta(seconds=1), False)):
            with self.subTest(feed_at=feed_at):
                url = JMA_BULLETIN.format(f'{feed_at:%Y%m%d%H%M%S}')
                held = saved(url, analysis=NOW - hours(7), issued=feed_at, active=False)
                result, transport = self.fetch(routes, held)
                self.assertEqual(result.state == 'ok', ok)
                self.assertEqual(JMA_LONG in transport.urls, not ok)

    def test_missed_final_trigger_uses_the_saved_feed_time(self):
        # Analysis 4.5 h old but in the feed 3 h 50 min ago: not stale yet, no long feed.
        now = T09 + hours(4) + timedelta(minutes=30)
        url = JMA_BULLETIN.format('20261111094000')
        routes = {JMA_FEED: feed(extra=('2026-11-11T12:00:00Z',)), JMA_TARGET: fixture('jma_targetTc_active.json')}
        result, transport = self.fetch(routes, saved(url, analysis=T09, issued=T09 + hours(1)), now=now)
        self.assertEqual((result.state, transport.urls), ('ok', [JMA_FEED, JMA_TARGET]))

    def test_without_a_saved_url_the_s4_interim_still_applies(self):
        # Same as the S4 row 4 boundary: the held analysis time stands in for the feed time.
        held = known(datetime(2026, 11, 11, 3, tzinfo=UTC), active=False)
        routes = {JMA_FEED: feed(extra=('2026-11-11T06:30:01Z',)), JMA_TARGET: 404, JMA_LONG: feed()}
        _, transport = self.fetch(routes, held, now=datetime(2026, 11, 11, 7, tzinfo=UTC))
        self.assertIn(JMA_LONG, transport.urls)

    def test_other_bulletins_of_the_system_become_extra_track_points(self):
        routes = dict(tt.cempaka_routes())
        routes[B0640] = bulletin(analysis='2026-11-11T15:00:00+09:00', report='2026-11-11T15:45:00+09:00',
                                 coordinate='+28.5+148.6/')
        result, _ = self.fetch(routes)
        self.assertEqual([record['analysis_time'] for record in result.records], [T09])
        self.assertEqual([(p['analysis_time'], p['lat'], p['lon']) for p in result.records[0]['extra_points']],
                         [('2026-11-11T06:00:00Z', 28.5, 148.6)])


def cwa_payload():
    return json.loads(fixture('cwa_datastore_cempaka.json'))


def cwa_entry(payload):
    return payload['records']['TropicalCyclones']['TropicalCyclone'][0]


class CwaDetailTests(unittest.TestCase):
    def test_real_sample_track_radii_and_forecast(self):
        record = tropical_cwa.parse_cwa(fixture('cwa_datastore_cempaka.json')).records[0]
        analysis, forecast = record['analysis'], record['forecast']
        self.assertEqual(analysis['product_url'], 'https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005')
        # No separate issue time in the datastore response (11a): the analysis time stands in.
        self.assertEqual((analysis['issued_at'], analysis['bulletin'], analysis['final']),
                         ('2026-11-11T06:00:00Z', None, False))
        track = record['source_track']
        self.assertEqual(len(track), 21)
        self.assertEqual(track[0]['analysis_time'], '2026-11-06T00:00:00Z')  # 08:00 +08:00
        self.assertEqual(track, sorted(track, key=lambda point: point['analysis_time']))
        fix = analysis['fix']
        self.assertEqual(fix['movement'], {'direction_deg': None, 'direction_text': 'ENE', 'speed_kt': None, 'speed_kmh': 54})
        self.assertEqual([item['threshold'] for item in fix['radii']],
                         [{'value': 25, 'unit': 'm/s'}, {'value': 15, 'unit': 'm/s'}])
        self.assertEqual([item['dir'] for item in fix['radii'][1]['sectors']], ['NE', 'SE', 'SW', 'NW'])
        self.assertEqual(forecast['init_time'], '2026-11-11T06:00:00Z')
        self.assertEqual([(p['tau_h'], p['note']) for p in forecast['points']], [(6, None), (12, 'EXTRATROPICAL')])
        self.assertEqual(forecast['points'][0]['radii'],
                         [{'threshold': {'value': 15, 'unit': 'm/s'}, 'unit': 'km', 'sectors': [{'dir': 'ALL', 'radius': 150}]}])
        self.assertEqual(forecast['points'][0]['probability_circle'], {'radius': 40, 'unit': 'km', 'probability_pct': 70})
        assert_blocks_valid(self, record)

    def test_track_is_capped_at_160_newest_points(self):
        payload = cwa_payload()
        base = cwa_entry(payload)['AnalysisData']['Fix'][0]
        start = datetime(2026, 10, 1, tzinfo=UTC)
        cwa_entry(payload)['AnalysisData']['Fix'] = [
            dict(base, DateTime=(start + hours(3 * n)).isoformat()) for n in range(200)]
        record = tropical_cwa.parse_cwa(json.dumps(payload).encode()).records[0]
        self.assertEqual(len(record['source_track']), 160)
        self.assertEqual(record['source_track'][-1]['analysis_time'], tt.stamp(start + hours(3 * 198)))

    def test_unusable_forecast_drops_only_the_forecast(self):
        # S6a review finding A: the record (and so the index) must stay as in S4.
        for label, change in (
                ('two init times', lambda fixes: fixes[1].update(InitialTime='2026-11-11T20:00:00+08:00')),
                ('longitude 200', lambda fixes: fixes[0].update(CoordinateLongitude='200.0')),
                ('tau 0', lambda fixes: fixes[0].update(ForecastHour='0')),
                ('blank tau', lambda fixes: fixes[0].update(ForecastHour='')),
                ('missing latitude', lambda fixes: fixes[0].pop('CoordinateLatitude')),
                ('gust 300', lambda fixes: fixes[0].update(MaxGustSpeed='300')),
                ('25 points', lambda fixes: fixes.extend(dict(fixes[0], ForecastHour=str(n)) for n in range(20, 43)))):
            with self.subTest(label):
                payload = cwa_payload()
                change(cwa_entry(payload)['ForecastData']['Fix'])
                result = tropical_cwa.parse_cwa(json.dumps(payload).encode())
                self.assertEqual((result.state, len(result.records)), ('ok', 1))
                self.assertIsNone(result.records[0]['forecast'])
                self.assertEqual(result.records[0]['analysis']['fix']['lat'], 28.9)

    def test_odd_radii_and_past_points_are_left_out(self):
        def fix(payload):
            return cwa_entry(payload)['AnalysisData']['Fix']
        for label, change, radii, track in (
                ('quadrant N', lambda p: fix(p)[-1]['Circle15ms']['QuadrantRadii']['Radius'][0].update(dir='N'), [25], 21),
                ('quadrants as dict', lambda p: fix(p)[-1]['Circle25ms']['QuadrantRadii'].update(Radius={'value': 1}),
                 [15], 21),
                ('circle as string', lambda p: fix(p)[-1].update(Circle15ms='150'), [25], 21),
                ('old point without latitude', lambda p: fix(p)[0].pop('CoordinateLatitude'), [25, 15], 20),
                ('old point at latitude 99', lambda p: fix(p)[1].update(CoordinateLatitude='99'), [25, 15], 20),
                ('repeated old time', lambda p: fix(p)[1].update(DateTime=fix(p)[0]['DateTime']), [25, 15], 20)):
            with self.subTest(label):
                payload = cwa_payload()
                change(payload)
                result = tropical_cwa.parse_cwa(json.dumps(payload).encode())
                self.assertEqual((result.state, len(result.records)), ('ok', 1))
                record = result.records[0]
                self.assertEqual([item['threshold']['value'] for item in record['analysis']['fix']['radii']], radii)
                self.assertEqual(len(record['source_track']), track)
                assert_blocks_valid(self, record)


    def test_missing_forecast_gives_no_forecast_block(self):
        payload = cwa_payload()
        cwa_entry(payload).pop('ForecastData')
        record = tropical_cwa.parse_cwa(json.dumps(payload).encode()).records[0]
        self.assertIsNone(record['forecast'])


if __name__ == '__main__':
    unittest.main()
