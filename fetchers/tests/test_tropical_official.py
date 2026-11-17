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


ANALYSIS = 'tropical/official/storms/2026-jma-tc2638/analysis.json'
FORECAST = 'tropical/official/storms/2026-jma-tc2638/forecast.json'
LATER = datetime(2026, 11, 11, 16, 30, tzinfo=UTC)  # Taiwan 00:30 on 11-12


def final_routes():
    """Real final products of CEMPAKA, as seen at LATER."""
    return {CWA_URL: fixture('cwa_datastore_cempaka.json'),
            JMA_FEED: fixture('jma_extra_feed_cropped.xml').replace(
                b'20261111094118_0_VPTW60', b'20261111124152_0_VPTW60').replace(
                b'<updated>2026-11-11T09:41:17Z</updated>', b'<updated>2026-11-11T12:41:52Z</updated>'),
            tt.JMA_BULLETIN.format('20261111124152'): fixture('jma_vptw60_tc2638_final.xml'),
            JMA_TARGET: fixture('jma_targetTc_low.json'),
            JTWC_RSS: fixture('jtwc_rss_final.xml'),
            JTWC_PRODUCT.format('wp3126.tcw'): fixture('jtwc_wp3126_final.tcw'),
            JTWC_PRODUCT.format('cp0426.tcw'): fixture('jtwc_cp0426_warning23.tcw')}


def read(root, name):
    return json.loads((Path(root) / name).read_text(encoding='utf-8'))


class StormFileTaskTests(unittest.TestCase):
    """analysis.json and forecast.json (design.md 1.4, 1.5, 3.3, 6.1, 11b)."""

    update = TaskTests.update

    def test_real_samples_write_both_files(self):
        from src.tropical_contract import validate_storm_file
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            analysis, forecast = read(root, ANALYSIS), read(root, FORECAST)
            validate_storm_file(ANALYSIS, analysis)
            validate_storm_file(FORECAST, forecast)
            agencies = analysis['agencies']
            self.assertEqual(agencies['jtwc']['product_url'], JTWC_PRODUCT.format('wp3126.tcw'))
            self.assertEqual(agencies['jtwc']['graphic_url'], JTWC_PRODUCT.format('wp3126.gif'))
            self.assertEqual(agencies['jma']['product_url'], tt.JMA_BULLETIN.format('20261111094118'))
            self.assertEqual((agencies['cwa']['past_track_origin'], len(agencies['cwa']['past_track'])), ('source', 21))
            # The 06:40 bulletin of the same system (same body in this fixture) adds nothing older.
            self.assertEqual((agencies['jtwc']['past_track'], agencies['jma']['past_track']), ([], []))
            # The fix equals the index summary of the same agency.
            index = read(root, OFFICIAL_INDEX_PATH)
            for agency, block in agencies.items():
                summary = index['storms'][0]['summary'][agency]
                self.assertEqual({key: block['fix'][key] for key in ('analysis_time', 'lat', 'lon', 'max_wind')},
                                 {key: summary[key] for key in ('analysis_time', 'lat', 'lon', 'max_wind')})
            self.assertEqual([len(forecast['agencies'][a]['points']) for a in ('jtwc', 'jma', 'cwa')], [2, 2, 2])
            text = ''.join(path.read_text(encoding='utf-8') for path in root.rglob('*.json'))
            for forbidden in (SECRET, 'opendata.cwa.gov.tw/api', 'image_url', 'source_url'):
                self.assertNotIn(forbidden, text)
            # PENA (east of 180) has no index entry and so no files.
            self.assertEqual(sorted(p.name for p in (root / 'tropical/official/storms').iterdir()), ['2026-jma-tc2638'])

    def test_later_run_accumulates_tracks_and_keeps_only_the_latest_report(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            _, transport = self.update(root, final_routes(), LATER)
            agencies = read(root, ANALYSIS)['agencies']
            jtwc, jma = agencies['jtwc'], agencies['jma']
            self.assertEqual((jtwc['fix']['analysis_time'], jtwc['final'], jtwc['bulletin']),
                             ('2026-11-11T12:00:00Z', True, '022'))
            self.assertEqual([p['analysis_time'] for p in jtwc['past_track']], ['2026-11-11T06:00:00Z'])
            self.assertEqual(jtwc['past_track'][0]['lat'], 29.1)
            self.assertEqual((jma['fix']['analysis_time'], jma['final']), ('2026-11-11T12:00:00Z', True))
            self.assertEqual([p['analysis_time'] for p in jma['past_track']], ['2026-11-11T09:00:00Z'])
            forecast = read(root, FORECAST)['agencies']
            self.assertEqual(forecast['jma']['points'], [])  # final bulletin: no forecast part
            self.assertEqual(forecast['jtwc']['init_time'], '2026-11-11T12:00:00Z')
            # CWA served the same response: same blocks.
            self.assertEqual(agencies['cwa']['fix']['analysis_time'], '2026-11-11T06:00:00Z')
            # A third run sees nothing new: the saved JMA bulletin is not downloaded again.
            _, transport = self.update(root, final_routes(), LATER + hours(0.5))
            self.assertNotIn(tt.JMA_BULLETIN.format('20261111124152'), transport.urls)
            self.assertEqual([p['analysis_time'] for p in read(root, ANALYSIS)['agencies']['jma']['past_track']],
                             ['2026-11-11T09:00:00Z'])

    def test_failed_source_keeps_its_saved_blocks(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            before_a, before_f = read(root, ANALYSIS)['agencies'], read(root, FORECAST)['agencies']
            routes = dict(final_routes(), **{JTWC_RSS: 500})
            index, _ = self.update(root, routes, LATER)
            self.assertEqual(index['sources']['jtwc']['state'], 'failed')
            after_a, after_f = read(root, ANALYSIS)['agencies'], read(root, FORECAST)['agencies']
            self.assertEqual((after_a['jtwc'], after_f['jtwc']), (before_a['jtwc'], before_f['jtwc']))
            self.assertNotEqual(after_a['jma'], before_a['jma'])

    def test_one_failed_product_keeps_that_block_and_updates_the_rest(self):
        # JTWC failed as a source (one .tcw missing) but the other product is still used (design.md 3.3).
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            routes = dict(final_routes(), **{JTWC_PRODUCT.format('cp0426.tcw'): 403})
            index, _ = self.update(root, routes, LATER)
            self.assertEqual(index['sources']['jtwc']['state'], 'failed')
            self.assertEqual(read(root, ANALYSIS)['agencies']['jtwc']['bulletin'], '022')

    def test_index_only_snapshot_upgrades_without_loss(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            for name in (ANALYSIS, FORECAST):
                (root / name).unlink()
            # JTWC down in the first S6 run: nothing to carry, so the block is null for now (11b #2).
            index, transport = self.update(root, dict(tt.cempaka_routes(), **{JTWC_RSS: 500}), NOW + hours(0.5))
            self.assertIsNotNone(index['storms'][0]['summary']['jtwc'])
            analysis = read(root, ANALYSIS)['agencies']
            self.assertIsNone(analysis['jtwc'])
            self.assertIsNotNone(analysis['cwa'])
            # No saved JMA URL yet: the S4 interim applies and the bulletins are read again.
            self.assertIn(tt.JMA_BULLETIN.format('20261111094118'), transport.urls)
            self.assertIsNotNone(analysis['jma'])
            self.update(root, tt.cempaka_routes(), NOW + hours(1))
            self.assertIsNotNone(read(root, ANALYSIS)['agencies']['jtwc'])

    def test_leftover_files_of_an_unlisted_system_are_never_read(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / ANALYSIS).parent.mkdir(parents=True)
            (root / ANALYSIS).write_text(json.dumps(tt.valid_analysis()), encoding='utf-8')
            # No previous index: the system is minted again with the same ID and starts clean.
            self.update(root, tt.cempaka_routes())
            agencies = read(root, ANALYSIS)['agencies']
            self.assertEqual(agencies['jtwc']['past_track'], [])
            self.assertEqual(agencies['jma']['past_track'], [])

    def test_invalid_saved_file_is_treated_as_absent(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            (root / ANALYSIS).write_text('{"schema_version": 1}', encoding='utf-8')
            self.update(root, dict(final_routes(), **{JTWC_RSS: 500}), LATER)
            analysis = read(root, ANALYSIS)['agencies']
            self.assertIsNone(analysis['jtwc'])
            self.assertEqual(analysis['jma']['past_track'], [])

    def test_index_is_written_last(self):
        from unittest import mock
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            before = (root / OFFICIAL_INDEX_PATH).read_bytes()
            order = []
            real = official.atomic_write_json

            def failing(data, path, prefix):
                order.append(Path(path).name)
                if Path(path).name == 'forecast.json':
                    raise OSError('disk full')
                return real(data, path, prefix=prefix)
            with mock.patch.object(official, 'atomic_write_json', failing), self.assertRaises(OSError):
                self.update(root, final_routes(), LATER)
            self.assertEqual(order, ['analysis.json', 'forecast.json'])
            # The caller (checked_update) rolls the prefix back; the index itself was never touched.
            self.assertEqual((root / OFFICIAL_INDEX_PATH).read_bytes(), before)
            order.clear()
            with mock.patch.object(official, 'atomic_write_json',
                                   lambda data, path, prefix: (order.append(Path(path).name), real(data, path, prefix=prefix))[1]):
                self.update(root, final_routes(), LATER)
            self.assertEqual(order[-1], 'index.json')

    def test_storm_file_failing_validation_is_skipped_and_index_still_written(self):
        from unittest import mock
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            saved = (root / FORECAST).read_bytes()
            real = official.build_storm_files

            def broken(*arguments):
                outputs = real(*arguments)
                outputs[FORECAST]['agencies']['jtwc']['points'][0]['valid_time'] = '2000-01-01T00:00:00Z'
                return outputs
            with mock.patch.object(official, 'build_storm_files', broken):
                index, _ = self.update(root, final_routes(), LATER)
            self.assertEqual((root / FORECAST).read_bytes(), saved)
            self.assertEqual(read(root, OFFICIAL_INDEX_PATH), index)
            self.assertEqual(read(root, ANALYSIS)['agencies']['jtwc']['bulletin'], '022')

    def test_files_follow_the_index_when_a_system_ends_and_leaves(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self.update(root, tt.cempaka_routes())
            self.update(root, final_routes(), LATER)
            index, _ = self.update(root, final_routes(), datetime(2026, 11, 11, 21, 0, 1, tzinfo=UTC))
            self.assertEqual(index['storms'][0]['status'], 'ended')
            self.assertTrue((root / ANALYSIS).exists())  # kept during the 48 h retention
            index, _ = self.update(root, final_routes(), datetime(2026, 11, 13, 21, 2, tzinfo=UTC))
            self.assertEqual(index['storms'], [])
            # The task never deletes: removal is the prune step's job (design.md 3.6, S6b).
            self.assertTrue((root / ANALYSIS).exists())


def track(count, start=datetime(2026, 10, 1, tzinfo=UTC), step=3):
    return [{'analysis_time': tt.stamp(start + hours(step * n)), 'lat': 20.0, 'lon': 140.0, 'category': None,
             'max_wind': None, 'pressure_hpa': None} for n in range(count)]


class AccumulationAndSizeTests(unittest.TestCase):
    def detailed(self, when, **extra):
        item = record('jtwc', when=when)
        item['analysis'] = {'fix': {'analysis_time': tt.stamp(when)}}
        item.update(extra)
        return item

    def test_track_holds_saved_points_and_fix_capped_at_160_without_duplicates(self):
        when = datetime(2026, 11, 1, tzinfo=UTC)
        saved = {'past_track': track(159, step=1),
                 'fix': dict(track(1, start=when - hours(2))[0], gust=None, movement=None, radii=[])}
        extra = [track(1, start=when - hours(1))[0], track(1, start=when - hours(2))[0], track(1, start=when)[0]]
        points = official._accumulated(saved, self.detailed(when, extra_points=extra))
        times = [point['analysis_time'] for point in points]
        self.assertEqual(len(points), 160)
        self.assertEqual(times, sorted(set(times)))
        self.assertLess(times[-1], tt.stamp(when))  # never the current fix
        self.assertEqual(times[-1], tt.stamp(when - hours(1)))
        self.assertNotIn(saved['past_track'][0]['analysis_time'], times)  # oldest dropped first

    def test_older_saved_fix_than_new_one_only(self):
        when = datetime(2027, 1, 1, tzinfo=UTC)  # across the new year
        saved = {'past_track': [], 'fix': dict(track(1, start=datetime(2026, 12, 31, 18, tzinfo=UTC))[0])}
        points = official._accumulated(saved, self.detailed(when, extra_points=[]))
        self.assertEqual([p['analysis_time'] for p in points], ['2026-12-31T18:00:00Z'])
        # A re-issued report for the same analysis time adds nothing.
        same = {'past_track': [], 'fix': dict(track(1, start=when)[0])}
        self.assertEqual(official._accumulated(same, self.detailed(when, extra_points=[])), [])

    def outputs(self, ended_count=1, points=160):
        index = validate_official_index(tt.valid_index())
        storms = [index['storms'][0]]
        for number in range(ended_count):
            storm = deepcopy(index['storms'][0])
            storm['cyclone_id'] = f'2026-jma-tc26{40 + number}'
            storm['ids']['jma_tc'] = f'TC26{40 + number}'
            for summary in storm['summary'].values():
                summary['active'] = False
            storm.update(status='ended', ended_at=tt.stamp(datetime(2026, 11, 1, tzinfo=UTC) + hours(24 * number)))
            storms.append(storm)
        index['storms'] = sorted(storms, key=lambda storm: storm['cyclone_id'])
        files = {}
        for storm in index['storms']:
            analysis = tt.valid_analysis()
            analysis['cyclone_id'] = storm['cyclone_id']
            for agency in ('jtwc', 'jma'):
                analysis['agencies'][agency]['past_track'] = track(points, start=datetime(2026, 10, 1, tzinfo=UTC))
            files[official.storm_path(storm['cyclone_id'], 'analysis')] = analysis
        return validate_official_index(index), files

    def test_real_sizes_are_far_below_the_limits(self):
        index, files = self.outputs(ended_count=11)
        total = official._size(index) + sum(official._size(data) for data in files.values())
        self.assertLess(max(official._size(data) for data in files.values()), official.MAX_ANALYSIS_BYTES)
        _, kept = official.limit_sizes(index, files)
        self.assertEqual(len(kept), 12)
        self.assertGreater(total, 0)

    def test_file_limit_halves_tracks_oldest_first(self):
        from unittest import mock
        index, files = self.outputs(ended_count=0)
        path = next(iter(files))
        newest = files[path]['agencies']['jtwc']['past_track'][-1]
        with mock.patch.object(official, 'MAX_ANALYSIS_BYTES', official._size(files[path]) - 1):
            _, kept = official.limit_sizes(index, files)
        self.assertEqual(len(kept[path]['agencies']['jtwc']['past_track']), 80)
        self.assertEqual(kept[path]['agencies']['jtwc']['past_track'][-1], newest)

    def test_prefix_limit_drops_longest_ended_first_then_halves_then_fails(self):
        from unittest import mock
        index, files = self.outputs(ended_count=2)
        total = official._size(index) + sum(official._size(data) for data in files.values())
        with mock.patch.object(official, 'MAX_OFFICIAL_BYTES', total - 1):
            kept_index, kept = official.limit_sizes(deepcopy(index), deepcopy(files))
        self.assertEqual([s['cyclone_id'] for s in kept_index['storms']], ['2026-jma-tc2638', '2026-jma-tc2641'])
        validate_official_index(kept_index)  # status and counts stay consistent
        self.assertNotIn(official.storm_path('2026-jma-tc2640', 'analysis'), kept)
        active_only = {official.storm_path('2026-jma-tc2638', 'analysis'): files[official.storm_path('2026-jma-tc2638', 'analysis')]}
        small_index = deepcopy(index)
        small_index['storms'] = [s for s in small_index['storms'] if s['status'] == 'active']
        size = official._size(small_index) + official._size(next(iter(active_only.values())))
        with mock.patch.object(official, 'MAX_OFFICIAL_BYTES', size - 1):
            _, kept = official.limit_sizes(deepcopy(small_index), deepcopy(active_only))
        self.assertLess(len(next(iter(kept.values()))['agencies']['jtwc']['past_track']), 160)
        with mock.patch.object(official, 'MAX_OFFICIAL_BYTES', 10), self.assertRaises(ValueError):
            official.limit_sizes(deepcopy(small_index), deepcopy(active_only))

    def test_known_jma_uses_the_saved_bulletin_only_when_it_is_the_summarised_one(self):
        previous = validate_official_index(tt.valid_index())
        files = {'2026-jma-tc2638': {'analysis': tt.valid_analysis(), 'forecast': None}}
        item, = official._known_jma(previous, files)
        self.assertEqual(item['product_url'], tt.JMA_BULLETIN.format('20261111094118'))
        self.assertEqual(item['feed_time'], datetime(2026, 11, 11, 9, 41, 18, tzinfo=UTC))
        self.assertEqual(item['issued_at'], datetime(2026, 11, 11, 9, 45, tzinfo=UTC))
        files['2026-jma-tc2638']['analysis']['agencies']['jma']['fix']['analysis_time'] = '2026-11-11T06:00:00Z'
        item, = official._known_jma(previous, files)
        self.assertNotIn('product_url', item)
        item, = official._known_jma(previous)
        self.assertNotIn('product_url', item)

    def test_forecast_times_across_the_new_year_and_taiwan_midnight(self):
        from src.services.tropical_jtwc import parse_tcw
        text = fixture('jtwc_wp3126_warning21.tcw').decode('latin-1')
        text = text.replace('WTPN51 PGTW 110900', 'WTPN51 PGTW 311500').replace('261111073859', '261231134500')
        text = text.replace('2026111106 31W', '2026123112 31W')
        record_ = parse_tcw(text.encode('latin-1'), JTWC_PRODUCT.format('wp3126.tcw'), final=False)
        self.assertEqual(record_['analysis']['issued_at'], '2026-12-31T15:00:00Z')
        self.assertEqual(record_['season'], 2026)  # from the product name, not the date
        # 12 h after 12-31 12Z is 01-01 00Z, which is 08:00 in Taiwan; 24 h is 01-01 12Z (20:00 Taiwan).
        self.assertEqual([p['valid_time'] for p in record_['forecast']['points']],
                         ['2027-01-01T00:00:00Z', '2027-01-01T12:00:00Z'])


if __name__ == '__main__':
    unittest.main()
