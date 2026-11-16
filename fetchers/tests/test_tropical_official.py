"""Decisions of the tropical_official task: activity, matching, minting, retention, status.

All instants are fixed; nothing here depends on the current date, time zone or
on whether a cyclone exists today.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tropical_testing as tt
from tropical_testing import (CWA_URL, JMA_FEED, JMA_TARGET, JTWC_PRODUCT, JTWC_RSS, NOW, SECRET,
                              FakeTransport, fixture, hours, quiet_policy, record, result, results)

from src import tropical_official as official
from src.tropical_contract import OFFICIAL_INDEX_PATH, validate_official_index

UTC = timezone.utc
RECENT = NOW - hours(1.5)


def setUpModule():
    tt.block_network()


def tearDownModule():
    tt.unblock_network()


def build(previous, now=NOW, **sources):
    return validate_official_index(official.build_index(previous, results(**sources), now))


def all_three(when=RECENT, **overrides):
    return dict(jma=result(record('jma', when=when, **overrides)),
                jtwc=result(record('jtwc', when=when, **overrides)),
                cwa=result(record('cwa', when=when, **overrides)))


def failed(code='http_error'):
    return result(state='failed', code=code)


class StatusTests(unittest.TestCase):
    """The five outcomes of design.md 3.3."""

    def test_all_sources_failed_writes_nothing(self):
        with self.assertRaises(official.AllSourcesFailed):
            official.build_index(None, results(cwa=failed(), jma=failed('timeout'), jtwc=failed()), NOW)

    def test_ok_with_storms(self):
        index = build(None, **all_three())
        self.assertEqual(index['status'], 'OK_WITH_STORMS')
        self.assertEqual([source['active_count'] for source in index['sources'].values()], [1, 1, 1])

    def test_ok_no_storms_even_when_jtwc_failed(self):
        self.assertEqual(build(None)['status'], 'OK_NO_STORMS')
        index = build(None, jtwc=failed())
        self.assertEqual((index['status'], index['storms']), ('OK_NO_STORMS', []))
        self.assertEqual(index['sources']['jtwc'], {'required': False, 'state': 'failed', 'error_code': 'http_error',
                                                    'last_ok_at': None, 'active_count': None})

    def test_partial_when_a_required_source_failed_even_without_storms(self):
        for missing in ('cwa', 'jma'):
            index = build(None, **{missing: failed('parse_error')})
            self.assertEqual((index['status'], index['storms']), ('PARTIAL', []))
            self.assertEqual(index['sources'][missing]['error_code'], 'parse_error')

    def test_partial_when_storms_exist_and_jtwc_failed(self):
        sources = all_three()
        sources['jtwc'] = failed()
        self.assertEqual(build(None, **sources)['status'], 'PARTIAL')

    def test_jtwc_only_system_is_ok_with_storms(self):
        index = build(None, jtwc=result(record('jtwc', when=RECENT)))
        self.assertEqual((index['status'], index['storms'][0]['cyclone_id']), ('OK_WITH_STORMS', '2026-jtwc-31w'))

    def test_only_ended_storms_left_is_ok_no_storms(self):
        first = build(None, **all_three())
        index = build(first, NOW + hours(24))
        self.assertEqual((index['status'], index['storms'][0]['status']), ('OK_NO_STORMS', 'ended'))

    def test_times_are_utc_and_heartbeat_has_minute_precision(self):
        index = build(None, now=datetime(2026, 11, 11, 18, 30, 47, tzinfo=timezone(timedelta(hours=8))))
        self.assertEqual(index['fetched_at'], '2026-11-11T10:30:47Z')
        self.assertEqual(index['sources']['cwa']['last_ok_at'], '2026-11-11T10:30:00Z')

    def test_failed_source_keeps_previous_heartbeat(self):
        first = build(None)
        index = build(first, NOW + hours(1), jtwc=failed('timeout'))
        self.assertEqual(index['sources']['jtwc']['last_ok_at'], tt.minute(NOW))
        self.assertEqual(index['sources']['cwa']['last_ok_at'], tt.minute(NOW + hours(1)))


class ActivityTests(unittest.TestCase):
    def test_stale_threshold_both_sides_per_agency(self):
        for agency, limit in (('jtwc', 15), ('jma', 9), ('cwa', 15)):
            with self.subTest(agency=agency):
                self.assertTrue(official.is_active(agency, NOW - hours(limit), False, NOW))
                self.assertFalse(official.is_active(agency, NOW - hours(limit) - timedelta(seconds=1), False, NOW))
                self.assertFalse(official.is_active(agency, NOW, True, NOW))

    def test_thresholds_do_not_depend_on_calendar_boundaries(self):
        # Taiwan midnight (16:00Z), UTC midnight and the UTC new year.
        for now in (datetime(2026, 11, 11, 16, 0, tzinfo=UTC), datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
                    datetime(2027, 1, 1, 0, 30, tzinfo=UTC)):
            with self.subTest(now=now):
                index = build(None, now, jma=result(record('jma', when=now - hours(9))))
                self.assertEqual(index['storms'][0]['status'], 'active')
                stale = result(record('jma', when=now - hours(9) - timedelta(minutes=1)))
                self.assertEqual(build(None, now, jma=stale)['storms'], [])

    def test_listed_but_final_or_stale_is_not_active(self):
        first = build(None, **all_three())
        sources = all_three(when=NOW - hours(1))
        sources['jtwc'] = result(record('jtwc', when=NOW - hours(1), ended=True))
        index = build(first, **sources)
        self.assertFalse(index['storms'][0]['summary']['jtwc']['active'])
        self.assertEqual((index['storms'][0]['status'], index['sources']['jtwc']['active_count']), ('active', 0))

    def test_source_ok_but_no_longer_listing_turns_inactive_and_keeps_last_data(self):
        first = build(None, **all_three())
        before = first['storms'][0]['summary']
        index = build(first, NOW + hours(1), jma=result(record('jma', when=NOW)))  # CWA and JTWC ok, empty lists
        summary = index['storms'][0]['summary']
        for agency in ('cwa', 'jtwc'):
            self.assertFalse(summary[agency]['active'])
            self.assertEqual({k: v for k, v in summary[agency].items() if k != 'active'},
                             {k: v for k, v in before[agency].items() if k != 'active'})
        self.assertTrue(summary['jma']['active'])
        self.assertEqual(index['storms'][0]['status'], 'active')

    def test_jma_without_new_bulletin_uses_only_the_stale_threshold(self):
        first = build(None, jma=result(record('jma', when=RECENT)))
        still = build(first, RECENT + hours(9))
        self.assertTrue(still['storms'][0]['summary']['jma']['active'])
        gone = build(first, RECENT + hours(9) + timedelta(seconds=1))
        self.assertEqual((gone['storms'][0]['status'], gone['storms'][0]['ended_at']),
                         ('ended', tt.minute(RECENT + hours(9))))

    def test_failed_source_carries_previous_active_without_stale_threshold(self):
        first = build(None, jtwc=result(record('jtwc', when=RECENT)))
        # 60 hours later the analysis is far beyond the 15-hour threshold, yet "not fetched" is not "ended".
        index = build(first, NOW + hours(60), jtwc=failed())
        storm = index['storms'][0]
        self.assertTrue(storm['summary']['jtwc']['active'])
        self.assertEqual((storm['status'], index['status']), ('active', 'PARTIAL'))

    def test_failed_source_carry_stops_after_72_hours_both_sides(self):
        first = build(None, jtwc=result(record('jtwc', when=RECENT)))  # last_ok_at = NOW (minute)
        at_limit = build(first, NOW + hours(72), jtwc=failed())
        self.assertTrue(at_limit['storms'][0]['summary']['jtwc']['active'])
        self.assertEqual(at_limit['status'], 'PARTIAL')
        beyond = build(first, NOW + hours(72) + timedelta(minutes=1), jtwc=failed())
        self.assertFalse(beyond['storms'][0]['summary']['jtwc']['active'])
        # A JTWC-only system then ends, and with CWA and JMA fine the overall answer is "no storms".
        self.assertEqual((beyond['storms'][0]['status'], beyond['status']), ('ended', 'OK_NO_STORMS'))

    def test_failed_source_round_still_uses_the_records_it_did_get(self):
        first = build(None, **all_three())
        newer = record('jma', when=NOW)
        index = build(first, NOW + hours(1), jma=result(newer, state='failed', code='validation_error'),
                      jtwc=result(record('jtwc', when=NOW), state='failed'), cwa=result(record('cwa', when=NOW)))
        storm = index['storms'][0]
        self.assertEqual(storm['summary']['jma']['analysis_time'], tt.stamp(NOW))
        self.assertEqual(storm['summary']['jtwc']['analysis_time'], tt.stamp(NOW))
        self.assertEqual((index['status'], index['sources']['jma']['active_count']), ('PARTIAL', None))

    def test_failed_source_round_applies_stale_threshold_to_fetched_records_only(self):
        first = build(None, jma=result(record('jma', when=RECENT), record('jma', when=RECENT, number='TC2639', name='OTHER', lat=12.0)))
        fetched = record('jma', when=RECENT)  # same old bulletin again, now 10.5 h old
        index = build(first, RECENT + hours(10.5), jma=result(fetched, state='failed', code='validation_error'))
        by_id = {storm['cyclone_id']: storm for storm in index['storms']}
        self.assertFalse(by_id['2026-jma-tc2638']['summary']['jma']['active'])  # fetched: threshold applies
        self.assertTrue(by_id['2026-jma-tc2639']['summary']['jma']['active'])   # not fetched: carried

    def test_older_bulletin_cannot_revive_an_ended_system(self):
        first = build(None, jma=result(record('jma', when=RECENT)))
        ended = build(first, NOW + hours(1), jma=result(record('jma', when=NOW, ended=True)))
        self.assertEqual(ended['storms'][0]['ended_at'], tt.minute(NOW + hours(1)))
        # Next run only the older, still-active bulletin is obtained (the final one failed to download).
        older = result(record('jma', when=RECENT), state='failed', code='network_error')
        for jma in (older, result(record('jma', when=RECENT))):
            again = build(ended, NOW + hours(2), jma=jma)
            storm = again['storms'][0]
            self.assertEqual((storm['status'], storm['ended_at'], storm['summary']['jma']['active']),
                             ('ended', tt.minute(NOW + hours(1)), False))
            self.assertEqual(storm['summary']['jma']['analysis_time'], tt.stamp(NOW))

    def test_never_successful_source_is_carried_from_its_own_analysis_time(self):
        partial = build(None, jtwc=result(record('jtwc', when=RECENT), state='failed'))
        self.assertIsNone(partial['sources']['jtwc']['last_ok_at'])
        self.assertEqual(partial['storms'][0]['status'], 'active')
        carried = build(partial, NOW + hours(1), jtwc=failed())
        self.assertTrue(carried['storms'][0]['summary']['jtwc']['active'])
        limit = RECENT + hours(72)
        self.assertTrue(build(partial, limit, jtwc=failed())['storms'][0]['summary']['jtwc']['active'])
        self.assertFalse(build(partial, limit + timedelta(seconds=1), jtwc=failed())['storms'][0]['summary']['jtwc']['active'])

    def test_active_count_matches_the_summaries(self):
        first = build(None, jma=result(record('jma', when=RECENT)))
        quiet = build(first, NOW + hours(1))  # JMA ok, no new bulletin, still inside 9 hours
        self.assertTrue(quiet['storms'][0]['summary']['jma']['active'])
        self.assertEqual(quiet['sources']['jma']['active_count'], 1)
        self.assertEqual(quiet['sources']['cwa']['active_count'], 0)

    def test_analysis_from_the_future_fails_that_source(self):
        edge = build(None, jtwc=result(record('jtwc', when=NOW + hours(1))))
        self.assertEqual((edge['sources']['jtwc']['state'], len(edge['storms'])), ('ok', 1))
        future = build(None, jtwc=result(record('jtwc', when=NOW + hours(1) + timedelta(seconds=1))),
                       jma=result(record('jma', when=RECENT)))
        self.assertEqual((future['sources']['jtwc']['state'], future['sources']['jtwc']['error_code']),
                         ('failed', 'parse_error'))
        self.assertEqual([s['cyclone_id'] for s in future['storms']], ['2026-jma-tc2638'])
        self.assertIsNone(future['storms'][0]['summary']['jtwc'])

    def test_older_record_never_replaces_newer_data(self):
        first = build(None, jma=result(record('jma', when=RECENT, lat=30.0)))
        index = build(first, jma=result(record('jma', when=RECENT - hours(3), lat=10.0)))
        self.assertEqual(index['storms'][0]['summary']['jma']['lat'], 30.0)


class MatchingTests(unittest.TestCase):
    def test_mint_priority_is_jma_then_jtwc_then_cwa(self):
        self.assertEqual(build(None, **all_three())['storms'][0]['cyclone_id'], '2026-jma-tc2638')
        sources = all_three()
        del sources['jma']
        self.assertEqual(build(None, **sources)['storms'][0]['cyclone_id'], '2026-jtwc-31w')
        self.assertEqual(build(None, cwa=result(record('cwa', when=RECENT)))['storms'][0]['cyclone_id'], '2026-cwa-td35')
        typhoon_only = record('cwa', when=RECENT)
        typhoon_only.update(ids={'cwa_ty': '31', 'cwa_td': None}, key=('ty', '31'))
        self.assertEqual(build(None, cwa=result(typhoon_only))['storms'][0]['cyclone_id'], '2026-cwa-ty31')

    def test_name_match_joins_agencies_and_fills_identifiers(self):
        storm = build(None, **all_three())['storms'][0]
        self.assertEqual(storm['match'], {'jtwc': 'name', 'jma': 'origin', 'cwa': 'name'})
        self.assertEqual(storm['ids'], {'jtwc': '31W', 'jma_tc': 'TC2638', 'jma_number': None, 'cwa_ty': None, 'cwa_td': '35'})
        self.assertEqual((storm['name'], storm['season'], storm['origin_basin']), ('CEMPAKA', 2026, 'WP'))

    def test_continuation_keeps_the_id_and_reports_id_match(self):
        first = build(None, **all_three())
        renamed = all_three(when=NOW, name='RENAMED')
        storm = build(first, NOW + hours(1), **renamed)['storms']
        self.assertEqual(len(storm), 1)
        self.assertEqual(storm[0]['cyclone_id'], '2026-jma-tc2638')
        self.assertEqual(storm[0]['match'], {'jtwc': 'id', 'jma': 'origin', 'cwa': 'id'})

    def test_id_survives_naming_and_another_agency_joining(self):
        first = build(None, jma=result(record('jma', when=RECENT, name=None)))
        self.assertIsNone(first['storms'][0]['name'])
        named = build(first, NOW + hours(3), jma=result(record('jma', when=NOW + hours(2))),
                      jtwc=result(record('jtwc', when=NOW + hours(2))))
        self.assertEqual([storm['cyclone_id'] for storm in named['storms']], ['2026-jma-tc2638'])
        self.assertEqual((named['storms'][0]['name'], named['storms'][0]['ids']['jtwc']), ('CEMPAKA', '31W'))

    def test_name_comparison_ignores_case_and_punctuation_but_not_season(self):
        sources = dict(jma=result(record('jma', when=RECENT, name='KONG-REY')),
                       jtwc=result(record('jtwc', when=RECENT, name='KONG REY')))
        self.assertEqual(len(build(None, **sources)['storms']), 1)
        sources['jtwc'] = result(record('jtwc', when=RECENT, name='KONG REY', season=2027))
        self.assertEqual(len(build(None, **sources)['storms']), 2)

    def test_same_name_too_far_apart_is_not_merged(self):
        self.assertAlmostEqual(official.distance_km(0, 0, 0, 1), 111.19, places=1)
        near = dict(jma=result(record('jma', when=RECENT, lat=20.0, lon=130.0)),
                    jtwc=result(record('jtwc', when=RECENT, lat=20.0, lon=144.0)))   # about 1460 km
        self.assertEqual(len(build(None, **near)['storms']), 1)
        far = dict(jma=result(record('jma', when=RECENT, lat=20.0, lon=130.0)),
                   jtwc=result(record('jtwc', when=RECENT, lat=20.0, lon=145.0)))    # about 1565 km
        self.assertEqual([s['cyclone_id'] for s in build(None, **far)['storms']], ['2026-jma-tc2638', '2026-jtwc-31w'])

    def test_unnamed_systems_stay_separate_until_position_matching_exists(self):
        sources = all_three(name=None)
        index = build(None, **sources)
        self.assertEqual([s['cyclone_id'] for s in index['storms']], ['2026-cwa-td35', '2026-jma-tc2638', '2026-jtwc-31w'])
        self.assertTrue(all(sum(v is not None for v in s['summary'].values()) == 1 for s in index['storms']))
        # Once separate they are never merged automatically, even after both get the same name.
        later = build(index, NOW + hours(1), **all_three(when=NOW))
        self.assertEqual(len(later['storms']), 3)
        self.assertEqual({s['name'] for s in later['storms']}, {'CEMPAKA'})

    def test_two_records_of_one_agency_never_share_a_system(self):
        twin = record('jtwc', when=RECENT, number='32W', lat=29.5)
        index = build(None, jma=result(record('jma', when=RECENT)), jtwc=result(record('jtwc', when=RECENT), twin))
        self.assertEqual([s['cyclone_id'] for s in index['storms']], ['2026-jma-tc2638', '2026-jtwc-32w'])
        self.assertEqual(index['storms'][0]['ids']['jtwc'], '31W')

    def test_existing_binding_is_not_overturned_by_a_name(self):
        first = build(None, jma=result(record('jma', when=RECENT)), jtwc=result(record('jtwc', when=RECENT, name='OTHER')))
        self.assertEqual(len(first['storms']), 2)
        later = build(first, NOW + hours(1), jma=result(record('jma', when=NOW)), jtwc=result(record('jtwc', when=NOW)))
        self.assertEqual([s['ids']['jtwc'] for s in later['storms']], [None, '31W'])

    def test_inactive_leftovers_never_mint_including_first_run(self):
        leftovers = dict(jma=result(record('jma', when=RECENT, ended=True)),
                         jtwc=result(record('jtwc', when=RECENT, ended=True)),
                         cwa=result(record('cwa', when=NOW - hours(40))))
        index = build(None, **leftovers)
        self.assertEqual((index['status'], index['storms']), ('OK_NO_STORMS', []))
        self.assertEqual([s['active_count'] for s in index['sources'].values()], [0, 0, 0])

    def test_removed_system_is_not_reminted_from_leftover_data(self):
        first = build(None, **all_three())
        ended = build(first, NOW + hours(20), jtwc=result(record('jtwc', when=RECENT, ended=True)))
        self.assertEqual(ended['storms'][0]['status'], 'ended')
        gone = build(ended, NOW + hours(20 + 48) + timedelta(minutes=1), jtwc=result(record('jtwc', when=RECENT, ended=True)))
        self.assertEqual(gone['storms'], [])
        again = build(gone, NOW + hours(70), jtwc=result(record('jtwc', when=RECENT, ended=True)))
        self.assertEqual(again['storms'], [])

    def test_inactive_record_can_still_join_an_existing_system_by_name(self):
        index = build(None, jma=result(record('jma', when=RECENT)), jtwc=result(record('jtwc', when=RECENT, ended=True)))
        storm = index['storms'][0]
        self.assertEqual((len(index['storms']), storm['match']['jtwc'], storm['summary']['jtwc']['active']), (1, 'name', False))

    def test_central_pacific_system_joins_only_after_crossing_and_then_stays(self):
        east = record('jtwc', when=RECENT, number='04C', name='PENA', lat=9.8, lon=-171.3, in_scope=False, origin_basin='CP')
        self.assertEqual(build(None, jtwc=result(east))['storms'], [])
        west = record('jtwc', when=NOW, number='04C', name='PENA', lat=10.2, lon=179.5, in_scope=True, origin_basin='CP')
        crossed = build(None, NOW + hours(1), jtwc=result(west))
        self.assertEqual((crossed['storms'][0]['cyclone_id'], crossed['storms'][0]['origin_basin']), ('2026-jtwc-04c', 'CP'))
        back = record('jtwc', when=NOW + hours(6), number='04C', name='PENA', lat=10.5, lon=-179.0, in_scope=False, origin_basin='CP')
        kept = build(crossed, NOW + hours(7), jtwc=result(back))
        self.assertEqual((kept['storms'][0]['status'], kept['storms'][0]['summary']['jtwc']['lon']), ('active', -179.0))

    def test_out_of_scope_jma_or_cwa_record_is_ignored(self):
        index = build(None, jma=result(record('jma', when=RECENT, lon=85.0, in_scope=False)))
        self.assertEqual(index['storms'], [])

    def test_invalid_previous_index_is_treated_as_no_systems(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / 'index.json'
            self.assertIsNone(official.read_previous(path))
            for content in (b'{}', b'not json', b'[]', json.dumps(dict(tt.valid_index(), extra=1)).encode()):
                path.write_bytes(content)
                self.assertIsNone(official.read_previous(path))
            path.write_text(json.dumps(tt.valid_index()), encoding='utf-8')
            self.assertEqual(official.read_previous(path)['status'], 'PARTIAL')

    def test_season_and_id_do_not_change_across_new_year(self):
        december = datetime(2026, 12, 31, 20, tzinfo=UTC)
        first = build(None, december, **all_three(when=december - hours(2)))
        january = datetime(2027, 1, 1, 2, tzinfo=UTC)
        later = build(first, january, **all_three(when=january - hours(2)))
        self.assertEqual([(s['cyclone_id'], s['season']) for s in later['storms']], [('2026-jma-tc2638', 2026)])

    def test_storms_are_sorted_and_output_is_deterministic(self):
        sources = dict(jma=result(record('jma', when=RECENT, number='TC2640', name='ZED', lat=10.0),
                                  record('jma', when=RECENT, number='TC2639', name='ABLE', lat=20.0)),
                       jtwc=result(record('jtwc', when=RECENT, number='33W', name=None)))
        one, two = build(None, **sources), build(None, **deepcopy(sources))
        self.assertEqual(one, two)
        ids = [s['cyclone_id'] for s in one['storms']]
        self.assertEqual(ids, sorted(ids))


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.active = build(None, **all_three())
        self.ended_at = NOW + hours(24)
        self.ended = build(self.active, self.ended_at)

    def test_first_end_is_stamped_once(self):
        storm = self.ended['storms'][0]
        self.assertEqual((storm['status'], storm['ended_at']), ('ended', tt.minute(self.ended_at)))
        later = build(self.ended, self.ended_at + hours(5))
        self.assertEqual(later['storms'][0]['ended_at'], tt.minute(self.ended_at))

    def test_ended_system_is_kept_48_hours_both_sides(self):
        self.assertEqual(len(build(self.ended, self.ended_at + hours(48))['storms']), 1)
        self.assertEqual(build(self.ended, self.ended_at + hours(48) + timedelta(seconds=1))['storms'], [])

    def test_reactivation_clears_ended_at(self):
        again = build(self.ended, self.ended_at + hours(6), jma=result(record('jma', when=self.ended_at + hours(5))))
        storm = again['storms'][0]
        self.assertEqual((storm['status'], storm['ended_at'], storm['cyclone_id']), ('active', None, '2026-jma-tc2638'))

    def test_more_than_twelve_storms_sheds_longest_ended_first(self):
        base = self.ended['storms'][0]
        crowd = deepcopy(self.ended)
        crowd['storms'] = []
        for n in range(12):
            storm = deepcopy(base)
            storm['cyclone_id'] = f'2026-jma-tc27{n:02d}'
            storm['ids'] = dict(base['ids'], jma_tc=f'TC27{n:02d}', jtwc=None, cwa_td=None)
            storm['ended_at'] = tt.minute(self.ended_at + timedelta(minutes=n))
            crowd['storms'].append(storm)
        validate_official_index(crowd)
        index = build(crowd, self.ended_at + hours(1), jma=result(record('jma', when=self.ended_at, number='TC2799', name='NEW')))
        ids = [s['cyclone_id'] for s in index['storms']]
        self.assertEqual(len(ids), 12)
        self.assertIn('2026-jma-tc2799', ids)
        self.assertNotIn('2026-jma-tc2700', ids)


class TaskTests(unittest.TestCase):
    """End to end through the fake transport: real samples in, validated index out."""

    def update(self, root, routes, now=NOW, key=SECRET):
        transport = FakeTransport(routes)
        index = official.update_tropical_official(root, now=now, transport=transport, wait=lambda s: None,
                                                  clock=lambda: 0.0, api_key=key, policy=quiet_policy())
        return index, transport

    def test_real_samples_produce_one_matched_system(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            index, transport = self.update(root, tt.cempaka_routes())
            written = json.loads((root / OFFICIAL_INDEX_PATH).read_text(encoding='utf-8'))
            self.assertEqual(written, index)
            self.assertEqual(index['status'], 'OK_WITH_STORMS')
            storm, = index['storms']
            self.assertEqual(storm['cyclone_id'], '2026-jma-tc2638')
            self.assertEqual(storm['ids'], {'jtwc': '31W', 'jma_tc': 'TC2638', 'jma_number': '2632', 'cwa_ty': '31', 'cwa_td': '35'})
            self.assertEqual((storm['name'], storm['name_zh']), ('CEMPAKA', '查帕卡'))
            self.assertEqual(storm['last_fix_time'], '2026-11-11T09:00:00Z')
            # PENA (04C) is east of 180 and is not listed.
            self.assertEqual(index['sources']['jtwc']['active_count'], 1)
            # CWA 1; JMA feed, 2 bulletins, targetTc; JTWC RSS and 2 products.
            self.assertEqual(len(transport.calls), 8)
            self.assertNotIn(SECRET, (root / OFFICIAL_INDEX_PATH).read_text(encoding='utf-8'))
            self.assertNotIn('opendata.cwa.gov.tw/api', json.dumps(index))

    def test_synthetic_no_system_run_makes_four_requests(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            index, transport = self.update(Path(directory), tt.no_storm_routes())
            self.assertEqual((index['status'], index['storms']), ('OK_NO_STORMS', []))
            self.assertEqual(sorted(transport.urls), sorted([CWA_URL, JMA_FEED, JMA_TARGET, JTWC_RSS]))

    def test_real_no_system_responses_of_20261115_give_ok_no_storms(self):
        # Real bodies: CWA still lists CEMPAKA (last analysis 11-11 06Z), JMA lists nothing, JTWC has no WP warning.
        routes = {CWA_URL: fixture('cwa_datastore_cempaka.json'),
                  JMA_FEED: fixture('jma_extra_feed_no_vptw_cropped_20261115.xml'),
                  JMA_TARGET: fixture('jma_targetTc_empty_20261115.json'),
                  JTWC_RSS: fixture('jtwc_rss_no_wp_systems_20261115.xml')}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            index, transport = self.update(Path(directory), routes, datetime(2026, 11, 15, 17, 44, 20, tzinfo=UTC))
            self.assertEqual((index['status'], index['storms']), ('OK_NO_STORMS', []))
            self.assertEqual([source['active_count'] for source in index['sources'].values()], [0, 0, 0])
            self.assertEqual(len(transport.calls), 4)

    def test_all_failed_raises_and_leaves_previous_file_untouched(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.no_storm_routes())
            before = (root / OFFICIAL_INDEX_PATH).read_bytes()
            routes = {CWA_URL: 403, JMA_FEED: 404, JTWC_RSS: requests.Timeout('x')}
            with self.assertRaises(official.AllSourcesFailed):
                self.update(root, routes, NOW + hours(1))
            self.assertEqual((root / OFFICIAL_INDEX_PATH).read_bytes(), before)
            self.assertEqual(list((root / 'tropical/official').iterdir()), [root / OFFICIAL_INDEX_PATH])

    def test_first_run_all_failed_writes_no_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            with self.assertRaises(official.AllSourcesFailed):
                self.update(root, {CWA_URL: 500, JMA_FEED: 500, JTWC_RSS: 500})
            self.assertFalse((root / 'tropical').exists())

    def test_single_source_failures_are_never_reported_as_no_storm(self):
        for label, route in (('403', 403), ('404', 404), ('timeout', requests.Timeout('x')), ('5xx', 502),
                             ('malformed', b'<html>')):
            for url, source in ((CWA_URL, 'cwa'), (JMA_FEED, 'jma')):
                with self.subTest(label=label, source=source), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                    index, _ = self.update(Path(directory), dict(tt.no_storm_routes(), **{url: route}))
                    self.assertEqual((index['status'], index['sources'][source]['state']), ('PARTIAL', 'failed'))
            with self.subTest(label=label, source='jtwc'), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                index, _ = self.update(Path(directory), dict(tt.no_storm_routes(), **{JTWC_RSS: route}))
                self.assertEqual((index['status'], index['sources']['jtwc']['state']), ('OK_NO_STORMS', 'failed'))

    def test_final_state_then_system_ends_and_data_is_kept(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            later = datetime(2026, 11, 11, 16, 30, tzinfo=UTC)  # Taiwan 00:30 next day
            final_url = tt.JMA_BULLETIN.format('20261111124152')
            routes = {CWA_URL: fixture('cwa_datastore_cempaka.json'),
                      JMA_FEED: fixture('jma_extra_feed_cropped.xml').replace(
                          b'20261111094118_0_VPTW60', b'20261111124152_0_VPTW60').replace(
                          b'<updated>2026-11-11T09:41:17Z</updated>', b'<updated>2026-11-11T12:41:52Z</updated>'),
                      final_url: fixture('jma_vptw60_tc2638_final.xml'),
                      JMA_TARGET: fixture('jma_targetTc_low.json'),
                      JTWC_RSS: fixture('jtwc_rss_final.xml'),
                      JTWC_PRODUCT.format('wp3126.tcw'): fixture('jtwc_wp3126_final.tcw'),
                      JTWC_PRODUCT.format('cp0426.tcw'): fixture('jtwc_cp0426_warning23.tcw')}
            index, _ = self.update(root, routes, later)
            storm, = index['storms']
            self.assertEqual({a: s['active'] for a, s in storm['summary'].items()}, {'jtwc': False, 'jma': False, 'cwa': True})
            self.assertEqual(storm['summary']['jma']['category'], 'LOW')
            # CWA's last analysis (06Z) becomes stale 15 hours later, with the source still listing it.
            index, _ = self.update(root, routes, datetime(2026, 11, 11, 21, 0, 1, tzinfo=UTC))
            self.assertEqual((index['storms'][0]['status'], index['status']), ('ended', 'OK_NO_STORMS'))
            self.assertEqual(index['storms'][0]['summary']['cwa']['pressure_hpa'], 975)

    def test_missing_cwa_key_is_partial_and_key_is_read_from_environment_by_default(self):
        import os
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            index, transport = self.update(Path(directory), tt.no_storm_routes(), key='')
            self.assertEqual((index['status'], index['sources']['cwa']['error_code']), ('PARTIAL', 'source_error'))
            self.assertNotIn(CWA_URL, transport.urls)
        previous = os.environ.get('CWA_API_KEY')
        os.environ['CWA_API_KEY'] = SECRET
        try:
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                index, transport = self.update(Path(directory), tt.no_storm_routes(), key=None)
                self.assertEqual(index['sources']['cwa']['state'], 'ok')
                self.assertEqual(dict(transport.calls)[CWA_URL]['params']['Authorization'], SECRET)
        finally:
            if previous is None:
                del os.environ['CWA_API_KEY']
            else:
                os.environ['CWA_API_KEY'] = previous

    def test_key_never_reaches_files_output_or_exceptions(self):
        leaking = requests.ConnectionError(f'{CWA_URL}?Authorization={SECRET}&format=JSON')
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            seen = []
            for cwa in (fixture('cwa_datastore_cempaka.json'), leaking, 403, b'{"key":"' + SECRET.encode() + b'"}'):
                index, _ = self.update(root, dict(tt.cempaka_routes(), **{CWA_URL: cwa}))
                seen.append(json.dumps(index, ensure_ascii=False))
                seen.extend(path.read_text(encoding='utf-8') for path in root.rglob('*') if path.is_file())
            try:
                self.update(root, {CWA_URL: leaking, JMA_FEED: 500, JTWC_RSS: 500})
            except official.AllSourcesFailed as failure:
                seen.append(repr(failure) + str(failure.__cause__) + str(failure.__context__))
        self.assertNotIn(SECRET, ''.join(seen) + captured.getvalue())


if __name__ == '__main__':
    unittest.main()
