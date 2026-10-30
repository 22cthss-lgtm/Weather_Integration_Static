from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src import history_reconciliation as h
from src.current_day import publish_current_history, update_current_product
from src.services.cwa_service import CWAService

NOW = datetime.fromisoformat('2026-10-29T12:01:00+08:00')
POLICY = {'interval_seconds':3600,'max_rechecks':3,'max_slots_per_run':12,'current_day_only':True}


class HistoryTests(unittest.TestCase):
    def test_retry_uses_last_attempt_and_policy_instead_of_corrupt_cached_time(self):
        for cached in ('2099-01-01T00:00:00Z', '2020-01-01T00:00:00Z'):
            with self.subTest(cached=cached):
                gaps = {'radar': {'2026-10-29': {'00:00': {
                    'classification': 'missing', 'attempts': 1,
                    'last_attempt_at': h._stamp(NOW), 'next_retry_at': cached}}}}
                self.assertFalse(h.history_due('radar', gaps, NOW+timedelta(minutes=59), POLICY))
                self.assertTrue(h.history_due('radar', gaps, NOW+timedelta(minutes=60), POLICY))

    def latest(self, service, kind='radar', at='12:00'):
        return service.build_payload(kind,'Latest','https://example.com/latest.png',
            'https://example.com/',f'2026-10-29T{at}:00+08:00')

    def test_bounded_budget_shared_across_calls_keeps_latest_and_pending_safe(self):
        service = CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with h.history_scope(POLICY,{},NOW) as ctx:
                with patch.object(service,'check_image_url',return_value=False) as check:
                    first = publish_current_history(service,self.latest(service),directory)
                    again = publish_current_history(service,self.latest(service),directory)
                self.assertEqual(check.call_count,12)
                self.assertEqual(len(first['items']),1)
                self.assertEqual(first['expected_count'],73)
                self.assertEqual(len(again['items'])+len(again['missing'])+len(again['failed']),73)
                statuses = ctx.gaps['radar']['2026-10-29']
                self.assertIn('pending',{v['classification'] for v in statuses.values()})
                self.assertEqual(ctx.outcomes['radar']['history_state'],'incomplete')
                self.assertTrue(h.history_due('radar',ctx.gaps,NOW,POLICY))
        self.assertIsNone(h.current_history_context())

    def test_successful_slots_not_reprobed_and_retry_has_only_three_rechecks(self):
        service = CWAService()
        latest = self.latest(service,at='00:10')
        gaps = {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            for attempt in range(5):
                at = NOW+timedelta(hours=attempt)
                with h.history_scope(POLICY,gaps,at) as ctx:
                    with patch.object(service,'check_image_url',return_value=False) as check:
                        publish_current_history(service,latest,directory)
                    self.assertEqual(check.call_count,1 if attempt<4 else 0)
                    gaps = ctx.gaps
            gap = gaps['radar']['2026-10-29']['00:00']
            self.assertEqual(gap['attempts'],4)
            self.assertFalse(h.history_due('radar',gaps,NOW+timedelta(hours=5),POLICY))
            self.assertFalse(h.history_due('radar',gaps,NOW+timedelta(days=1),POLICY))

    def test_official_satellite_missing_is_never_probed(self):
        service = CWAService()
        policy = dict(POLICY,max_slots_per_run=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with h.history_scope(policy,{},NOW) as ctx:
                with patch.object(service,'check_image_url',return_value=True) as check:
                    result = publish_current_history(service,self.latest(service,'satellite'),directory)
                self.assertIn('2026-10-29T10:40:00+08:00',result['missing'])
                self.assertEqual(ctx.gaps['satellite']['2026-10-29']['10:40']['classification'],'official_missing')
                self.assertEqual(check.call_count,71)

    def test_history_and_daily_failure_do_not_fail_latest(self):
        service = CWAService()
        for kind in ('radar','rainfall'):
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                with h.history_scope(POLICY,{},NOW) as ctx:
                    with patch.object(CWAService,f'fetch_{kind}',return_value=iter([self.latest(service,kind)])), \
                         patch.object(CWAService,'check_image_url',return_value=True), \
                         patch('src.current_day.publish_current_history',side_effect=RuntimeError('private-key')), \
                         patch('src.current_day.update_daily_rainfall',side_effect=RuntimeError('daily-secret')):
                        result = update_current_product(kind,directory)
                    self.assertIsNotNone(result)
                    self.assertTrue(ctx.outcomes[kind]['latest_ok'])
                    self.assertEqual(ctx.outcomes[kind]['history_state'],'unavailable')
                    self.assertNotIn('private-key',json.dumps(ctx.outcomes))
                    if kind == 'rainfall': self.assertFalse(ctx.outcomes[kind]['daily_ok'])

    def test_legacy_latest_success_does_not_raise_history_warning(self):
        service = CWAService()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with patch.object(CWAService,'fetch_radar',return_value=iter([self.latest(service)])), \
                 patch.object(CWAService,'check_image_url',return_value=True), \
                 patch('src.current_day.publish_current_history',side_effect=RuntimeError('history')):
                self.assertIsNotNone(update_current_product('radar',directory))

    def test_safe_state_drops_unknown_private_fields(self):
        value = {'radar':{'2026-10-29':{'00:00':{'classification':'failed','attempts':1,
            'last_attempt_at':'2026-10-29T00:00:00Z','next_retry_at':'2026-10-29T01:00:00Z','secret':'KEY'}}}}
        with h.history_scope(POLICY,value,NOW) as ctx:
            self.assertNotIn('KEY',json.dumps(ctx.gaps))

    def test_gap_state_retains_only_today_and_yesterday_unresolved_stopped_slots(self):
        today = NOW.date()
        gaps = {'radar':{}}
        for age in range(3650):
            gaps['radar'][(today-timedelta(days=age)).isoformat()] = {
                '00:00':{'classification':'success','attempts':1,'last_attempt_at':None,'next_retry_at':None},
                '00:10':{'classification':'failed','attempts':1,'last_attempt_at':None,'next_retry_at':None},
                '00:11':{'classification':'pending','attempts':0,'last_attempt_at':None,'next_retry_at':None}}
        with h.history_scope(POLICY,gaps,NOW) as ctx:
            self.assertEqual(set(ctx.gaps['radar']),{'2026-10-29','2026-10-28'})
            self.assertEqual(set(ctx.gaps['radar']['2026-10-28']),{'00:10'})
            stopped = ctx.gaps['radar']['2026-10-28']['00:10']
            self.assertEqual(stopped['classification'],'stopped')
            self.assertIsNone(stopped['next_retry_at'])
            self.assertNotIn('00:11',ctx.gaps['radar']['2026-10-29'])
            self.assertLess(len(json.dumps(ctx.gaps).encode()),1024)
            self.assertEqual(h._safe_gaps(ctx.gaps),ctx.gaps)
        self.assertLess(len(json.dumps(h._safe_gaps(gaps)).encode()),1024)

    def test_even_every_minute_input_is_bounded_to_product_grids_under_artifact_limit(self):
        gap = {'classification':'failed','attempts':4,
               'last_attempt_at':'2026-10-28T00:00:00Z','next_retry_at':'2026-10-29T00:00:00Z'}
        slots = {f'{hour:02}:{minute:02}':dict(gap) for hour in range(24) for minute in range(60)}
        gaps = {kind:{day:slots for day in ('2026-10-28','2026-10-29')} for kind in h.KINDS}
        with h.history_scope(POLICY,gaps,NOW) as ctx:
            count = sum(len(slots) for days in ctx.gaps.values() for slots in days.values())
            self.assertEqual(count,672)
            self.assertLess(len(json.dumps(ctx.gaps).encode()),200_000)

    def test_retry_wait_and_successful_inventory_are_not_reprobed(self):
        service = CWAService()
        latest = self.latest(service,at='00:20')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with h.history_scope(POLICY,{},NOW) as ctx:
                with patch.object(service,'check_image_url',side_effect=[True,False]) as check:
                    publish_current_history(service,latest,directory)
                self.assertEqual(check.call_count,2)
                gaps = ctx.gaps
            self.assertFalse(h.history_due('radar',gaps,NOW+timedelta(minutes=59),POLICY))
            with h.history_scope(POLICY,gaps,NOW+timedelta(minutes=59)):
                with patch.object(service,'check_image_url') as check:
                    result = publish_current_history(service,latest,directory)
                check.assert_not_called()
                self.assertEqual(len(result['items']),2)
            with h.history_scope(POLICY,gaps,NOW+timedelta(hours=1)) as ctx:
                with patch.object(service,'check_image_url',return_value=True) as check:
                    result = publish_current_history(service,latest,directory)
                self.assertEqual(check.call_count,1)
                self.assertTrue(result['complete'])

    def test_latest_failure_keeps_previous_and_records_safe_outcome_with_daily_attempt(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory)/'rainfall/latest.json'
            output.parent.mkdir()
            output.write_bytes(b'previous')
            with h.history_scope(POLICY,{},NOW) as ctx:
                with patch.object(CWAService,'fetch_rainfall',return_value=iter([])), \
                     patch('src.current_day.update_daily_rainfall') as daily:
                    with self.assertRaises(RuntimeError): update_current_product('rainfall',directory)
                daily.assert_called_once()
                self.assertFalse(ctx.outcomes['rainfall']['latest_ok'])
                self.assertTrue(ctx.outcomes['rainfall']['daily_ok'])
            self.assertEqual(output.read_bytes(),b'previous')


if __name__ == '__main__': unittest.main()
