"""Offline failure-path contracts. No requests may escape the fake transport."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.history_reconciliation import history_scope
from src.services.cwa_service import CWAService
from src.services.kma_service import KMAService
from src.http_client import HttpPolicy, _policy

NOW = datetime.fromisoformat('2026-10-30T18:35:00+08:00')
POLICY = {'interval_seconds': 3600, 'max_rechecks': 3,
          'max_slots_per_run': 12, 'current_day_only': True}
# Reduced from the saved official 2026-10-30 JS structure; not executable JS.
TEMP = """var TemperatureImg = {'Day0':{
 'size0':{0:{"img":'/Data/temperature/2026-10-30_1800.GTP8.jpg'}},
 'size1':{0:{"img":'/Data/temperature/2026-10-30_1800.GTP8w.jpg'},
          1:{"img":'/Data/temperature/2026-10-30_1700.GTP8w.jpg'}}}};"""
RAIN = """var RainDay={'Tab0':{'Day0':{
 0:{'img':'2026-10-30_1830.QZJ8','text':'2026/10/30 18:30'},
 1:{'img':'2026-10-30_1800.QZJ8','text':'2026/10/30 18:00'}},
 'Day1':{0:{'img':'2026-10-30_0000.QZJ8'}}},
 'Tab1':{'Day0':{0:{'img':'2099-10-30_1830.QZJ8'}}}};"""
RADAR = "0:{\"img\":'CV1_3600_202610301830.png', 'text':'2026/10/30 18:30'}"


def reply(code=200, text=None, body=b'image', mime='image/png'):
    r = requests.Response()
    r.status_code = code
    r.headers['Content-Type'] = 'text/javascript' if text is not None else mime
    r._content = text.encode() if text is not None else body
    r._content_consumed = True
    r.url = 'https://www.cwa.gov.tw/test'
    return r


@contextmanager
def scope(kind):
    with history_scope(POLICY, {}, NOW) as ctx:
        ctx.active_kind = kind
        yield ctx


class CwaFallbackTests(unittest.TestCase):
    def test_rainfall_time_fallback_skips_midnight_daily_product_and_wrong_grid(self):
        service = CWAService()
        midnight = datetime.fromisoformat('2026-10-31T00:25:00+08:00')
        with history_scope(POLICY, {}, midnight), patch('src.services.cwa_service.http_get', return_value=reply()) as get:
            result = service.resolve_latest_image(image_prefix=service.rainfall_image_prefix,
                    image_pattern=service.rainfall_image_pattern, publish_delay_minutes=20)
        self.assertEqual(result[1], '2026-10-30 23:30')
        self.assertIn('2026-10-30_2330.QZJ8', get.call_args.args[0])

    def test_local_index_route_failure_can_reach_alternate_metadata(self):
        for kind, html in [('radar', '/Data/radar/CV1_3600_202610301830.png'),
                           ('temperature', '/Data/temperature/2026-10-30_1800.GTP8w.jpg'),
                           ('rainfall', '/Data/rainfall/2026-10-30_1830.QZJ8.jpg'),
                           ('weather_chart', '/Data/fcst_img/FI04.png?t=2026103018-1')]:
            # A route-level error before policy exhaustion, unlike a globally
            # blocked source, may still have a working alternate metadata URL.
            with self.subTest(kind=kind), scope(kind), patch('src.services.cwa_service.http_get',
                    side_effect=[requests.Timeout('PRIVATE'), reply(text=html), reply()] if kind != 'weather_chart'
                    else [requests.Timeout('PRIVATE'), reply()]):
                result = getattr(CWAService(), f'resolve_{kind}_image_url')()
                self.assertIsNotNone(result)

    def test_bad_index_image_stops_instead_of_guessing_many_timestamps(self):
        for kind, script in [('radar', RADAR), ('temperature', TEMP), ('rainfall', RAIN)]:
            for image in (reply(mime='text/html'), reply(body=b''), reply(503)):
                with self.subTest(kind=kind, code=image.status_code), scope(kind), \
                     patch('src.services.cwa_service.http_get', side_effect=[reply(text=script), image]) as get:
                    with self.assertRaises(RuntimeError):
                        getattr(CWAService(), f'resolve_{kind}_image_url')()
                    self.assertEqual(get.call_count, 2)

    def test_future_or_wrong_rainfall_slots_do_not_skip_html_fallback(self):
        script = RAIN.replace('2026-10-30_1830', '2099-10-30_1830').replace('2026-10-30_1800', '2026-10-30_1810')
        with scope('rainfall'), patch('src.services.cwa_service.http_get', side_effect=[
                reply(text=script), reply(text='/Data/rainfall/2026-10-30_1800.QZJ8.jpg'), reply()]):
            self.assertEqual(CWAService().resolve_rainfall_image_url()[1], '2026-10-30 18:00')

    def test_request_and_elapsed_time_budgets_stop_fallback(self):
        for options in ({'max_requests': 1}, {'max_seconds': 1, 'clock': Mock(side_effect=[0, 2])}):
            p = HttpPolicy(wait=Mock(), jitter=lambda: 0, **options)
            token = _policy.set(p)
            try:
                with scope('radar'), patch('src.http_client.requests.get', side_effect=lambda *a, **k: reply(404)) as get:
                    with self.assertRaises(RuntimeError): CWAService().resolve_radar_image_url()
                self.assertEqual(get.call_count, 1)
            finally:
                _policy.reset(token)

    def test_temperature_and_rainfall_use_official_index_before_html(self):
        for kind, script, stamp in [('temperature', TEMP, '1800'), ('rainfall', RAIN, '1830')]:
            calls = []
            def get(url, **kwargs):
                calls.append(url)
                if url.endswith('.js'): return reply(text=script)
                if '/Data/' in url: return reply()
                self.fail('HTML should not be needed after a verified index candidate')
            with self.subTest(kind=kind), scope(kind), patch('src.services.cwa_service.http_get', side_effect=get):
                result = getattr(CWAService(), f'resolve_{kind}_image_url')()
            self.assertIn(stamp, result[0])
            self.assertTrue(calls[0].endswith('Observe_temp.js' if kind == 'temperature' else 'RainfallImg_Day.js'))
            self.assertEqual(len(calls), 2)

    def test_radar_malformed_or_absent_index_reaches_html(self):
        for first in (reply(text='new JS structure'), reply(404), reply(410)):
            with self.subTest(status=first.status_code), scope('radar'):
                with patch('src.services.cwa_service.http_get', side_effect=[first,
                        reply(text='/Data/radar/CV1_3600_202610301830.png'), reply()]) as get:
                    result = CWAService().resolve_radar_image_url()
                self.assertEqual(result[1], '2026-10-30 18:30')
                self.assertEqual(get.call_count, 3)

    def test_missing_index_candidate_reaches_existing_time_fallback(self):
        for kind, script in [('radar', RADAR), ('temperature', TEMP), ('rainfall', RAIN)]:
            service = CWAService()
            with self.subTest(kind=kind), scope(kind):
                def get(url, **kwargs):
                    if url.endswith('.js'): return reply(text=script)
                    if '.html' in url: return reply(text='no embedded image')
                    return reply(404)
                with patch('src.services.cwa_service.http_get', side_effect=get), \
                     patch.object(service, 'resolve_latest_image', return_value=('fallback', '2026-10-30 17:00')) as probe:
                    result = getattr(service, f'resolve_{kind}_image_url')()
                self.assertEqual(result[0], 'fallback')
                probe.assert_called_once()

    def test_malformed_time_can_use_html_instead_of_raising_early(self):
        service = CWAService()
        with scope('temperature'), patch('src.services.cwa_service.http_get', side_effect=[
                reply(text=TEMP.replace('2026-10-30_1800', '2026-99-30_1800').replace('2026-10-30_1700', '2026-99-30_1700')),
                reply(text='/Data/temperature/2026-10-30_1800.GTP8w.jpg'), reply()]):
            self.assertEqual(service.resolve_temperature_image_url()[1], '2026-10-30 18:00')

    def test_index_candidates_are_newest_first_and_missing_is_not_permanent(self):
        with scope('temperature') as ctx, patch('src.services.cwa_service.http_get', side_effect=[
                reply(text=TEMP), reply(404), reply()]) as get:
            result = CWAService().resolve_temperature_image_url()
        self.assertEqual(result[1], '2026-10-30 17:00')
        self.assertIn('1800.GTP8w', get.call_args_list[1].args[0])
        self.assertEqual(ctx.outcomes['temperature']['candidate_missing_count'], 1)
        self.assertNotIn('official_missing', json.dumps(ctx.outcomes))

    def test_chart_no_timestamp_or_bad_timestamp_reaches_direct_image(self):
        for html in ('<img src="/Data/fcst_img/FI04.png">',
                     '<img src="/Data/fcst_img/FI04.png?t=2026993000-1">'):
            with self.subTest(html=html), scope('weather_chart'), \
                 patch('src.services.cwa_service.http_get', side_effect=[reply(text=html), reply()]):
                result = CWAService().resolve_weather_chart_image_url()
            self.assertIn('FI04.png', result[0])
            self.assertIsNone(result[1])

    def test_chart_missing_timed_candidate_reaches_direct_image(self):
        with scope('weather_chart'), patch('src.services.cwa_service.http_get', side_effect=[
                reply(text='/Data/fcst_img/FI04.png?t=2026103018-1'), reply(404), reply()]):
            result = CWAService().resolve_weather_chart_image_url()
        self.assertIsNone(result[1])

    def test_satellite_missing_then_older_and_all_missing_are_bounded(self):
        with scope('satellite'), patch('src.services.cwa_service.http_get', side_effect=[reply(404), reply(410), reply()]) as get:
            result = CWAService().resolve_satellite_image_url()
        self.assertEqual(result[1], '2026-10-30 17:40')
        self.assertEqual(get.call_count, 3)
        with scope('satellite'), patch('src.services.cwa_service.http_get', side_effect=lambda *a, **k: reply(404)) as get:
            self.assertIsNone(CWAService().resolve_satellite_image_url())
        self.assertEqual(get.call_count, 36)

    def test_satellite_fault_or_invalid_stops_without_scanning_older_in_both_modes(self):
        from contextlib import nullcontext
        for scoped in (True, False):
            for fault in (requests.Timeout('PRIVATE'), reply(503), reply(mime='text/html'), reply(body=b'')):
                with self.subTest(scoped=scoped, fault=type(fault).__name__), (scope('satellite') if scoped else nullcontext()):
                    def get(*args, **kwargs):
                        if isinstance(fault, Exception): raise fault
                        return fault
                    with patch('src.services.cwa_service.http_get', side_effect=get) as transport:
                        with self.assertRaises(RuntimeError): CWAService().resolve_satellite_image_url()
                    self.assertEqual(transport.call_count, 1)

    def test_exhausted_http_source_does_not_run_blind_fallback(self):
        p = HttpPolicy(wait=Mock(), jitter=lambda: 0)
        token = _policy.set(p)
        try:
            for kind in ('radar',):
                with scope(kind), patch('src.http_client.requests.get', side_effect=lambda *a, **k: reply(503)) as get:
                    with self.assertRaises(RuntimeError): CWAService().resolve_radar_image_url()
                self.assertEqual(get.call_count, 3)
                self.assertEqual(p.sources['cwa']['count'], 3)
        finally:
            _policy.reset(token)

    def test_failed_radar_and_satellite_keep_valid_previous_bytes(self):
        from src.current_day import update_current_product
        from dataclasses import asdict
        for kind in ('radar', 'satellite'):
            for code in (404, 503):
                with self.subTest(kind=kind, code=code), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
                    path = Path(root) / kind / 'latest.json'
                    path.parent.mkdir()
                    old = asdict(CWAService().build_payload(kind, 'Old', 'https://www.cwa.gov.tw/old.png',
                                'https://www.cwa.gov.tw/', '2026-10-30T17:00:00+08:00'))
                    original = (json.dumps(old) + '\n').encode()
                    path.write_bytes(original)
                    with scope(kind), patch('src.services.cwa_service.http_get', side_effect=lambda *a, **k: reply(code)):
                        with self.assertRaises(RuntimeError): update_current_product(kind, Path(root))
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(list(Path(root).rglob('*.json')), [path])


class KmaFallbackTests(unittest.TestCase):
    def test_malformed_api_uses_existing_probe(self):
        for payload in ([{'url': '/x.png', 'tm': 'invalid'}], {'bad': []}, [None], [], None):
            r = reply()
            r._content = json.dumps(payload).encode()
            service = KMAService()
            with self.subTest(payload=payload), patch('src.services.kma_service.http_get', return_value=r), \
                 patch.object(service, 'resolve_latest_850hpa_image_by_probe', return_value=('older', '2026-10-30 09:00')) as probe:
                self.assertEqual(service.resolve_850hpa_image_url()[0], 'older')
            probe.assert_called_once()

    def test_api_candidate_404_uses_existing_probe(self):
        r = reply()
        r._content = json.dumps([{'url': '/x.png', 'tm': '2026103018'}]).encode()
        service = KMAService()
        with patch('src.services.kma_service.http_get', side_effect=[r, reply(404)]), \
             patch.object(service, 'resolve_latest_850hpa_image_by_probe', return_value=('older', '2026-10-30 09:00')) as probe:
            self.assertEqual(service.resolve_850hpa_image_url()[0], 'older')
        probe.assert_called_once()

    def test_probe_fault_is_not_treated_as_fifteen_missing_images(self):
        for fault in (requests.Timeout('PRIVATE'), reply(503), reply(mime='text/html'), reply(body=b'')):
            with self.subTest(fault=type(fault).__name__):
                def get(*args, **kwargs):
                    if isinstance(fault, Exception): raise fault
                    return fault
                with patch('src.services.kma_service.http_get', side_effect=get) as get:
                    with self.assertRaises(RuntimeError): KMAService().resolve_latest_850hpa_image_by_probe()
                self.assertEqual(get.call_count, 1)


class NoAlternativeSourceTests(unittest.TestCase):
    def test_source_exhaustion_keeps_valid_latest_files_byte_for_byte(self):
        from update_images import update_image
        public = Path(__file__).resolve().parents[2] / 'frontend/public/data/images'
        for kind in ('temperature', 'rainfall', 'weather_chart', '850hpa', 'sst', 'tchp'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
                path = Path(root) / kind / 'latest.json'
                path.parent.mkdir()
                original = (public / kind / 'latest.json').read_bytes()
                path.write_bytes(original)
                with scope(kind), patch('src.http_client.requests.get', side_effect=lambda *a, **k: reply(404)), \
                     patch('requests.Session.get', side_effect=lambda *a, **k: reply(404)):
                    with self.assertRaises(RuntimeError): update_image(kind, Path(root))
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(Path(root).rglob('*.json')), [path])

    def test_sst_real_resolver_fails_safely_without_inventing_another_source(self):
        from src.services.ocean_service import OceanService
        date = 'var yye = 2026; var mme = 10; var dde = 30;'
        scenarios = [([requests.Timeout('PRIVATE')], 1),
                     ([reply(text='changed structure')], 1),
                     ([reply(text=date), reply(404)], 2),
                     ([reply(text=date), reply(mime='text/html')], 2),
                     ([reply(text=date), reply(body=b'')], 2)]
        for responses, count in scenarios:
            with self.subTest(count=count, empty=len(responses) == 2 and responses[-1].content == b''), \
                 patch('src.services.ocean_service.http_get', side_effect=responses) as get:
                with self.assertRaises(RuntimeError): OceanService().resolve_latest_sst_image()
                self.assertEqual(get.call_count, count)

    def test_tchp_index_absent_malformed_and_fault_do_not_guess_filenames(self):
        for r in (reply(404), reply(text='changed structure'), requests.Timeout('PRIVATE')):
            with self.subTest(response=type(r).__name__), scope('tchp'), \
                 patch('src.services.cwa_service.http_get', side_effect=[r]) as get:
                try:
                    result = CWAService().resolve_tchp_image_url()
                    self.assertIsNone(result)
                except RuntimeError as exc:
                    self.assertIn(str(exc), ('candidate_source_error', 'candidate_validation_error'))
                self.assertEqual(get.call_count, 1)

    def test_rankings_api_failure_keeps_valid_previous_bytes(self):
        from src.rainfall_rankings import update_rankings
        from src.services.rainfall_observation_service import RainfallObservationService
        for r in (reply(500), reply(text='not json'), reply(text='{"records":{}}')):
            with self.subTest(code=r.status_code), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
                output = Path(root) / 'latest.json'
                original = (Path(__file__).resolve().parents[2] / 'frontend/public/data/rainfall/rankings/latest.json').read_bytes()
                output.write_bytes(original)
                with patch.dict('os.environ', {'CWA_API_KEY': 'TEST_ONLY'}), \
                     patch('src.services.rainfall_observation_service.http_get', return_value=r) as get:
                    with self.assertRaises(RuntimeError): update_rankings(output)
                self.assertEqual(output.read_bytes(), original)
                self.assertEqual(get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
