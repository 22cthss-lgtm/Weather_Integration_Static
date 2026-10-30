"""Pure schedule primitives: no network, local clock or filesystem mutation."""
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import scheduling as s

NOW = datetime(2026, 10, 29, 0, tzinfo=timezone.utc)


class SchedulingTests(unittest.TestCase):
    def test_policy_contains_all_confirmed_intervals(self):
        expected = dict(radar=600, satellite=600, rainfall=1800,
            rainfall_rankings=600, temperature=3600, sst=86400,
            weather_chart=21600, **{'850hpa':21600}, tchp=86400,
            cimss_wind_analysis=10800, cimss_steering_flow=10800,
            seaice_arctic=86400, seaice_antarctic=86400)
        config = s.default_tasks()
        self.assertEqual({k:v['interval_seconds'] for k,v in config.items()}, expected)
        self.assertEqual(json.loads((Path(__file__).parents[1] / 'policies/due-intervals.json').read_text())['tasks'], config)

    def test_new_state_is_all_due_and_success_uses_check_time(self):
        state = s.new_state('content', NOW)
        config = s.default_tasks()['radar']
        self.assertTrue(s.is_due(config, state['tasks']['radar'], NOW)[0])
        s.record_result(state, 'radar', NOW, True)
        self.assertFalse(s.is_due(config, state['tasks']['radar'], NOW + timedelta(seconds=599))[0])
        self.assertTrue(s.is_due(config, state['tasks']['radar'], NOW + timedelta(seconds=600))[0])
        s.record_result(state, 'radar', NOW + timedelta(seconds=600), True)
        self.assertEqual(state['tasks']['radar']['last_successful_check_at'], '2026-10-29T00:10:00Z')

    def test_retry_overrides_normal_due_and_caps_across_rounds(self):
        for kind, delays in [('radar',[600,1200,2400,3600,3600]),
                             ('temperature',[1800,3600,7200,14400,21600,21600])]:
            state = s.new_state('content', NOW)
            at = NOW
            for count, delay in enumerate(delays, 1):
                s.record_result(state, kind, at, False, error_code='timeout')
                task = state['tasks'][kind]
                self.assertEqual(task['consecutive_failures'], count)
                self.assertFalse(s.is_due(s.default_tasks()[kind], task, at + timedelta(seconds=delay-1))[0])
                at += timedelta(seconds=delay)
                self.assertTrue(s.is_due(s.default_tasks()[kind], task, at)[0])
            s.record_result(state, kind, at, True)
            self.assertEqual(task['consecutive_failures'], 0)
            self.assertIsNone(task['next_retry_at'])

    def test_restore_validates_identity_expiry_and_schema_without_assuming_image_time(self):
        config = s.default_tasks()
        original = s.new_state('content', NOW)
        s.record_result(original, 'radar', NOW, True)
        restored, warning = s.restore_state(original, 'content', NOW, config, ttl_seconds=3600)
        self.assertIsNone(warning)
        self.assertEqual(restored, original)
        for document, content, now, code in [
            (None,'content',NOW,'missing'), ({},'content',NOW,'corrupt'),
            (original,'other',NOW,'content_mismatch'),
            (original,'content',NOW+timedelta(seconds=3601),'expired')]:
            result, warning = s.restore_state(document, content, now, config, ttl_seconds=3600)
            self.assertEqual(warning, code)
            self.assertTrue(all(s.is_due(config[k],v,now)[0] for k,v in result['tasks'].items()))
        damaged = copy.deepcopy(original)
        damaged['tasks']['radar']['fetched_at'] = 'private'
        self.assertEqual(s.restore_state(damaged,'content',NOW,config,ttl_seconds=3600)[1], 'corrupt')

    def test_private_error_is_replaced_by_safe_code(self):
        state = s.new_state('content', NOW)
        s.record_result(state, 'radar', NOW, False, error_code='https://secret/?key=TOKEN')
        self.assertEqual(state['tasks']['radar']['error_code'], 'source_error')
        self.assertNotIn('TOKEN', json.dumps(state))

    def test_due_retry_runs_before_normal_interval_and_nonstring_errors_are_safe(self):
        state = s.new_state('content', NOW)
        s.record_result(state, 'temperature', NOW, True)
        s.record_result(state, 'temperature', NOW, False, error_code={'raw':'secret'})
        self.assertTrue(s.is_due(s.default_tasks()['temperature'],
            state['tasks']['temperature'], NOW+timedelta(seconds=1800))[0])
        self.assertNotIn('secret', json.dumps(state))

    def test_restored_instants_must_be_json_strings_and_failure_fields_consistent(self):
        config = s.default_tasks()
        state = s.new_state('content', NOW)
        s.record_result(state,'radar',NOW,True)
        for field, value in [('last_attempt_at',NOW), ('consecutive_failures',True),
                             ('completed_occurrence','2099-01-01')]:
            damaged = copy.deepcopy(state)
            damaged['tasks']['radar'][field] = value
            self.assertEqual(s.restore_state(damaged,'content',NOW,config,ttl_seconds=3600)[1], 'corrupt')

    def test_fixed_time_is_taipei_bounded_and_success_deduplicates(self):
        config = {'mode':'fixed','timezone':'Asia/Taipei','time':'09:30','retry_delays_seconds':[600,1200,2400,3600]}
        policy = {'max_lateness_days':0}
        state = s.new_state('x', NOW, {'radar':config})
        task = state['tasks']['radar']
        self.assertFalse(s.is_due(config, task, NOW, policy)[0])
        at = NOW + timedelta(hours=1, minutes=30)
        self.assertEqual(s.is_due(config,task,at,policy)[:2], (True,'2026-10-29'))
        s.record_result(state,'radar',at,True,'2026-10-29',task_config={'radar':config})
        self.assertFalse(s.is_due(config,task,at,policy)[0])
        self.assertEqual(s.is_due(config,task,NOW+timedelta(days=1,hours=2),policy)[:2], (True,'2026-10-30'))

    def test_fixed_retry_retains_occurrence_then_moves_to_latest_when_outside_window(self):
        config = {'mode':'fixed','timezone':'Asia/Taipei','time':'09:30','retry_delays_seconds':[600,1200,2400,3600]}
        configs = {'radar':config}
        state = s.new_state('x', NOW, configs)
        at = NOW + timedelta(hours=15,minutes=55)  # Taipei 23:55
        s.record_result(state,'radar',at,False,'2026-10-29',task_config=configs)
        task = state['tasks']['radar']
        self.assertEqual(s.is_due(config,task,at+timedelta(minutes=10),{'max_lateness_days':1})[:2], (True,'2026-10-29'))
        self.assertFalse(s.is_due(config,task,at+timedelta(minutes=10),{'max_lateness_days':0})[0])
        self.assertEqual(s.is_due(config,task,NOW+timedelta(days=1,hours=2),{'max_lateness_days':0})[:2], (True,'2026-10-30'))
        self.assertEqual(s.is_due(config,task,NOW+timedelta(days=1,hours=2),{'max_lateness_days':1})[:2], (True,'2026-10-30'))
        self.assertEqual(s.is_due(config,task,NOW+timedelta(days=5,hours=2),{'max_lateness_days':1})[:2], (True,'2026-11-03'))

    def test_new_fixed_occurrence_bypasses_old_retry_and_resets_failure_sequence(self):
        config = {'mode':'fixed','timezone':'Asia/Taipei','time':'09:30','retry_delays_seconds':[600,1200,2400,3600]}
        configs = {'radar':config}
        state = s.new_state('x',NOW,configs)
        before = NOW+timedelta(days=1,hours=1,minutes=29)
        task = state['tasks']['radar']
        for _ in range(4):
            s.record_result(state,'radar',before,False,'2026-10-29',task_config=configs)
        self.assertFalse(s.is_due(config,task,before,{'max_lateness_days':1})[0])
        today = before+timedelta(minutes=1)
        self.assertEqual(s.is_due(config,task,today,{'max_lateness_days':1})[:2],(True,'2026-10-30'))
        s.record_result(state,'radar',today,False,'2026-10-30',task_config=configs)
        self.assertEqual(task['consecutive_failures'],1)
        self.assertEqual(task['next_retry_at'],s._stamp(today+timedelta(seconds=600)))

    def test_bad_state_json_is_reset_and_ttl_boundary_is_inclusive(self):
        config = s.default_tasks()
        original = s.new_state('content',NOW)
        self.assertIsNone(s.restore_state(json.dumps(original),'content',NOW+timedelta(seconds=3600),config,ttl_seconds=3600)[1])
        self.assertEqual(s.restore_state('{','content',NOW,config,ttl_seconds=3600)[1], 'corrupt')
        self.assertEqual(s.restore_state(original,'content',NOW-timedelta(seconds=1),config,ttl_seconds=3600)[1], 'corrupt')

    def test_future_retry_cache_cannot_defer_real_due_time_or_survive_restore(self):
        config = s.default_tasks()
        state = s.new_state('content',NOW)
        s.record_result(state,'radar',NOW,False)
        state['tasks']['radar']['next_retry_at'] = '2099-01-01T00:00:00Z'
        due = NOW+timedelta(seconds=600)
        self.assertTrue(s.is_due(config['radar'],state['tasks']['radar'],due)[0])
        restored, warning = s.restore_state(state,'content',due,config,ttl_seconds=3600)
        self.assertEqual(warning,'corrupt')
        self.assertTrue(s.is_due(config['radar'],restored['tasks']['radar'],due)[0])

    def test_retry_cache_cannot_allow_early_retry_and_normal_due_cache_is_checked(self):
        config = s.default_tasks()
        state = s.new_state('content',NOW)
        s.record_result(state,'radar',NOW,False)
        state['tasks']['radar']['next_retry_at'] = s._stamp(NOW)
        self.assertFalse(s.is_due(config['radar'],state['tasks']['radar'],NOW)[0])
        self.assertEqual(s.restore_state(state,'content',NOW,config,ttl_seconds=3600)[1],'corrupt')
        state = s.new_state('content',NOW)
        s.record_result(state,'radar',NOW,True)
        state['tasks']['radar']['next_due_at'] = '2099-01-01T00:00:00Z'
        self.assertTrue(s.is_due(config['radar'],state['tasks']['radar'],NOW+timedelta(seconds=600))[0])
        self.assertEqual(s.restore_state(state,'content',NOW,config,ttl_seconds=3600)[1],'corrupt')

    def test_policy_and_clock_require_explicit_valid_values(self):
        with self.assertRaises(ValueError):
            s.new_state('x', datetime(2026,10,29))
        config = {'mode':'fixed','timezone':'Asia/Taipei','time':'09:30','retry_delays_seconds':[600,1200,2400,3600]}
        with self.assertRaises(ValueError):
            s.is_due(config, {}, NOW)
        with self.assertRaises(ValueError):
            s.is_due(dict(config,timezone='UTC'), {}, NOW, {'max_lateness_days':1})
        with self.assertRaises(TypeError):
            s.restore_state(None,'x',NOW,s.default_tasks())
        for missing in ({'mode':'interval','interval_seconds':600},
                        {'mode':'fixed','timezone':'Asia/Taipei','time':'09:30'}):
            with self.assertRaisesRegex(ValueError,'retry_delays_seconds'):
                s.new_state('x',NOW,{'custom':missing})


if __name__ == '__main__':
    unittest.main()
