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


if __name__ == '__main__':
    unittest.main()
