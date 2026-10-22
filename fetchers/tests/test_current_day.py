from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.cwa_service import CWAService


class CurrentDayTests(unittest.TestCase):
    def test_future_latest_never_replaces_previous_json(self):
        from src.current_day import update_current_product
        service = CWAService()
        latest = service.build_payload('radar', 'Future', 'https://example.com/img.png',
                                      'https://example.com/', '2999-10-22T01:00:00+08:00')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / 'radar/latest.json'
            output.parent.mkdir()
            original = json.dumps(asdict(service.build_payload('radar', 'Previous',
                'https://example.com/old.png', 'https://example.com/', '2026-10-22T00:00:00+08:00'))).encode()
            output.write_bytes(original)
            with patch.object(CWAService, 'fetch_radar', return_value=iter([latest])), \
                 patch.object(CWAService, 'check_image_url', return_value=True):
                with self.assertRaises(RuntimeError):
                    update_current_product('radar', Path(directory))
            self.assertEqual(output.read_bytes(), original)

    def test_daily_update_is_attempted_when_latest_rainfall_fails(self):
        from src.current_day import update_current_product
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with patch.object(CWAService, 'fetch_rainfall', return_value=iter([])), \
                 patch('src.current_day.update_daily_rainfall') as daily:
                with self.assertRaises(RuntimeError):
                    update_current_product('rainfall', Path(directory))
            daily.assert_called_once()

    def test_three_latest_payloads_have_taipei_image_times(self):
        service = CWAService()
        for kind in ('radar', 'satellite', 'rainfall'):
            with self.subTest(kind=kind), patch.object(service, f'resolve_{kind}_image_url',
                    return_value=('https://example.com/img.png', '2026-10-22 01:00')):
                self.assertEqual(next(getattr(service, f'fetch_{kind}')()).image_time,
                                 '2026-10-22T01:00:00+08:00')

    def test_scan_starts_and_ends_at_verified_latest_and_merges(self):
        from src.current_day import publish_current_history
        for kind, expected in [('radar', 7), ('satellite', 7), ('rainfall', 2)]:
            service = CWAService()
            latest = service.build_payload(kind, 'Latest', 'https://example.com/img.png',
                                          'https://example.com/', '2026-10-22T01:00:00+08:00')
            now = datetime.fromisoformat('2026-10-22T01:01:00+08:00')
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                with patch.object(service, 'check_image_url', return_value=True):
                    result = publish_current_history(service, latest, Path(directory), now=now)
                self.assertEqual(len(result['items']), expected)
                self.assertEqual(result['items'][0]['image_time'][11:16], '00:30' if kind == 'rainfall' else '00:00')
                self.assertEqual(result['items'][-1]['image_time'], latest.image_time)
                old = result['items'][0]
                with patch.object(service, 'check_image_url', side_effect=lambda url: '0100' in url or '-01-00.jpg' in url):
                    again = publish_current_history(service, latest, Path(directory), now=now)
                self.assertIn(old, again['items'])
                self.assertEqual(len(again['items']), expected)

    def test_all_failed_scan_keeps_previous_bytes(self):
        from src.current_day import publish_current_history
        service = CWAService()
        latest = service.build_payload('radar', 'Radar', 'https://example.com/img.png',
                                      'https://example.com/', '2026-10-22T00:30:00+08:00')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / 'radar/history/2026-10-22.json'
            output.parent.mkdir(parents=True)
            output.write_bytes(b'previous success')
            with patch.object(service, 'check_image_url', side_effect=RuntimeError('timeout')):
                with self.assertRaises(RuntimeError):
                    publish_current_history(service, latest, Path(directory),
                        now=datetime.fromisoformat('2026-10-22T00:31:00+08:00'))
            self.assertEqual(output.read_bytes(), b'previous success')

    def test_midnight_keeps_yesterdays_latest_without_scanning_yesterday(self):
        from src.current_day import publish_current_history
        service = CWAService()
        latest = service.build_payload('radar', 'Radar', 'https://example.com/img.png',
                                      'https://example.com/', '2026-10-21T23:50:00+08:00')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with patch.object(service, 'check_image_url') as check:
                result = publish_current_history(service, latest, Path(directory),
                    now=datetime.fromisoformat('2026-10-22T00:05:00+08:00'))
            self.assertIsNone(result)
            check.assert_not_called()

    def test_partial_missing_and_failed_scan_reports_gaps_without_losing_data(self):
        from src.current_day import publish_current_history
        service = CWAService()
        latest = service.build_payload('radar', 'Radar', 'https://example.com/img.png',
                                      'https://example.com/', '2026-10-22T00:30:00+08:00')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            def check(url):
                if '0010' in url: return False
                if '0020' in url: raise RuntimeError('timeout')
                return True
            with patch.object(service, 'check_image_url', side_effect=check):
                result = publish_current_history(service, latest, Path(directory),
                    now=datetime.fromisoformat('2026-10-22T00:31:00+08:00'))
            self.assertEqual(result['missing'], ['2026-10-22T00:10:00+08:00'])
            self.assertEqual(result['failed'], ['2026-10-22T00:20:00+08:00'])
            self.assertFalse(result['complete'])
            self.assertEqual(len(result['items']), 2)


class DailyRainTests(unittest.TestCase):
    script = """var RainDay={'Tab0':{
      'Day0':{0:{'img':'2026-10-22_0100.QZJ8','text':'2026/10/22 01:00'}},
      'Day1':{0:{'img':'2026-10-22_0000.QZJ8','text':'2026/10/22 00:00'}},
      'Day2':{0:{'img':'2026-10-21_0000.QZJ8','text':'2026/10/21 00:00'}}}};"""

    def test_official_days_use_correct_dates_and_accumulation_boundaries(self):
        from src.current_day import update_daily_rainfall
        service = CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with patch.object(service, 'fetch_rainfall_day_script', return_value=self.script), \
                 patch.object(service, 'check_image_url', return_value=True):
                data = update_daily_rainfall(service, Path(directory),
                    now=datetime.fromisoformat('2026-10-22T01:05:00+08:00'))
            self.assertEqual([p['label'] for p in data['items']], ['今日', '昨日', '前日'])
            self.assertEqual([p['represented_date'] for p in data['items']], ['2026-10-22', '2026-10-21', '2026-10-20'])
            self.assertEqual(data['items'][1]['image_time'], '2026-10-22T00:00:00+08:00')
            self.assertEqual(data['items'][1]['accumulation_start'], '2026-10-21T00:00:00+08:00')
            self.assertEqual(data['items'][1]['accumulation_end'], '2026-10-22T00:00:00+08:00')

    def test_missing_wrong_day_or_failed_image_preserves_daily_file(self):
        from src.current_day import update_daily_rainfall
        for script, status in [(self.script.replace("'Day2'", "'Day9'"), True),
                               (self.script.replace('2026-10-22_0100', '2026-10-21_0100'), True),
                               (self.script, False)]:
            service = CWAService()
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                output = Path(directory) / 'rainfall/daily/latest.json'
                output.parent.mkdir(parents=True)
                output.write_bytes(b'previous daily success')
                with patch.object(service, 'fetch_rainfall_day_script', return_value=script), \
                     patch.object(service, 'check_image_url', return_value=status):
                    with self.assertRaises((RuntimeError, ValueError)):
                        update_daily_rainfall(service, Path(directory),
                            now=datetime.fromisoformat('2026-10-22T01:05:00+08:00'))
                self.assertEqual(output.read_bytes(), b'previous daily success')
