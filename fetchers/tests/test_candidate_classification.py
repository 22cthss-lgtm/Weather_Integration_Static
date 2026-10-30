from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.history_reconciliation import history_scope
from src.services.cwa_service import CWAService

POLICY = {'interval_seconds':3600,'max_rechecks':3,'max_slots_per_run':12,'current_day_only':True}
NOW = datetime.fromisoformat('2026-10-29T12:00:00+08:00')


def response(code=200, content_type='image/png', body=b'x'):
    result = Mock(status_code=code,ok=200<=code<400,
                  headers={'Content-Type':content_type,'content-type':content_type})
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.iter_content.return_value = iter([body])
    if code >= 400:
        result.raise_for_status.side_effect = requests.HTTPError('SECRET',response=result)
    return result


class CandidateClassificationTests(unittest.TestCase):
    def test_missing_candidates_allow_older_probe_without_guessing_official_missing(self):
        service = CWAService()
        with history_scope(POLICY,{},NOW) as ctx:
            ctx.active_kind = 'satellite'
            with patch('src.services.cwa_service.http_get',side_effect=[response(404),response(410),response()]) as get:
                self.assertIsNotNone(service.resolve_satellite_image_url())
            self.assertEqual(get.call_count,3)
            self.assertEqual(ctx.outcomes['satellite']['candidate_missing_count'],2)
            self.assertNotIn('official_missing',json.dumps(ctx.outcomes))

    def test_transport_and_server_failure_stop_resolver_without_36_fake_missing(self):
        for fault in (requests.Timeout('PRIVATE'),requests.ConnectionError('PRIVATE'),response(429),response(503)):
            with self.subTest(fault=type(fault).__name__),history_scope(POLICY,{},NOW) as ctx:
                ctx.active_kind = 'satellite'
                options = {'side_effect':fault} if isinstance(fault,Exception) else {'return_value':fault}
                with patch('src.services.cwa_service.http_get',**options) as get:
                    with self.assertRaisesRegex(RuntimeError,'candidate_source_error'):
                        CWAService().resolve_satellite_image_url()
                self.assertEqual(get.call_count,1)
                self.assertEqual(ctx.outcomes['satellite']['candidate_fault_count'],1)
                self.assertNotIn('PRIVATE',json.dumps(ctx.outcomes))

    def test_nonimage_and_empty_body_are_validation_faults(self):
        for method in ('image_exists','check_image_url'):
            for reply in (response(content_type='text/html'),response(body=b'')):
                with history_scope(POLICY,{},NOW) as ctx:
                    ctx.active_kind = 'radar'
                    with patch('src.services.cwa_service.http_get',return_value=reply):
                        with self.assertRaisesRegex(RuntimeError,'candidate_validation_error'):
                            getattr(CWAService(),method)('https://example.com/SECRET')
                    self.assertEqual(ctx.outcomes['radar']['candidate_invalid_count'],1)
                    self.assertNotIn('SECRET',json.dumps(ctx.outcomes))

    def test_check_url_records_404_and_network_failure(self):
        for reply, category in ((response(404),'missing'),(requests.Timeout('secret'),'fault')):
            with history_scope(POLICY,{},NOW) as ctx:
                ctx.active_kind = 'rainfall'
                options = {'side_effect':reply} if isinstance(reply,Exception) else {'return_value':reply}
                with patch('src.services.cwa_service.http_get',**options):
                    if category == 'missing': self.assertFalse(CWAService().check_image_url('https://example.com/x'))
                    else:
                        with self.assertRaises(RuntimeError): CWAService().check_image_url('https://example.com/x')
                self.assertEqual(ctx.outcomes['rainfall'][f'candidate_{category}_count'],1)

    def test_index_timeout_and_malformed_index_stop_without_probe_fallback(self):
        for resolver in ('resolve_radar_image_url','resolve_temperature_image_url','resolve_rainfall_image_url','resolve_weather_chart_image_url','resolve_tchp_image_url'):
            for reply, category in ((requests.Timeout('PRIVATE'),'fault'),(response(content_type='text/html'),'invalid')):
                if not isinstance(reply,Exception): reply.text = 'unexpected index content'
                with self.subTest(resolver=resolver,category=category),history_scope(POLICY,{},NOW) as ctx:
                    ctx.active_kind = 'radar'
                    options = {'side_effect':reply} if isinstance(reply,Exception) else {'return_value':reply}
                    with patch('src.services.cwa_service.http_get',**options) as get:
                        with self.assertRaises(RuntimeError): getattr(CWAService(),resolver)()
                    self.assertEqual(get.call_count,1)
                    self.assertEqual(ctx.outcomes['radar'][f'candidate_{category}_count'],1)

    def test_legacy_image_probe_still_returns_false_for_network_fault(self):
        with patch('src.services.cwa_service.http_get',side_effect=requests.Timeout('private')):
            self.assertFalse(CWAService().image_exists('https://example.com/x'))

    def test_404_and_410_each_use_single_transport_attempt_and_close_response(self):
        for code in (404,410):
            reply = response(code)
            with history_scope(POLICY,{},NOW) as ctx:
                ctx.active_kind = 'radar'
                with patch('src.services.cwa_service.requests.get',return_value=reply) as get:
                    self.assertFalse(CWAService().image_exists('https://www.cwa.gov.tw/example.png'))
                self.assertEqual(get.call_count,1)
                reply.close.assert_called_once()

    def test_malformed_index_timestamp_is_safely_classified(self):
        reply = response(content_type='text/javascript')
        reply.text = "0:{\"img\":'CV1_3600_202610291200.png', 'text':'2026/99/29 12:00'}"
        with history_scope(POLICY,{},NOW) as ctx:
            ctx.active_kind = 'radar'
            with patch('src.services.cwa_service.http_get',return_value=reply) as get:
                with self.assertRaisesRegex(RuntimeError,'candidate_validation_error'):
                    CWAService().resolve_radar_image_url()
            self.assertEqual(get.call_count,1)
            self.assertEqual(ctx.outcomes['radar']['candidate_invalid_count'],1)


if __name__ == '__main__': unittest.main()
