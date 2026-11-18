"""tropical_models (S8): contract, parsers, task, prune, pipeline and shared-module invariants.

Real NOAA/ECMWF samples (fixtures/tropical/README.md) and synthetic cases; fixed
instants; fake transport; the network is blocked (design.md 9.2, 9.3).
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tropical_testing as tt
from tropical_testing import FakeResponse, FakeTransport, fixture, quiet_policy, record, result

from src import tropical_models as models
from src import tropical_official as official
from src.http_client import (DEFAULT_LIMITS, HttpPolicy, SourceBudgetExceeded, source_limits, source_name)
from src.publication import atomic_write_compact_json, atomic_write_json
from src.services import tropical_ecmwf, tropical_noaa
from src.snapshot_runner import _prune_tropical, belongs
from src.snapshots import allowed_path, validate_resource
from src.tropical_contract import (MODELS_INDEX_PATH, OFFICIAL_INDEX_PATH, validate_models_file,
                                   validate_models_index, validate_official_index)

UTC = timezone.utc
NOW_NOAA = datetime(2026, 11, 11, 11, 30, tzinfo=UTC)  # the 06Z ATCF samples are due
NOW_ECMWF = datetime(2026, 11, 10, 19, 0, tzinfo=UTC)  # the 12Z BUFR samples are due


def setUpModule():
    tt.block_network()


def tearDownModule():
    tt.unblock_network()


def official_index(*records, now, previous=None):
    by = {agency: [item for item in records if item['agency'] == agency] for agency in ('cwa', 'jma', 'jtwc')}
    index = official.build_index(previous, tt.results(cwa=result(*by['cwa']), jma=result(*by['jma']),
                                                   jtwc=result(*by['jtwc'])), now)
    return validate_official_index(index)


def cempaka(when, lat=29.1, lon=150.2, **options):
    return record('jtwc', when=when, name='CEMPAKA', lat=lat, lon=lon, **options)


def pena(when, lat=10.0, lon=-166.3, **options):
    return record('jtwc', when=when, name='PENA', number='04C', lat=lat, lon=lon, origin_basin='CP', **options)


def routes_at(now, noaa=404, ecmwf=404, tcvitals=False):
    """Every product the task may request at ``now``; ``b''`` is a published file with no system."""
    routes = {}
    for model in ('gfs', 'aigfs', 'ifs', 'aifs'):
        module = tropical_noaa if models.SOURCE_OF[model] == 'noaa' else tropical_ecmwf
        for moment in models.due_cycles(model, now):
            routes[module.track_url(model, moment.strftime('%Y%m%d%H'))] = noaa if module is tropical_noaa else ecmwf
    if tcvitals:
        routes[tropical_noaa.tcvitals_url(models.due_cycles('gfs', now)[-1].strftime('%Y%m%d%H'))] = 404
    return routes


def all_404(now, tcvitals=False):
    return routes_at(now, tcvitals=tcvitals)


def noaa_routes(now=NOW_NOAA, **extra):
    routes = routes_at(now, noaa=b'', **extra)
    routes[tropical_noaa.track_url('gfs', '2026111106')] = fixture('noaa_avno_2026111106.txt')
    routes[tropical_noaa.track_url('aigfs', '2026111106')] = fixture('noaa_agfs_2026111106.txt')
    return routes


def ecmwf_routes(now=NOW_ECMWF):
    routes = all_404(now)
    routes[tropical_ecmwf.track_url('ifs', '2026111012')] = fixture('ecmwf_ifs_2026111012_oper.bufr')
    routes[tropical_ecmwf.track_url('aifs', '2026111012')] = fixture('ecmwf_aifs_2026111012_oper.bufr')
    return routes


def write_json(root, name, data):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(root, routes, now):
    transport = FakeTransport(routes)
    index = models.update_tropical_models(root, now=now, transport=transport, wait=lambda s: None,
                                          clock=lambda: 0.0, policy=quiet_policy())
    return index, transport


def cycle_file(cyclone_id='2026-jtwc-31w', cycle='2026111106', **models_):
    track = [[0, 28.8, 149.8, 988, 62], [6, 29.7, 153.2, 989, 82]]
    body = models_ or {'gfs': {'provider': 'NOAA', 'source_id': 'WP31', 'match': 'jtwc_id', 'wind_unit': 'kt',
                               'track': track}}
    return {'schema_version': 1, 'cyclone_id': cyclone_id, 'cycle': cycle,
            'init_time': datetime.strptime(cycle, '%Y%m%d%H').strftime('%Y-%m-%dT%H:00:00Z'),
            'fetched_at': '2026-11-11T11:30:00Z', 'models': body}


def models_index(storms=None, checked=None, basis=None):
    return {'schema_version': 1, 'fetched_at': '2026-11-11T11:30:00Z',
            'sources': {'noaa': {'state': 'ok', 'error_code': None}, 'ecmwf': {'state': 'idle', 'error_code': None}},
            'match_basis': basis or [], 'checked': checked or {},
            'storms': storms if storms is not None else {
                '2026-jtwc-31w': {'bridge': {'jtwc': None}, 'cycles': [{'cycle': '2026111106', 'models': ['gfs']}]}}}


class ContractTests(unittest.TestCase):
    def test_valid_files_pass_and_are_allowed_but_not_required(self):
        self.assertEqual(validate_models_index(models_index()), models_index())
        validate_models_index(models.empty_index(NOW_NOAA))
        path = 'tropical/models/storms/2026-jtwc-31w/2026111106.json'
        validate_models_file(path, cycle_file())
        validate_resource(MODELS_INDEX_PATH, models_index())
        validate_resource(path, cycle_file())
        self.assertTrue(allowed_path(MODELS_INDEX_PATH) and allowed_path(path))
        for bad in ('tropical/models/storms/2026-jtwc-31w/2026111103.json', 'tropical/models/other.json',
                    'tropical/models/storms/2026-jtwc-31w/x/2026111106.json'):
            self.assertFalse(allowed_path(bad), bad)
        from src.snapshots import REQUIRED
        self.assertFalse(any(name.startswith('tropical/') for name in REQUIRED))
        self.assertTrue(belongs(MODELS_INDEX_PATH, 'tropical_models'))
        self.assertFalse(belongs(MODELS_INDEX_PATH, 'tropical_official'))

    def test_each_violation_is_rejected_with_value_error_only(self):
        path = 'tropical/models/storms/2026-jtwc-31w/2026111106.json'
        point = [6, 29.7, 153.2, 989, 82]

        def with_track(*points):
            data = cycle_file()
            data['models']['gfs']['track'] = [list(p) for p in points]
            return data
        bad_files = {
            'other id': dict(cycle_file(), cyclone_id='2026-jtwc-32w'),
            'other cycle': dict(cycle_file(), cycle='2026111100'),
            'init mismatch': dict(cycle_file(), init_time='2026-11-11T00:00:00Z'),
            'no models': dict(cycle_file(), models={}),
            'unknown model': cycle_file(gefs={}),
            'wrong provider': cycle_file(gfs={'provider': 'ECMWF', 'source_id': 'WP31', 'match': 'jtwc_id',
                                              'wind_unit': 'kt', 'track': [point]}),
            'wrong unit': cycle_file(ifs={'provider': 'ECMWF', 'source_id': '38W', 'match': 'name',
                                          'wind_unit': 'kt', 'track': [point]}),
            'noaa name match': cycle_file(gfs={'provider': 'NOAA', 'source_id': 'WP31', 'match': 'name',
                                               'wind_unit': 'kt', 'track': [point]}),
            'tau not multiple of 6': with_track([3, 29.7, 153.2, 989, 82]),
            'tau decreasing': with_track(point, [0, 28.8, 149.8, 988, 62]),
            'tau duplicated': with_track(point, point),
            'tau as float': with_track([6.0, 29.7, 153.2, 989, 82]),
            'tau as bool': with_track([True, 29.7, 153.2, 989, 82]),
            'lon 180': with_track([6, 29.7, 180.0, 989, 82]),
            'null position': with_track([6, None, 153.2, 989, 82]),
            'pressure out of range': with_track([6, 29.7, 153.2, 700, 82]),
            'nan wind': with_track([6, 29.7, 153.2, 989, float('nan')]),
            'short point': with_track([6, 29.7, 153.2]),
            'too many points': with_track(*[[6 * i, 20.0, 140.0, None, None] for i in range(82)]),
            'extra field': dict(cycle_file(), note='x'),
        }
        for label, data in bad_files.items():
            with self.subTest(label), self.assertRaises(ValueError):
                validate_models_file(path, data)
        index = models_index()
        bad_indexes = {
            'unknown source state': {**index, 'sources': {**index['sources'], 'noaa': {'state': 'busy', 'error_code': None}}},
            'failed without code': {**index, 'sources': {**index['sources'], 'noaa': {'state': 'failed', 'error_code': None}}},
            'ok with code': {**index, 'sources': {**index['sources'], 'noaa': {'state': 'ok', 'error_code': 'timeout'}}},
            'unsorted checked models': {**index, 'checked': {'2026111106': ['gfs', 'aigfs']}},
            'bad cycle key': {**index, 'checked': {'2026111103': ['gfs']}},
            'nine checked cycles': {**index, 'checked': {f'202611{d:02d}00': ['gfs'] for d in range(1, 10)}},
            'five cycles': {**index, 'storms': {'2026-jtwc-31w': {'bridge': {'jtwc': None}, 'cycles': [
                {'cycle': f'202611{d:02d}00', 'models': ['gfs']} for d in range(1, 6)]}}},
            'cycles not increasing': {**index, 'storms': {'2026-jtwc-31w': {'bridge': {'jtwc': None}, 'cycles': [
                {'cycle': '2026111106', 'models': ['gfs']}, {'cycle': '2026111100', 'models': ['gfs']}]}}},
            'empty models': {**index, 'storms': {'2026-jtwc-31w': {'bridge': {'jtwc': None}, 'cycles': [
                {'cycle': '2026111106', 'models': []}]}}},
            'bad bridge': {**index, 'storms': {'2026-jtwc-31w': {'bridge': {'jtwc': 'WP31'}, 'cycles': [
                {'cycle': '2026111106', 'models': ['gfs']}]}}},
            'unsorted basis': {**index, 'match_basis': ['2026-jtwc-32w||', '2026-jtwc-31w|31W|CEMPAKA']},
            'basis with url': {**index, 'match_basis': ['2026-jtwc-31w|31W|http://x']},
            'missing field': {key: value for key, value in index.items() if key != 'checked'},
        }
        for label, data in bad_indexes.items():
            with self.subTest(label), self.assertRaises(ValueError):
                validate_models_index(data)
        junk = (None, True, 7, 'x', [], {}, [None], {'a': None}, [[1, 2]], float('inf'))
        for value in junk:
            for key in index:
                if (key, json.dumps(value)) in (('checked', '{}'), ('storms', '{}'), ('match_basis', '[]')):
                    continue  # valid: nothing checked / no system / no active system
                with self.assertRaises(ValueError):
                    validate_models_index({**index, key: value})
            for key in cycle_file():
                with self.assertRaises(ValueError):
                    validate_models_file(path, {**cycle_file(), key: value})


class SharedModuleTests(unittest.TestCase):
    """Changes to shared files must not alter existing behaviour (design.md 9.4 S8)."""

    def test_indented_writer_output_is_unchanged_and_compact_writer_is_compact(self):
        data = {'title': '雷達回波', 'items': [1, 2.5, None], 'nested': {'a': True}}
        with tempfile.TemporaryDirectory() as directory:
            atomic_write_json(data, Path(directory) / 'a.json')
            self.assertEqual((Path(directory) / 'a.json').read_bytes(),
                             (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            self.assertEqual(atomic_write_compact_json(data, Path(directory) / 'b.json'), data)
            self.assertEqual((Path(directory) / 'b.json').read_bytes(),
                             (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8'))
            with self.assertRaises(ValueError):
                atomic_write_compact_json({'x': float('nan')}, Path(directory) / 'c.json')
            self.assertFalse((Path(directory) / 'c.json').exists())
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['a.json', 'b.json'])

    def test_existing_sources_keep_their_names_and_limits(self):
        def old_limits(name):  # the expressions http_client used before S8
            return (600 if name == 'cwa' else 80, 240 if name == 'cwa' else 90)
        urls = {'https://www.cwa.gov.tw/x': 'cwa', 'https://opendata.cwa.gov.tw/x': 'cwa',
                'https://www.data.jma.go.jp/x': 'jma', 'https://www.jma.go.jp/x': 'jma',
                'https://www.kma.go.kr/x': 'kma', 'https://www.weather.go.kr/x': 'kma',
                'https://tropic.ssec.wisc.edu/x': 'cimss', 'https://nsidc.org/x': 'nsidc',
                'https://www.metoc.navy.mil/x': 'jtwc', 'https://example.org/x': 'example.org',
                'https://www.nhc.noaa.gov/x': 'www.nhc.noaa.gov', 'https://apps.ecmwf.int/x': 'apps.ecmwf.int'}
        for url, name in urls.items():
            self.assertEqual(source_name(url), name, url)
            self.assertEqual(source_limits(name), old_limits(name), url)
        self.assertEqual(DEFAULT_LIMITS, (80, 90))
        self.assertEqual(source_name('https://nomads.ncep.noaa.gov/pub/x'), 'noaa')
        self.assertEqual(source_name('https://data.ecmwf.int/forecasts/x'), 'ecmwf')
        self.assertEqual(source_limits('noaa'), (200, 420))
        self.assertEqual(source_limits('ecmwf'), (40, 240))

    def test_request_and_time_budgets_per_source(self):
        cases = {'https://www.cwa.gov.tw/x': (600, 240), 'https://www.jma.go.jp/x': (80, 90),
                 'https://nomads.ncep.noaa.gov/x': (200, 420), 'https://data.ecmwf.int/x': (40, 240),
                 'https://example.org/x': (80, 90)}
        for url, (count, seconds) in cases.items():
            with self.subTest(url):
                policy = HttpPolicy(clock=lambda: 0.0)
                for _ in range(count):
                    policy.reserve(url)
                with self.assertRaises(SourceBudgetExceeded):
                    policy.reserve(url)
                now = [0.0]
                policy = HttpPolicy(clock=lambda: now[0])
                policy.reserve(url)
                now[0] = seconds - 0.5
                policy.reserve(url)
                now[0] = seconds
                with self.assertRaises(SourceBudgetExceeded):
                    policy.reserve(url)
        # Explicit overrides still win over the table.
        policy = HttpPolicy(max_requests=1, clock=lambda: 0.0)
        policy.reserve('https://nomads.ncep.noaa.gov/x')
        with self.assertRaises(SourceBudgetExceeded):
            policy.reserve('https://nomads.ncep.noaa.gov/y')


class NoaaParserTests(unittest.TestCase):
    def test_real_atcf_lines_merge_into_points(self):
        tracks = tropical_noaa.parse_atcf(fixture('noaa_avno_2026111106.txt'), 'gfs', '2026111106')
        self.assertEqual(set(tracks), {('WP', '31'), ('CP', '04')})
        wp = tracks[('WP', '31')]
        self.assertEqual(wp[0], [0, 28.8, 149.8, 988, 62])
        self.assertEqual(wp[1], [6, 29.7, 153.2, 989, 82])
        self.assertEqual([p[0] for p in wp], sorted({p[0] for p in wp}))
        self.assertEqual(tracks[('CP', '04')][0], [0, 10.7, -166.6, 1003, 39])
        aigfs = tropical_noaa.parse_atcf(fixture('noaa_agfs_2026111106.txt'), 'aigfs', '2026111106')
        self.assertEqual(aigfs[('WP', '31')][0][:3], [0, 28.8, 149.8])
        # Another model code or cycle is not read from the same file.
        self.assertEqual(tropical_noaa.parse_atcf(fixture('noaa_avno_2026111106.txt'), 'aigfs', '2026111106'), {})
        self.assertEqual(tropical_noaa.parse_atcf(fixture('noaa_avno_2026111106.txt'), 'gfs', '2026111100'), {})

    def test_values_basins_and_broken_lines(self):
        line = 'WP, 07, 2026123118, 03, AVNO, {tau}, 105N, 1800E, {wind}, {pres}, XX,  34, NEQ, 0, 0, 0, 0\n'
        body = ''.join(line.format(tau=tau, wind=wind, pres=pres) for tau, wind, pres in
                       ((0, 0, 0), (3, 40, 990), (6, 250, 700), (486, 30, 1000), (12, 35, 1001))).encode()
        tracks = tropical_noaa.parse_atcf(body, 'gfs', '2026123118')
        self.assertEqual(tracks[('WP', '07')], [[0, 10.5, -180.0, None, None], [6, 10.5, -180.0, None, None],
                                                 [12, 10.5, -180.0, 1001, 35]])
        self.assertEqual(tropical_noaa.jtwc_style('WP', '07'), '07W')
        self.assertEqual(tropical_noaa.jtwc_style('CP', '04'), '04C')
        self.assertEqual(tropical_noaa.jtwc_style('EP', '12'), '12E')
        for basin in ('SI', 'SP', 'IO', 'AL', 'SH'):
            self.assertIsNone(tropical_noaa.jtwc_style(basin, '03'))
        conflict = (line.format(tau=0, wind=30, pres=1000)
                    + line.format(tau=0, wind=30, pres=1000).replace('105N', '106N')).encode()
        for bad in (conflict, b'WP, 07, 2026123118\n', line.format(tau=0, wind='x', pres=1).encode(),
                    line.format(tau=0, wind=3, pres=1).replace('105N', '105Q').encode(), b'\xff\xfe'):
            with self.assertRaises(ValueError):
                tropical_noaa.parse_atcf(bad, 'gfs', '2026123118')

    def test_tcvitals_and_bridge_window(self):
        entries = tropical_noaa.parse_tcvitals(fixture('noaa_tcvitals_2026111118.txt'))
        self.assertEqual([(e['id'], e['name'], e['time'].isoformat(), e['lat'], e['lon']) for e in entries],
                         [('04C', 'PENA', '2026-11-11T18:00:00+00:00', 9.9, -168.7),
                          ('31W', 'CEMPAKA', '2026-11-11T12:00:00+00:00', 30.2, 154.1)])
        storm = {'name': 'CEMPAKA'}
        self.assertEqual(models.bridge_from_tcvitals(entries, storm, '2026111118'), '31W')  # 6 h: inside
        self.assertIsNone(models.bridge_from_tcvitals(entries, storm, '2026111200'))  # 12 h: too old
        self.assertIsNone(models.bridge_from_tcvitals(entries, {'name': 'OTHER'}, '2026111118'))
        twice = entries + [dict(entries[1], id='32W')]
        self.assertIsNone(models.bridge_from_tcvitals(twice, storm, '2026111118'))


class EcmwfDecoderTests(unittest.TestCase):
    def test_real_deterministic_files_value_by_value(self):
        ifs = {t['id']: t for t in tropical_ecmwf.decode_tracks(fixture('ecmwf_ifs_2026111012_oper.bufr'))}
        self.assertEqual(set(ifs), {'04C', '38W'})  # 70+ generated systems dropped
        cempaka = ifs['38W']
        self.assertEqual((cempaka['name'], cempaka['member'], cempaka['init_time']),
                         ('CEMPAKA', 51, datetime(2026, 11, 10, 12, tzinfo=UTC)))
        self.assertEqual(cempaka['analysis'], (26.3, 142.0))
        self.assertEqual(cempaka['track'][:2], [[0, 25.9, 142.0, 988.0, 29.8], [6, 26.6, 144.2, 980.0, 34.0]])
        self.assertEqual(cempaka['track'][-1], [36, 31.1, 159.0, 999.0, 35.0])
        self.assertEqual(len(ifs['04C']['track']), 13)
        self.assertEqual(ifs['04C']['track'][-1], [84, 11.5, 177.3, 1009.0, 13.4])  # crossed 180 deg
        aifs = {t['id']: t for t in tropical_ecmwf.decode_tracks(fixture('ecmwf_aifs_2026111012_oper.bufr'))}
        self.assertEqual(aifs['38W']['member'], 52)
        self.assertEqual(aifs['04C']['track'][0], [0, 11.4, -163.7, 1004.0, 14.9])

    def test_systems_without_forecast_steps_and_generated_systems_are_dropped(self):
        # 11/11 18Z IFS: CEMPAKA and PENA appear with an analysis only; 70L/70B/70P are generated.
        self.assertEqual(tropical_ecmwf.decode_tracks(fixture('ecmwf_ifs_2026111118_oper.bufr')), [])

    def test_neutral_filters(self):
        base = {'id': '05W', 'name': '05W', 'member': 51, 'type': 0, 'time': [2026, 11, 10, 12, 0],
                'analysis': (20.0, 130.0), 'own': None, 'pressure0': 100000.0, 'wind0': 20.0,
                'steps': [{'tau': 6, 'centre': (20.5, 131.0), 'pressure': 99900.0, 'wind': 21.0}]}
        unnamed = tropical_ecmwf.neutral_track(base)
        self.assertIsNone(unnamed['name'])  # the name repeats the identifier
        self.assertEqual(unnamed['track'], [[0, 20.0, 130.0, 1000.0, 20.0], [6, 20.5, 131.0, 999.0, 21.0]])
        self.assertIsNone(tropical_ecmwf.neutral_track(dict(base, id='70W')))
        self.assertIsNone(tropical_ecmwf.neutral_track(dict(base, analysis=None)))
        self.assertIsNone(tropical_ecmwf.neutral_track(dict(base, steps=[])))
        self.assertIsNone(tropical_ecmwf.neutral_track(dict(base, steps=[dict(base['steps'][0], centre=None)])))
        self.assertIsNone(tropical_ecmwf.neutral_track(dict(base, time=[2026, 11, 10, None, 0])))
        own = tropical_ecmwf.neutral_track(dict(base, own=(19.9, 129.9)))
        self.assertEqual(own['track'][0][:3], [0, 19.9, 129.9])
        bad = tropical_ecmwf.neutral_track(dict(base, pressure0=10.0, wind0=500.0))
        self.assertEqual(bad['track'][0][3:], [None, None])
        with self.assertRaises(ValueError):
            tropical_ecmwf.decode_tracks(b'BUFR not really')
        self.assertEqual(tropical_ecmwf.step_hours('ifs', '2026111106'), 144)
        self.assertEqual(tropical_ecmwf.step_hours('ifs', '2026111112'), 360)
        self.assertEqual(tropical_ecmwf.step_hours('aifs', '2026111118'), 360)
        self.assertEqual(tropical_ecmwf.track_url('aifs', '2026111018'),
                         'https://data.ecmwf.int/forecasts/20261110/18z/aifs-single/0p25/oper/'
                         '20261110180000-360h-oper-tf.bufr')


class CycleTimingTests(unittest.TestCase):
    def test_due_cycles_cross_day_month_and_year(self):
        self.assertEqual(models.due_cycles('gfs', datetime(2027, 1, 1, 4, 29, tzinfo=UTC))[-1],
                         datetime(2026, 12, 31, 18, tzinfo=UTC))
        self.assertEqual(models.due_cycles('gfs', datetime(2027, 1, 1, 4, 30, tzinfo=UTC))[-1],
                         datetime(2027, 1, 1, 0, tzinfo=UTC))
        self.assertEqual(models.due_cycles('ifs', datetime(2026, 12, 1, 5, 59, tzinfo=UTC)),
                         [datetime(2026, 11, 30, h, tzinfo=UTC) for h in (0, 6, 12, 18)])
        self.assertEqual(tropical_noaa.track_url('aigfs', '2026123118'),
                         'https://nomads.ncep.noaa.gov/pub/data/nccf/com/ens_tracker/prod/aigfs.20261231/18/'
                         'tctrack/agfs.t18z.cyclone.trackatcfunix')


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def official(self, *records, now):
        write_json(self.root, OFFICIAL_INDEX_PATH, official_index(*records, now=now))

    def saved(self, name):
        return json.loads((self.root / name).read_bytes())

    def test_noaa_tracks_match_by_jtwc_number_and_are_written_compact(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.official(cempaka(t), pena(t), now=NOW_NOAA)
        index, transport = run(self.root, noaa_routes(), NOW_NOAA)
        self.assertEqual(set(transport.urls), set(noaa_routes()))  # nothing else (no listing, no HTML)
        self.assertEqual(len(transport.urls), 16)
        self.assertTrue(all(options['headers']['User-Agent'].startswith('weather-integration-static/')
                            for _, options in transport.calls))
        self.assertEqual(index['sources']['noaa'], {'state': 'ok', 'error_code': None})
        # Every ECMWF product of this run is overdue and missing: the source is failed.
        self.assertEqual(index['sources']['ecmwf'], {'state': 'failed', 'error_code': 'http_error'})
        self.assertEqual(index['match_basis'], ['2026-jtwc-04c|04C|PENA', '2026-jtwc-31w|31W|CEMPAKA'])
        self.assertEqual(index['checked'], {cycle: ['aigfs', 'gfs'] for cycle in
                                            ('2026111012', '2026111018', '2026111100', '2026111106')})
        self.assertEqual(index['storms']['2026-jtwc-31w'],
                         {'bridge': {'jtwc': None}, 'cycles': [{'cycle': '2026111106', 'models': ['aigfs', 'gfs']}]})
        name = 'tropical/models/storms/2026-jtwc-31w/2026111106.json'
        raw = (self.root / name).read_bytes()
        data = json.loads(raw)
        self.assertEqual(raw, (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
        self.assertEqual(data['models']['gfs']['source_id'], 'WP31')
        self.assertEqual(data['models']['gfs']['match'], 'jtwc_id')
        self.assertEqual(data['models']['gfs']['track'][0], [0, 28.8, 149.8, 988, 62])
        self.assertEqual(self.saved('tropical/models/storms/2026-jtwc-04c/2026111106.json')['models']['aigfs']['source_id'], 'CP04')
        self.assertEqual(self.saved(MODELS_INDEX_PATH), index)
        self.assertIn(b'\n  "sources"', (self.root / MODELS_INDEX_PATH).read_bytes())  # index keeps indent 2
        # Second run in the same hour: checked combinations are not requested again.
        index, again = run(self.root, noaa_routes(), NOW_NOAA)
        self.assertFalse(any('nomads' in url for url in again.urls))
        self.assertEqual(len(again.urls), 8)
        self.assertEqual(index['sources']['noaa'], {'state': 'idle', 'error_code': None})

    def test_ecmwf_tracks_match_by_name_and_merge_into_the_cycle_file(self):
        t = datetime(2026, 11, 10, 18, tzinfo=UTC)
        self.official(cempaka(t, lat=26.9, lon=144.3), pena(t, lat=11.2, lon=-165.0), now=NOW_ECMWF)
        routes = ecmwf_routes()
        routes[tropical_noaa.track_url('gfs', '2026111012')] = fixture('noaa_avno_2026111106.txt').replace(
            b'2026111106', b'2026111012')
        index, _ = run(self.root, routes, NOW_ECMWF)
        self.assertEqual(index['sources']['ecmwf'], {'state': 'ok', 'error_code': None})
        self.assertEqual(index['storms']['2026-jtwc-31w']['cycles'],
                         [{'cycle': '2026111012', 'models': ['aifs', 'gfs', 'ifs']}])
        data = self.saved('tropical/models/storms/2026-jtwc-31w/2026111012.json')
        self.assertEqual(list(data['models']), ['aifs', 'gfs', 'ifs'])
        self.assertEqual({k: (v['provider'], v['source_id'], v['match'], v['wind_unit'])
                          for k, v in data['models'].items()},
                         {'aifs': ('ECMWF', '38W', 'name', 'm/s'), 'gfs': ('NOAA', 'WP31', 'jtwc_id', 'kt'),
                          'ifs': ('ECMWF', '38W', 'name', 'm/s')})
        self.assertEqual(data['models']['ifs']['track'][0], [0, 25.9, 142.0, 988.0, 29.8])
        self.assertEqual(len(self.saved('tropical/models/storms/2026-jtwc-04c/2026111012.json')['models']), 3)
        # A later run adds AIGFS to the same file and keeps the earlier models (11e E12).
        later = NOW_ECMWF + timedelta(hours=1)
        routes = all_404(later)
        routes[tropical_noaa.track_url('aigfs', '2026111012')] = fixture('noaa_agfs_2026111106.txt').replace(
            b'2026111106', b'2026111012')
        index, transport = run(self.root, routes, later)
        self.assertNotIn(tropical_ecmwf.track_url('ifs', '2026111012'), transport.urls)
        self.assertEqual(index['storms']['2026-jtwc-31w']['cycles'][0]['models'], ['aifs', 'aigfs', 'gfs', 'ifs'])
        self.assertEqual(len(self.saved('tropical/models/storms/2026-jtwc-31w/2026111012.json')['models']), 4)

    def test_ecmwf_name_far_from_the_official_position_does_not_match(self):
        t = datetime(2026, 11, 10, 18, tzinfo=UTC)
        self.official(cempaka(t, lat=35.0, lon=144.3), now=NOW_ECMWF)  # about 900 km away
        index, _ = run(self.root, ecmwf_routes(), NOW_ECMWF)
        self.assertEqual(index['storms'], {})
        self.assertEqual(index['checked']['2026111012'], ['aifs', 'ifs'])

    def test_not_published_is_not_a_failure_until_overdue(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        now = datetime(2026, 11, 11, 10, 45, tzinfo=UTC)
        index = official_index(cempaka(t), now=now)
        active = [storm for storm in index['storms'] if storm['status'] == 'active']
        previous = models.empty_index(now)
        previous['match_basis'] = models.match_basis(active, {storm['cyclone_id']: None for storm in active})
        for model in models.MODELS:
            for moment in models.due_cycles(model, now)[:-1]:
                cycle = moment.strftime('%Y%m%d%H')
                previous['checked'][cycle] = sorted(set(previous['checked'].get(cycle, [])) | {model})
        asked = []
        result_index, outputs = models.run_models(index, previous, {}, {}, now,
                                                  lambda url: asked.append(url) or (403, b''))
        # Only the newest cycle of each model is asked and none is overdue yet: both sources ok.
        self.assertEqual(len(asked), 4)
        self.assertEqual(result_index['sources'], {s: {'state': 'ok', 'error_code': None} for s in ('noaa', 'ecmwf')})
        self.assertEqual(result_index['checked'], previous['checked'])
        self.assertEqual(outputs, {})
        # Without the earlier results every source also asks overdue cycles: all 404 -> failed.
        with self.assertRaises(models.AllSourcesFailed):
            models.run_models(index, None, {}, {}, now, lambda url: (404, b''))
        # Overdue 404s next to a published file do not fail the source (5.4).
        mixed = routes_at(now, noaa=404, ecmwf=b'')
        mixed[tropical_noaa.track_url('gfs', '2026111100')] = b''
        result_index, _ = models.run_models(
            index, None, {}, {}, now,
            lambda url: (mixed[url], b'') if isinstance(mixed[url], int) else (200, mixed[url]))
        self.assertEqual(result_index['sources']['noaa']['state'], 'ok')

    def test_abandoned_cycles_are_marked_checked_without_a_request(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.official(cempaka(t), now=NOW_NOAA)
        index, transport = run(self.root, routes_at(NOW_NOAA, noaa=404, ecmwf=b''), NOW_NOAA)
        abandoned = '2026111012'  # 23.5 h old at 11:30 for NOAA: still tried
        self.assertIn(tropical_noaa.track_url('gfs', abandoned), transport.urls)
        later = NOW_NOAA + timedelta(hours=1)  # 24.5 h: given up
        index, transport = run(self.root, routes_at(later, noaa=404, ecmwf=b''), later)
        self.assertNotIn(tropical_noaa.track_url('gfs', abandoned), transport.urls)
        self.assertIn('gfs', index['checked'].get(abandoned, []))

    def test_source_failures_and_task_failure(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.official(cempaka(t), now=NOW_NOAA)
        for failure in (500, requests_error(), FakeResponse(429, headers={'Retry-After': '120'})):
            with self.subTest(repr(failure)):
                routes = {url: failure for url in all_404(NOW_NOAA)}
                with self.assertRaises(models.AllSourcesFailed):
                    run(self.root, routes, NOW_NOAA)
                self.assertFalse((self.root / 'tropical/models').exists())
        routes = noaa_routes()
        for url in list(routes):
            if 'ecmwf' in url:
                routes[url] = 503
        index, _ = run(self.root, routes, NOW_NOAA)
        self.assertEqual(index['sources']['ecmwf'], {'state': 'failed', 'error_code': 'network_error'})
        self.assertEqual(index['sources']['noaa']['state'], 'ok')
        broken = routes_at(NOW_NOAA, noaa=b'', ecmwf=b'')
        broken[tropical_noaa.track_url('gfs', '2026111106')] = b'WP, 31\n'
        index = models.run_models(official_index(cempaka(t), now=NOW_NOAA), None, {}, {}, NOW_NOAA,
                                  lambda url: (200, broken[url]) if not isinstance(broken[url], int)
                                  else (broken[url], b''))[0]
        self.assertEqual(index['sources']['noaa'], {'state': 'failed', 'error_code': 'parse_error'})
        self.assertNotIn('gfs', index['checked']['2026111106'])  # the broken file is retried
        self.assertIn('aigfs', index['checked']['2026111106'])

    def test_a_hanging_source_costs_one_request_with_its_retries(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.official(cempaka(t), now=NOW_NOAA)
        routes = {url: requests_error() for url in all_404(NOW_NOAA)}
        with self.assertRaises(models.AllSourcesFailed):
            _, transport = run(self.root, routes, NOW_NOAA)
        transport = FakeTransport(routes)
        with self.assertRaises(models.AllSourcesFailed):
            models.update_tropical_models(self.root, now=NOW_NOAA, transport=transport, wait=lambda s: None,
                                          clock=lambda: 0.0, policy=quiet_policy())
        # http_client tries each request 3 times; then the source is skipped (11e E13).
        self.assertEqual(len(transport.urls), 6)
        self.assertEqual(len({url for url in transport.urls}), 2)
        # A failing ECMWF does not stop NOAA, and NOAA still answers every cycle.
        routes = noaa_routes()
        for url in routes:
            if 'ecmwf' in url:
                routes[url] = requests_error()
        transport = FakeTransport(routes)
        index = models.update_tropical_models(self.root, now=NOW_NOAA, transport=transport, wait=lambda s: None,
                                              clock=lambda: 0.0, policy=quiet_policy())
        self.assertEqual(sum('nomads' in url for url in transport.urls), 8)
        self.assertEqual(sum('ecmwf' in url for url in transport.urls), 3)
        self.assertEqual(index['sources']['ecmwf'], {'state': 'failed', 'error_code': 'network_error'})

    def test_invalid_official_index_changes_nothing(self):
        index, transport = run(self.root, {}, NOW_NOAA)
        self.assertEqual(transport.urls, [])
        self.assertEqual(index, models.empty_index(NOW_NOAA))
        before = (self.root / MODELS_INDEX_PATH).read_bytes()
        write_json(self.root, OFFICIAL_INDEX_PATH, {'schema_version': 99})
        index, transport = run(self.root, {}, NOW_NOAA + timedelta(hours=1))
        self.assertEqual(transport.urls, [])
        self.assertEqual((self.root / MODELS_INDEX_PATH).read_bytes(), before)

    def test_no_active_system_keeps_ended_systems_and_drops_removed_ones(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.official(cempaka(t), pena(t), now=NOW_NOAA)
        run(self.root, noaa_routes(), NOW_NOAA)
        later = t + timedelta(hours=16)  # JTWC data 16 h old: both systems ended
        ended = official_index(cempaka(t), pena(t), now=later,
                               previous=official_index(cempaka(t), pena(t), now=NOW_NOAA))
        self.assertEqual({s['status'] for s in ended['storms']}, {'ended'})
        ended['storms'] = [s for s in ended['storms'] if s['cyclone_id'] == '2026-jtwc-31w']
        write_json(self.root, OFFICIAL_INDEX_PATH, ended)
        index, transport = run(self.root, {}, later)
        self.assertEqual(transport.urls, [])
        self.assertEqual(index['sources'], {s: {'state': 'idle', 'error_code': None} for s in ('noaa', 'ecmwf')})
        self.assertEqual(list(index['storms']), ['2026-jtwc-31w'])
        self.assertEqual(index['match_basis'], [])
        # The file of the removed system stays on disk until the prune step.
        self.assertTrue((self.root / 'tropical/models/storms/2026-jtwc-04c/2026111106.json').exists())

    def test_new_match_basis_clears_checked(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.official(cempaka(t), now=NOW_NOAA)
        run(self.root, noaa_routes(), NOW_NOAA)
        self.official(cempaka(t), pena(t), now=NOW_NOAA)  # a new system appears
        index, transport = run(self.root, noaa_routes(), NOW_NOAA)
        self.assertIn(tropical_noaa.track_url('gfs', '2026111106'), transport.urls)
        self.assertIn('2026-jtwc-04c', index['storms'])

    def test_tcvitals_bridge_for_a_named_system_without_jtwc(self):
        t = datetime(2026, 11, 11, 18, tzinfo=UTC)
        now = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)
        jma = record('jma', when=t, name='CEMPAKA', lat=30.9, lon=156.0)
        self.official(jma, now=now)
        routes = routes_at(now, noaa=b'', ecmwf=b'', tcvitals=True)
        routes[tropical_noaa.tcvitals_url('2026111118')] = fixture('noaa_tcvitals_2026111118.txt')
        routes[tropical_noaa.track_url('gfs', '2026111118')] = fixture('noaa_avno_2026111106.txt').replace(
            b'2026111106', b'2026111118')
        index, transport = run(self.root, routes, now)
        self.assertEqual(transport.urls.count(tropical_noaa.tcvitals_url('2026111118')), 1)
        storm = index['storms']['2026-jma-tc2638']
        self.assertEqual(storm['bridge'], {'jtwc': '31W'})
        self.assertEqual(index['match_basis'], ['2026-jma-tc2638|31W|CEMPAKA'])
        data = self.saved('tropical/models/storms/2026-jma-tc2638/2026111118.json')
        self.assertEqual(data['models']['gfs']['match'], 'tcvitals')
        # Bridged: the next run does not ask tcvitals again and keeps the bridge.
        index, transport = run(self.root, {**routes, **routes_at(now + timedelta(minutes=30), noaa=b'', ecmwf=b'')},
                               now + timedelta(minutes=30))
        self.assertNotIn(tropical_noaa.tcvitals_url('2026111118'), transport.urls)
        self.assertEqual(index['storms']['2026-jma-tc2638']['bridge'], {'jtwc': '31W'})

    def test_unnamed_systems_are_not_bridged(self):
        t = datetime(2026, 11, 11, 6, tzinfo=UTC)
        self.official(record('jma', when=t, name=None, lat=40.0, lon=120.0), now=NOW_NOAA)
        index, transport = run(self.root, noaa_routes(), NOW_NOAA)
        self.assertFalse(any('tcvitals' in url for url in transport.urls))
        self.assertEqual(index['storms'], {})  # far from WP31: no position match either


class ReviewFixTests(unittest.TestCase):
    """Cases raised by the independent S8a review (design.md 11e E14-E16, review M2/M3)."""
    T = datetime(2026, 11, 11, 6, tzinfo=UTC)

    def test_one_stopped_product_does_not_fail_its_source(self):
        now = datetime(2026, 11, 11, 13, 30, tzinfo=UTC)
        index = official_index(cempaka(self.T), now=now)
        active = [s for s in index['storms'] if s['status'] == 'active']
        previous = models.empty_index(now)
        previous['match_basis'] = models.match_basis(active, {s['cyclone_id']: None for s in active})
        for model in ('ifs', 'gfs', 'aigfs'):  # every due cycle already processed; AIFS never
            for moment in models.due_cycles(model, now):
                cycle = moment.strftime('%Y%m%d%H')
                previous['checked'][cycle] = sorted(set(previous['checked'].get(cycle, [])) | {model})
        asked = []
        result_index, _ = models.run_models(index, previous, {}, {}, now,
                                            lambda url: asked.append(url) or (404, b''))
        self.assertEqual(len(asked), 4)
        self.assertTrue(all('aifs-single' in url for url in asked))
        self.assertEqual(result_index['sources']['ecmwf'], {'state': 'ok', 'error_code': None})
        self.assertEqual(result_index['sources']['noaa'], {'state': 'idle', 'error_code': None})

    def test_a_bridge_is_kept_before_any_cycle_file_exists(self):
        t = datetime(2026, 11, 11, 18, tzinfo=UTC)
        now = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, OFFICIAL_INDEX_PATH, official_index(record('jma', when=t, name='CEMPAKA', lat=30.9,
                                                                        lon=156.0), now=now))
            routes = routes_at(now, noaa=b'', ecmwf=b'', tcvitals=True)
            routes[tropical_noaa.tcvitals_url('2026111118')] = fixture('noaa_tcvitals_2026111118.txt')
            index, _ = run(root, routes, now)
            self.assertEqual(index['storms'], {'2026-jma-tc2638': {'bridge': {'jtwc': '31W'}, 'cycles': []}})
            later = now + timedelta(hours=1)
            index, transport = run(root, {**routes_at(later, noaa=b'', ecmwf=b'', tcvitals=True)}, later)
            self.assertFalse(any('tcvitals' in url for url in transport.urls))
            self.assertEqual(index['match_basis'], ['2026-jma-tc2638|31W|CEMPAKA'])
            self.assertTrue(index['checked'])  # not cleared again
        no_bridge = models_index(storms={'2026-jtwc-31w': {'bridge': {'jtwc': None}, 'cycles': []}})
        with self.assertRaises(ValueError):
            validate_models_index(no_bridge)

    def test_named_ecmwf_track_may_match_an_unnamed_system_by_position(self):
        moment = datetime(2026, 11, 10, 12, tzinfo=UTC)
        track = {'id': '26W', 'name': 'TWENTYSIX', 'init_time': moment,
                 'track': [[0, 20.0, 135.0, None, None], [6, 20.4, 134.5, None, None]]}
        unnamed = record('jma', when=moment + timedelta(hours=1), name=None, lat=20.2, lon=135.1)
        other = record('jtwc', when=moment + timedelta(hours=1), name='OTHER', number='27W', lat=22.5, lon=137.5)
        index = official_index(unnamed, other, now=moment + timedelta(hours=2))
        active = [s for s in index['storms'] if s['status'] == 'active']
        self.assertEqual(len(active), 2)
        positions = {s['cyclone_id']: models.known_positions(s, {}) for s in active}
        found = models.match_ecmwf([track], active, positions, '2026111012')
        # The other, differently named system is neither a target nor a second candidate.
        self.assertEqual({k: v[0][0] for k, v in found.items()}, {'2026-jma-tc2638': 'position'})
        lonely = [s for s in active if s['name'] == 'OTHER']
        self.assertEqual(models.match_ecmwf([track], lonely, positions, '2026111012'), {})

    def test_number_of_an_ended_system_is_not_matched_by_position(self):
        track = {('WP', '44'): [[0, 20.0, 135.0, 1000, 30]]}
        ended_then = official_index(record('jtwc', when=self.T - timedelta(hours=10), name=None, number='44W',
                                           lat=20.1, lon=135.1), now=self.T - timedelta(hours=9))
        both = official_index(record('jtwc', when=self.T - timedelta(hours=10), name=None, number='44W',
                                     lat=20.1, lon=135.1),
                              record('jma', when=self.T, name=None, lat=20.2, lon=135.2),
                              now=self.T + timedelta(hours=6), previous=ended_then)
        statuses = {s['cyclone_id']: s['status'] for s in both['storms']}
        self.assertEqual(statuses.get('2026-jtwc-44w'), 'ended')
        active = [s for s in both['storms'] if s['status'] == 'active']
        positions = {s['cyclone_id']: models.known_positions(s, {}) for s in active}
        bridges = {s['cyclone_id']: None for s in both['storms']}
        self.assertTrue(models.match_noaa(track, active, bridges, positions, self.T))  # without the rule
        self.assertEqual(models.match_noaa(track, active, bridges, positions, self.T, frozenset({'44W'})), {})

    def test_one_broken_tcvitals_line_is_skipped(self):
        body = (b'JTWC 99W BROKEN    20261111 1800 999S 1541E 065\n' + fixture('noaa_tcvitals_2026111118.txt'))
        self.assertEqual([e['id'] for e in tropical_noaa.parse_tcvitals(body)], ['04C', '31W'])


class MatchingTests(unittest.TestCase):
    T = datetime(2026, 11, 11, 6, tzinfo=UTC)

    def storms(self, *records, now=NOW_NOAA):
        index = official_index(*records, now=now)
        active = [s for s in index['storms'] if s['status'] == 'active']
        return active, {s['cyclone_id']: models.known_positions(s, {}) for s in active}

    def test_position_match_needs_a_unique_nearby_unnumbered_system(self):
        track = {('WP', '45'): [[0, 20.0, 135.0, 1000, 30], [6, 20.5, 134.0, 999, 32]]}
        near = record('jma', when=self.T, name=None, lat=20.3, lon=135.2)
        active, positions = self.storms(near)
        bridges = {s['cyclone_id']: None for s in active}
        found = models.match_noaa(track, active, bridges, positions, self.T)
        self.assertEqual([(k, v[0][0], v[0][1]) for k, v in found.items()], [('2026-jma-tc2638', 'position', 'WP45')])
        # A second system within 2D: ambiguous, nothing matched.
        other = record('cwa', when=self.T, name=None, lat=21.5, lon=136.5)
        active, positions = self.storms(near, other)
        self.assertEqual(models.match_noaa(track, active, {s['cyclone_id']: None for s in active}, positions,
                                           self.T), {})
        # A system that already has another JTWC number is not a position target (11e E8).
        numbered = record('jtwc', when=self.T, name=None, number='44W', lat=20.3, lon=135.2)
        active, positions = self.storms(numbered)
        self.assertEqual(models.match_noaa(track, active, {s['cyclone_id']: None for s in active}, positions,
                                           self.T), {})
        # Too far in time: the only official position is 7 h before the track start.
        active, positions = self.storms(record('cwa', when=self.T - timedelta(hours=7), name=None,
                                               lat=20.3, lon=135.2))
        self.assertEqual(len(active), 1)
        self.assertEqual(models.match_noaa(track, active, {s['cyclone_id']: None for s in active}, positions,
                                           self.T), {})

    def test_other_basins_never_match_and_duplicates_are_dropped(self):
        active, positions = self.storms(cempaka(self.T))
        bridges = {s['cyclone_id']: None for s in active}
        track = [[0, 29.0, 150.0, 990, 60]]
        self.assertEqual(models.match_noaa({('SI', '31'): track}, active, bridges, positions, self.T), {})
        self.assertEqual(models.match_noaa({('CP', '31'): track}, active, bridges, positions, self.T), {})
        found = models.match_noaa({('WP', '31'): track}, active, bridges, positions, self.T)
        self.assertEqual(len(found['2026-jtwc-31w']), 1)
        # Two ECMWF tracks of one model with the same name: neither is used (design.md 2.4).
        moment = datetime(2026, 11, 10, 12, tzinfo=UTC)
        index = official_index(cempaka(moment + timedelta(hours=6), lat=26.9, lon=144.3), now=NOW_ECMWF)
        decoded = tropical_ecmwf.decode_tracks(fixture('ecmwf_ifs_2026111012_oper.bufr'))
        twin = [t for t in decoded if t['id'] == '38W'][0]
        with patch.object(tropical_ecmwf, 'decode_tracks', lambda body: [twin, dict(twin, id='31W')]):
            result_index, outputs = models.run_models(
                index, None, {}, {}, NOW_ECMWF,
                lambda url: (200, b'') if 'ecmwf' in url else (404, b''))
        self.assertEqual(result_index['storms'], {})
        self.assertEqual(outputs, {})
        self.assertEqual(result_index['checked']['2026111012'], ['aifs', 'ifs'])

    def test_ecmwf_unnamed_track_uses_position_and_named_needs_the_same_name(self):
        moment = datetime(2026, 11, 10, 12, tzinfo=UTC)
        track = {'id': '06W', 'name': None, 'init_time': moment, 'track': [[0, 20.0, 135.0, None, None],
                                                                          [6, 20.4, 134.5, None, None]]}
        active, positions = self.storms(record('jma', when=moment + timedelta(hours=1), name=None,
                                               lat=20.2, lon=135.1), now=moment + timedelta(hours=2))
        self.assertEqual(len(active), 1)
        found = models.match_ecmwf([track], active, positions, '2026111012')
        self.assertEqual(found['2026-jma-tc2638'][0][:2], ('position', '06W'))
        # Named track, unnamed official system: position still applies (11e E15).
        named = dict(track, name='OTHER')
        self.assertEqual(models.match_ecmwf([named], active, positions, '2026111012')['2026-jma-tc2638'][0][0],
                         'position')


class PruneTests(unittest.TestCase):
    def test_only_unlisted_model_files_are_removed_and_official_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            listed = 'tropical/models/storms/2026-jtwc-31w/2026111106.json'
            old = 'tropical/models/storms/2026-jtwc-31w/2026111100.json'
            gone = 'tropical/models/storms/2026-jtwc-04c/2026111106.json'
            odd = 'tropical/models/storms/2026-jtwc-04c/notes.txt'
            for name in (listed, old, gone):
                write_json(root, name, cycle_file(name.split('/')[3], name.split('/')[4][:10]))
            (root / odd).write_text('x')
            write_json(root, MODELS_INDEX_PATH, models_index())
            self.assertEqual(sorted(_prune_tropical(root)), sorted([old, gone]))
            self.assertTrue((root / listed).exists() and (root / odd).exists())
            # The 04c directory still holds an unrelated file, so it stays.
            self.assertTrue((root / 'tropical/models/storms/2026-jtwc-04c').is_dir())
            for invalid in (b'{', json.dumps({'schema_version': 1}).encode()):
                write_json(root, gone, cycle_file('2026-jtwc-04c'))
                (root / MODELS_INDEX_PATH).write_bytes(invalid)
                self.assertEqual(_prune_tropical(root), [])
                self.assertTrue((root / gone).exists())
            (root / MODELS_INDEX_PATH).unlink()
            self.assertEqual(_prune_tropical(root), [])

    def test_prefixes_are_judged_by_their_own_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime(2026, 11, 11, 11, 30, tzinfo=UTC)
            write_json(root, OFFICIAL_INDEX_PATH, official_index(now=now))  # no systems
            write_json(root, 'tropical/official/storms/2026-jtwc-31w/analysis.json', {})
            name = 'tropical/models/storms/2026-jtwc-31w/2026111106.json'
            write_json(root, name, cycle_file())
            write_json(root, MODELS_INDEX_PATH, models_index())
            self.assertEqual(_prune_tropical(root), ['tropical/official/storms/2026-jtwc-31w/analysis.json'])
            self.assertTrue((root / name).exists())
            self.assertFalse((root / 'tropical/official/storms/2026-jtwc-31w').exists())


def requests_error():
    import requests
    return requests.ConnectionError('offline')


class PipelineTests(unittest.TestCase):
    """The models task inside prepare_due beside image and official tasks."""

    def test_models_failure_leaves_images_and_official_unchanged_and_bytes_stay_compact(self):
        from test_tropical_pipeline import FEW, image_view, make_update, package, prepare, subset
        from src.snapshots import read_resources
        compact = (json.dumps(cycle_file(), separators=(',', ':')) + '\n').encode()
        index = models_index()

        def writer(kind, images):
            if kind != 'tropical_models':
                raise RuntimeError('private official failure')
            root = Path(images).parent
            (root / 'tropical/models/storms/2026-jtwc-31w').mkdir(parents=True, exist_ok=True)
            (root / 'tropical/models/storms/2026-jtwc-31w/2026111106.json').write_bytes(compact)
            write_json(root, MODELS_INDEX_PATH, index)

        def broken(kind, images):
            raise RuntimeError('private models failure')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            sha = package(root)['sha256']
            tasks = subset(*FEW, 'tropical_official', 'tropical_models')
            done = prepare(root, 'ok', make_update(writer), tasks=tasks, sha=sha)
            self.assertEqual(done['checks']['tropical_models']['state'], 'updated')
            site = root / 'ok/site-data'
            self.assertEqual((site / 'tropical/models/storms/2026-jtwc-31w/2026111106.json').read_bytes(), compact)
            files, _ = read_resources(site)
            self.assertIn(MODELS_INDEX_PATH, files)
            for label, update in (('models fails', make_update(broken)),):
                with self.subTest(label):
                    failed = prepare(root, 'failed', update, tasks=tasks, sha=sha)
                    control = prepare(root, 'control', make_update(broken), tasks=subset(*FEW), sha=sha)
                    self.assertEqual(image_view(failed, root, 'failed', FEW), image_view(control, root, 'control', FEW))
                    for field in ('deploy', 'save_snapshot', 'deployment_reason'):
                        self.assertEqual(failed[field], control[field], field)
                    self.assertEqual(failed['checks']['tropical_models']['state'], 'retained_after_failure')
                    self.assertEqual(failed['products']['tropical_models'], 'failed')
                    self.assertNotIn('private models failure', json.dumps(failed))


if __name__ == '__main__':
    unittest.main()
