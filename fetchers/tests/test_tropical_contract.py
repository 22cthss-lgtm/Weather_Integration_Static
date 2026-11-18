"""tropical/official/index.json contract, whitelist and old-snapshot compatibility."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from snapshot_fixtures import write_seed
from tropical_testing import no_storm_index, valid_index

from src import scheduling
from src.snapshots import IMAGE_TYPES, REQUIRED, allowed_path, read_resources, validate_resource
from src.tropical_contract import (OFFICIAL_INDEX_PATH, SAFE_ERROR_CODES, expected_status,
                                   validate_official_index, validate_storm_file)

PACK_TIME = datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc)


def edit(path, value):
    """Return a mutation that sets data[path...] = value."""
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def drop(path):
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return mutate


STORM = ('storms', 0)
JMA = (*STORM, 'summary', 'jma')
VIOLATIONS = {
    'extra top-level field': edit(('note',), 'x'),
    'missing top-level field': drop(('basin',)),
    'schema version as bool': edit(('schema_version',), True),
    'unknown schema version': edit(('schema_version',), 2),
    'other basin': edit(('basin',), 'EP'),
    'backend never writes UNAVAILABLE': edit(('status',), 'UNAVAILABLE'),
    'backend never writes STALE': edit(('status',), 'STALE'),
    'status contradicts sources': edit(('status',), 'OK_WITH_STORMS'),
    'fetched_at with offset': edit(('fetched_at',), '2026-11-11T18:33:07+08:00'),
    'fetched_at without seconds': edit(('fetched_at',), '2026-11-11T10:33Z'),
    'fetched_at fractional': edit(('fetched_at',), '2026-11-11T10:33:07.5Z'),
    'fetched_at impossible date': edit(('fetched_at',), '2026-02-30T10:33:07Z'),
    'missing source': drop(('sources', 'jtwc')),
    'extra source': edit(('sources', 'noaa'), {}),
    'jtwc marked required': edit(('sources', 'jtwc', 'required'), True),
    'cwa marked optional': edit(('sources', 'cwa', 'required'), False),
    'unknown source state': edit(('sources', 'jma', 'state'), 'idle'),
    'ok source with error code': edit(('sources', 'jma', 'error_code'), 'timeout'),
    'failed source with arbitrary error text': edit(('sources', 'jtwc', 'error_code'), 'HTTP 403 from https://x'),
    'failed source without error code': edit(('sources', 'jtwc', 'error_code'), None),
    'failed source with active count': edit(('sources', 'jtwc', 'active_count'), 0),
    'ok source without active count': edit(('sources', 'jma', 'active_count'), None),
    'active count as bool': edit(('sources', 'jma', 'active_count'), True),
    'last_ok_at with seconds': edit(('sources', 'jtwc', 'last_ok_at'), '2026-11-11T09:03:07Z'),
    'last_ok_at in the future': edit(('sources', 'jtwc', 'last_ok_at'), '2026-11-11T11:00:00Z'),
    'ok source with stale last_ok_at': edit(('sources', 'jma', 'last_ok_at'), '2026-11-11T10:00:00Z'),
    'ok source without last_ok_at': edit(('sources', 'jma', 'last_ok_at'), None),
    'storms not a list': edit(('storms',), {}),
    'too many storms': lambda data: data.__setitem__('storms', [
        dict(deepcopy(data['storms'][0]), cyclone_id=f'2026-jma-tc26{n:02d}') for n in range(13)]),
    'duplicate storms': lambda data: data['storms'].append(deepcopy(data['storms'][0])),
    'malformed cyclone_id': edit((*STORM, 'cyclone_id'), '2026-JMA-TC2638'),
    'cyclone_id with path separator': edit((*STORM, 'cyclone_id'), '2026-jma-../x'),
    'season differs from id': edit((*STORM, 'season'), 2027),
    'season as string': edit((*STORM, 'season'), '2026'),
    'lower-case name': edit((*STORM, 'name'), 'Cempaka'),
    'name too long': edit((*STORM, 'name'), 'A' * 41),
    'name_zh carrying a URL': edit((*STORM, 'name_zh'), 'https://x/?key=1'),
    'unknown origin basin': edit((*STORM, 'origin_basin'), 'IO'),
    'missing id key': drop((*STORM, 'ids', 'cwa_td')),
    'malformed jtwc id': edit((*STORM, 'ids', 'jtwc'), '31B'),
    'malformed jma id': edit((*STORM, 'ids', 'jma_tc'), '2638'),
    'unknown match value': edit((*STORM, 'match', 'cwa'), 'guess'),
    'two origins': edit((*STORM, 'match', 'cwa'), 'origin'),
    'origin agency not origin': edit((*STORM, 'match', 'jma'), 'name'),
    'match without summary': edit((*STORM, 'summary', 'cwa'), None),
    'summary without match': edit((*STORM, 'match', 'cwa'), None),
    'missing summary agency': drop((*STORM, 'summary', 'cwa')),
    'missing summary field': drop((*JMA, 'category')),
    'extra summary field': edit((*JMA, 'image_url'), 'https://example.invalid/x.png'),
    'active as int': edit((*JMA, 'active'), 1),
    'latitude out of range': edit((*JMA, 'lat'), 90.1),
    'longitude exactly 180': edit((*JMA, 'lon'), 180.0),
    'longitude 0-360': edit((*JMA, 'lon'), 200.0),
    'longitude NaN': edit((*JMA, 'lon'), float('nan')),
    'latitude as string': edit((*JMA, 'lat'), '29.2'),
    'latitude as bool': edit((*JMA, 'lat'), True),
    'pressure out of range': edit((*JMA, 'pressure_hpa'), 0),
    'category too long': edit((*JMA, 'category'), 'X' * 41),
    'category carrying a URL': edit((*JMA, 'category'), 'see https://x'),
    'wind out of range': edit((*JMA, 'max_wind', 'kt'), 250),
    'wind missing unit key': drop((*JMA, 'max_wind', 'ms')),
    'jma averaging 1 minute': edit((*JMA, 'max_wind', 'averaging_min'), 1),
    'jtwc with converted m/s': edit((*STORM, 'summary', 'jtwc', 'max_wind', 'ms'), 33),
    'cwa with converted kt': edit((*STORM, 'summary', 'cwa', 'max_wind', 'kt'), 58),
    'analysis time with offset': edit((*JMA, 'analysis_time'), '2026-11-11T18:00:00+09:00'),
    'last_fix_time not the maximum': edit((*STORM, 'last_fix_time'), '2026-11-11T06:00:00Z'),
    'active storm with ended_at': edit((*STORM, 'ended_at'), '2026-11-11T10:00:00Z'),
    'ended status while agencies active': edit((*STORM, 'status'), 'ended'),
    'unknown storm status': edit((*STORM, 'status'), 'dissipated'),
}

MALFORMED = [None, True, 0, 1.5, 'text', [], [[]], {}, {'schema_version': 1}, {'storms': [None]}]


def shapes():
    """Structurally broken variants of a valid index: wrong types at every level."""
    junk = (None, True, 7, 'x', [], {}, [None], {'a': None}, [[1, 2]], float('inf'))
    base = valid_index()
    paths = [('sources',), ('sources', 'jma'), ('sources', 'jma', 'last_ok_at'), ('storms',), STORM,
             (*STORM, 'ids'), (*STORM, 'match'), (*STORM, 'summary'), JMA, (*JMA, 'max_wind'),
             (*JMA, 'analysis_time'), (*STORM, 'cyclone_id'), (*STORM, 'name'), (*STORM, 'last_fix_time'),
             (*STORM, 'ended_at'), ('fetched_at',), ('status',)]
    for path in paths:
        for value in junk:
            data = deepcopy(base)
            edit(path, value)(data)
            yield path, value, data


class ContractTests(unittest.TestCase):
    def test_accepts_design_example_and_no_storm_index(self):
        self.assertEqual(validate_official_index(valid_index())['status'], 'PARTIAL')
        validate_resource(OFFICIAL_INDEX_PATH, no_storm_index())

    def test_accepts_ended_storm_and_position_match_reserved_for_s6(self):
        data = valid_index()
        storm = data['storms'][0]
        for agency in ('jtwc', 'jma', 'cwa'):
            storm['summary'][agency]['active'] = False
        storm.update(status='ended', ended_at='2026-11-11T10:33:00Z')
        storm['match']['cwa'] = 'position'
        data['status'] = 'OK_NO_STORMS'
        validate_official_index(data)

    def test_accepts_longitude_minus_180_and_null_optional_values(self):
        data = valid_index()
        jma = data['storms'][0]['summary']['jma']
        jma.update(lon=-180.0, category=None, max_wind=None, pressure_hpa=None)
        data['storms'][0].update(name=None, name_zh=None)
        validate_official_index(data)

    def test_rejects_every_violation(self):
        for label, mutate in VIOLATIONS.items():
            with self.subTest(label):
                data = valid_index()
                mutate(data)
                with self.assertRaises(ValueError):
                    validate_official_index(data)

    def test_malformed_input_raises_only_value_error(self):
        cases = [(None, None, value) for value in MALFORMED] + list(shapes())
        self.assertGreater(len(cases), 150)
        rejected = 0
        for path, value, data in cases:
            with self.subTest(path=path, value=repr(value)):
                # Any exception other than ValueError propagates and fails this test.
                for check in (validate_official_index, lambda item: validate_resource(OFFICIAL_INDEX_PATH, item)):
                    try:
                        check(deepcopy(data))
                    except ValueError:
                        rejected += 1
        # A few junk values are legal (null name, null ended_at...); nearly all must be refused.
        self.assertGreater(rejected, len(cases) * 2 * 0.9)

    def test_status_table_of_design_3_3(self):
        ok, failed = 'ok', 'failed'
        table = [
            ((failed, failed, failed), True, None), ((failed, failed, failed), False, None),
            ((failed, ok, ok), True, 'PARTIAL'), ((ok, failed, ok), False, 'PARTIAL'),
            ((failed, failed, ok), True, 'PARTIAL'),
            ((ok, ok, failed), False, 'OK_NO_STORMS'), ((ok, ok, ok), False, 'OK_NO_STORMS'),
            ((ok, ok, failed), True, 'PARTIAL'), ((ok, ok, ok), True, 'OK_WITH_STORMS'),
        ]
        for (cwa, jma, jtwc), active, status in table:
            with self.subTest(cwa=cwa, jma=jma, jtwc=jtwc, active=active):
                self.assertEqual(expected_status({'cwa': cwa, 'jma': jma, 'jtwc': jtwc}, active), status)

    def test_error_codes_stay_in_step_with_scheduler(self):
        self.assertEqual(SAFE_ERROR_CODES, scheduling.SAFE_ERRORS)

    def test_no_reserved_side_effect_keys_in_contract(self):
        text = json.dumps(valid_index())
        self.assertNotIn('image_url', text)
        self.assertNotIn('source_url', text)


class WhitelistTests(unittest.TestCase):
    def test_tropical_index_is_allowed_but_never_required(self):
        self.assertTrue(allowed_path(OFFICIAL_INDEX_PATH))
        self.assertNotIn(OFFICIAL_INDEX_PATH, REQUIRED)
        self.assertFalse(any(kind.startswith('tropical') for kind in IMAGE_TYPES))
        self.assertEqual(len(IMAGE_TYPES), 12)
        self.assertEqual(len(REQUIRED), 14)
        for name in ('tropical/index.json', 'tropical/official/index.json.bak', 'tropical/official/x.json',
                     'tropical/ensemble/index.json',  # S9; tropical/models/ is allowed since S8
                     'tropical/official/../official/index.json'):
            self.assertFalse(allowed_path(name), name)

    def test_storm_files_are_allowed_by_rule_and_never_required(self):
        # S6 (design.md 4.1): the per-storm files match one dynamic rule.
        for name in ('tropical/official/storms/2026-jma-tc2638/analysis.json',
                     'tropical/official/storms/2026-jtwc-31w/forecast.json',
                     'tropical/official/storms/2027-cwa-td1/analysis.json'):
            self.assertTrue(allowed_path(name), name)
            self.assertNotIn(name, REQUIRED)
        for name in ('tropical/official/storms/2026-JMA-TC2638/analysis.json',
                     'tropical/official/storms/2026-noaa-31w/analysis.json',
                     'tropical/official/storms/2026-jma-tc2638/track.json',
                     'tropical/official/storms/2026-jma-tc2638/analysis.json.tmp',
                     'tropical/official/storms/2026-jma-tc2638/x/analysis.json',
                     'tropical/official/storms/2026-jma-/analysis.json',
                     'tropical/official/storms/2026-jma-abcdefghi/analysis.json',
                     'tropical/official/storms/../index.json',
                     'tropical/official/storms/2026-jma-tc2638/../2026-jma-tc2639/analysis.json',
                     'tropical/official/storms/26-jma-tc2638/analysis.json'):
            self.assertFalse(allowed_path(name), name)

    def test_invalid_tropical_file_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory) / 'data'
            write_seed(root, 2)
            path = root / OFFICIAL_INDEX_PATH
            path.parent.mkdir(parents=True)
            for content in (b'{"storms": [[]]}', b'[]', b'not json', b'{"schema_version": 1}', b'\xff\xfe'):
                path.write_bytes(content)
                valid, invalid = read_resources(root, strict=False)
                self.assertEqual(invalid, [OFFICIAL_INDEX_PATH])
                self.assertTrue(all(name in valid for name in REQUIRED))
                with self.assertRaises(ValueError):
                    read_resources(root)


A = ('agencies',)
AJ, AM, AC = (*A, 'jtwc'), (*A, 'jma'), (*A, 'cwa')
ANALYSIS_VIOLATIONS = {
    'extra top-level field': edit(('note',), 1),
    'missing agencies': drop(('agencies',)),
    'unknown schema version': edit(('schema_version',), 2),
    'cyclone_id differs from path': edit(('cyclone_id',), '2026-jma-tc2639'),
    'fetched_at with offset': edit(('fetched_at',), '2026-11-11T18:33:07+08:00'),
    'extra agency': edit((*A, 'noaa'), None),
    'missing agency': drop(AC),
    'reserved image_url key': edit((*AJ, 'image_url'), 'https://www.metoc.navy.mil/jtwc/products/wp3126.gif'),
    'reserved source_url key': edit((*AJ, 'source_url'), None),
    'product url on another host': edit((*AJ, 'product_url'), 'https://example.com/wp3126.tcw'),
    'product url over http': edit((*AJ, 'product_url'), 'http://www.metoc.navy.mil/jtwc/products/wp3126.tcw'),
    'product url with query': edit((*AJ, 'product_url'), 'https://www.metoc.navy.mil/jtwc/products/wp3126.tcw?key=1'),
    'product url with credentials': edit((*AJ, 'product_url'), 'https://u:p@www.metoc.navy.mil/jtwc/products/x.tcw'),
    'cwa request url instead of dataset page': edit(
        (*AC, 'product_url'), 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005?Authorization=x'),
    'jma url of another product': edit((*AM, 'product_url'),
                                       'https://www.data.jma.go.jp/developer/xml/data/20261111094118_0_VPWW53_010000.xml'),
    'graphic for cwa': edit((*AC, 'graphic_url'), 'https://www.cwa.gov.tw/x.gif'),
    'graphic not a gif': edit((*AJ, 'graphic_url'), 'https://www.metoc.navy.mil/jtwc/products/wp3126.tcw'),
    'issued_at without seconds': edit((*AJ, 'issued_at'), '2026-11-11T09:00Z'),
    'bulletin as int': edit((*AJ, 'bulletin'), 21),
    'bulletin with text': edit((*AJ, 'bulletin'), 'see https://x'),
    'cwa marked final': edit((*AC, 'final'), True),
    'final as int': edit((*AJ, 'final'), 0),
    'missing fix field': drop((*AJ, 'fix', 'gust')),
    'extra fix field': edit((*AJ, 'fix', 'note'), None),
    'fix longitude 180': edit((*AJ, 'fix', 'lon'), 180.0),
    'fix latitude out of range': edit((*AJ, 'fix', 'lat'), -90.5),
    'cwa category': edit((*AC, 'fix', 'category'), '輕度颱風'),
    'jtwc converted wind': edit((*AJ, 'fix', 'max_wind', 'ms'), 33),
    'jtwc gust in m/s': edit((*AJ, 'fix', 'gust', 'ms'), 41),
    'cwa gust in kt': edit((*AC, 'fix', 'gust', 'kt'), 74),
    'empty gust': edit((*AJ, 'fix', 'gust'), {'kt': None, 'ms': None}),
    'pressure out of range': edit((*AJ, 'fix', 'pressure_hpa'), 1200),
    'movement degree out of range': edit((*AJ, 'fix', 'movement', 'direction_deg'), 361),
    'movement unknown text': edit((*AM, 'fix', 'movement', 'direction_text'), '東北東'),
    'jtwc movement in km/h': edit((*AJ, 'fix', 'movement', 'speed_kmh'), 61),
    'cwa movement in kt': edit((*AC, 'fix', 'movement', 'speed_kt'), 29),
    'jma movement as degrees': edit((*AM, 'fix', 'movement', 'direction_deg'), 67),
    'empty movement': edit((*AJ, 'fix', 'movement'),
                           {'direction_deg': None, 'direction_text': None, 'speed_kt': None, 'speed_kmh': None}),
    'radii not a list': edit((*AJ, 'fix', 'radii'), None),
    'radii unit from another agency': edit((*AC, 'fix', 'radii', 0, 'unit'), 'nm'),
    'radii threshold unit converted': edit((*AJ, 'fix', 'radii', 0, 'threshold', 'unit'), 'm/s'),
    'radii negative radius': edit((*AJ, 'fix', 'radii', 0, 'sectors', 0, 'radius'), -1),
    'radii unknown direction': edit((*AJ, 'fix', 'radii', 0, 'sectors', 0, 'dir'), 'NNE'),
    'radii duplicate direction': edit((*AJ, 'fix', 'radii', 0, 'sectors', 1, 'dir'), 'NE'),
    'radii empty sectors': edit((*AJ, 'fix', 'radii', 0, 'sectors'), []),
    'radii duplicate threshold': lambda data: data['agencies']['jtwc']['fix']['radii'].append(
        deepcopy(data['agencies']['jtwc']['fix']['radii'][0])),
    'too many radii': lambda data: data['agencies']['jtwc']['fix'].__setitem__('radii', [
        {'threshold': {'value': v, 'unit': 'kt'}, 'unit': 'nm', 'sectors': [{'dir': 'ALL', 'radius': 1}]}
        for v in (30, 34, 50, 64, 100)]),
    'jtwc track marked source': edit((*AJ, 'past_track_origin'), 'source'),
    'cwa track marked accumulated': edit((*AC, 'past_track_origin'), 'accumulated'),
    'past point after the fix': edit((*AJ, 'past_track', 0, 'analysis_time'), '2026-11-11T07:00:00Z'),
    'past point equal to the fix': edit((*AJ, 'past_track', 0, 'analysis_time'), '2026-11-11T06:00:00Z'),
    'past point extra field': edit((*AJ, 'past_track', 0, 'gust'), None),
    'past points out of order': lambda data: data['agencies']['jtwc']['past_track'].append(
        deepcopy(data['agencies']['jtwc']['past_track'][0])),
    'too many past points': lambda data: data['agencies']['jtwc'].__setitem__('past_track', [
        dict(deepcopy(data['agencies']['jtwc']['past_track'][0]),
             analysis_time=f'2026-10-{1 + n // 24:02d}T{n % 24:02d}:00:00Z') for n in range(161)]),
}
FORECAST_VIOLATIONS = {
    'extra top-level field': edit(('note',), 1),
    'cyclone_id differs from path': edit(('cyclone_id',), '2026-jtwc-31w'),
    'missing agency': drop(AM),
    'extra block field': edit((*AJ, 'graphic_url'), None),
    'init_time with offset': edit((*AJ, 'init_time'), '2026-11-11T15:00:00+09:00'),
    'valid_time not init plus tau': edit((*AJ, 'points', 0, 'valid_time'), '2026-11-11T19:00:00Z'),
    'tau zero': lambda data: data['agencies']['jtwc']['points'][0].update(tau_h=0, valid_time='2026-11-11T06:00:00Z'),
    'tau above 240': lambda data: data['agencies']['jtwc']['points'][1].update(
        tau_h=241, valid_time='2026-11-21T07:00:00Z'),
    'tau as float': edit((*AJ, 'points', 0, 'tau_h'), 12.0),
    'tau as bool': lambda data: data['agencies']['jtwc']['points'][0].update(tau_h=True, valid_time='2026-11-11T07:00:00Z'),
    'points out of order': lambda data: data['agencies']['jtwc']['points'].reverse(),
    'duplicate tau': lambda data: data['agencies']['jtwc']['points'].append(
        deepcopy(data['agencies']['jtwc']['points'][1])),
    'too many points': lambda data: data['agencies']['jma'].__setitem__('points', [
        dict(deepcopy(data['agencies']['jma']['points'][0]), tau_h=tau,
             valid_time=f'2026-11-{11 + (9 + tau) // 24:02d}T{(9 + tau) % 24:02d}:00:00Z') for tau in range(1, 26)]),
    'point longitude 180': edit((*AJ, 'points', 1, 'lon'), 180.0),
    'jtwc probability circle': edit((*AJ, 'points', 0, 'probability_circle'),
                                    {'radius': 50, 'unit': 'km', 'probability_pct': 70}),
    'probability above 100': edit((*AM, 'points', 0, 'probability_circle', 'probability_pct'), 101),
    'probability unit unknown': edit((*AM, 'points', 0, 'probability_circle', 'unit'), 'mi'),
    'unknown note': edit((*AJ, 'points', 0, 'note'), 'BECOMING EXTRATROPICAL'),
    'cwa wind in kt': edit((*AC, 'points', 0, 'max_wind'), {'kt': 50, 'ms': None, 'averaging_min': 10}),
    'points not a list': edit((*AJ, 'points'), {}),
}


class StormFileContractTests(unittest.TestCase):
    def test_accepts_examples_null_agencies_and_empty_points(self):
        from tropical_testing import ANALYSIS_PATH, FORECAST_PATH, valid_analysis, valid_forecast
        validate_storm_file(ANALYSIS_PATH, valid_analysis())
        validate_storm_file(FORECAST_PATH, valid_forecast())
        validate_resource(ANALYSIS_PATH, valid_analysis())
        validate_resource(FORECAST_PATH, valid_forecast())
        empty = valid_analysis()
        empty['agencies'] = dict.fromkeys(('jtwc', 'jma', 'cwa'))
        validate_storm_file(ANALYSIS_PATH, empty)
        final = valid_forecast()
        final['agencies']['jma']['points'] = []  # JMA final bulletin: no forecast part [S3 sample].
        validate_storm_file(FORECAST_PATH, final)
        lean = valid_analysis()
        lean['agencies']['jtwc']['fix'].update(gust=None, movement=None, radii=[], category=None, max_wind=None,
                                               pressure_hpa=None)
        lean['agencies']['jtwc'].update(graphic_url=None, bulletin=None, past_track=[])
        validate_storm_file(ANALYSIS_PATH, lean)

    def test_one_path_one_kind(self):
        from tropical_testing import ANALYSIS_PATH, FORECAST_PATH, valid_analysis, valid_forecast
        for path, data in ((ANALYSIS_PATH, valid_forecast()), (FORECAST_PATH, valid_analysis()),
                           (OFFICIAL_INDEX_PATH, valid_analysis()), ('tropical/official/storms/x/analysis.json',
                                                                    valid_analysis())):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_storm_file(path, data)

    def test_rejects_every_violation(self):
        from tropical_testing import ANALYSIS_PATH, FORECAST_PATH, valid_analysis, valid_forecast
        for path, base, violations in ((ANALYSIS_PATH, valid_analysis, ANALYSIS_VIOLATIONS),
                                       (FORECAST_PATH, valid_forecast, FORECAST_VIOLATIONS)):
            for label, mutate in violations.items():
                with self.subTest(path=path, violation=label):
                    data = base()
                    mutate(data)
                    with self.assertRaises(ValueError):
                        validate_storm_file(path, data)
                    with self.assertRaises(ValueError):
                        validate_resource(path, data)

    def test_malformed_input_raises_only_value_error(self):
        from tropical_testing import ANALYSIS_PATH, FORECAST_PATH, valid_analysis, valid_forecast
        junk = (None, True, 7, -1, 'x', [], {}, [None], {'a': None}, [[1, 2]], float('inf'), float('nan'))

        def walk(data, prefix=()):
            yield prefix
            if isinstance(data, dict):
                for key, value in data.items():
                    yield from walk(value, (*prefix, key))
            elif isinstance(data, list):
                for position, value in enumerate(data):
                    yield from walk(value, (*prefix, position))

        cases = 0
        for path, base in ((ANALYSIS_PATH, valid_analysis), (FORECAST_PATH, valid_forecast)):
            for location in list(walk(base()))[1:]:
                for value in junk:
                    data = base()
                    edit(location, value)(data)
                    cases += 1
                    with self.subTest(path=path, location=location, value=repr(value)):
                        for check in (lambda item: validate_storm_file(path, item),
                                      lambda item: validate_resource(path, item)):
                            try:
                                check(deepcopy(data))
                            except ValueError:
                                pass
            for value in MALFORMED:
                with self.assertRaises(ValueError):
                    validate_storm_file(path, deepcopy(value))
        self.assertGreater(cases, 2000)


class SnapshotCompatibilityTests(unittest.TestCase):
    def roundtrip(self, root, *, with_tropical, with_storms=False):
        from src.pages_package import pack_snapshot, site_summary, unpack_snapshot
        from src.snapshots import export_snapshot, restore_snapshot
        write_seed(root / 'data', 2)
        if with_tropical:
            path = root / 'data' / OFFICIAL_INDEX_PATH
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(valid_index(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if with_storms:
            from tropical_testing import ANALYSIS_PATH, FORECAST_PATH, valid_analysis, valid_forecast
            for name, data in ((ANALYSIS_PATH, valid_analysis()), (FORECAST_PATH, valid_forecast())):
                (root / 'data' / name).parent.mkdir(parents=True, exist_ok=True)
                (root / 'data' / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                                                  encoding='utf-8')
        manifest = export_snapshot(root / 'data', root / 'snapshot')
        restore_snapshot(root / 'snapshot', root / 'restored')
        package = pack_snapshot(root / 'snapshot', root / 'package.zip', now=PACK_TIME)
        selected = unpack_snapshot(root / 'package.zip', package['sha256'], root / 'unpacked', now=PACK_TIME)
        summary = site_summary(root / 'unpacked')
        resources, _ = read_resources(root / 'unpacked')
        return manifest, selected, summary, resources

    def test_old_snapshot_without_tropical_files_restores_packs_and_validates(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            manifest, selected, summary, resources = self.roundtrip(Path(directory), with_tropical=False)
            self.assertFalse(any(name.startswith('tropical/') for name in manifest['files']))
            self.assertFalse(any(name.startswith('tropical/') for name in resources))
            self.assertEqual(summary['json_files'], len(resources))
            self.assertTrue(all(name in resources for name in REQUIRED))

    def test_snapshot_with_tropical_index_roundtrips_without_image_hashes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            manifest, selected, summary, resources = self.roundtrip(Path(directory), with_tropical=True)
            self.assertIn(OFFICIAL_INDEX_PATH, manifest['files'])
            self.assertEqual(json.loads(resources[OFFICIAL_INDEX_PATH]), valid_index())
            # The index adds one file and no image to hash.
            self.assertEqual(selected['content']['image_hashes'], {})

    def test_snapshot_with_storm_files_roundtrips_and_site_summary_ignores_them(self):
        from tropical_testing import ANALYSIS_PATH, FORECAST_PATH, valid_analysis
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            manifest, selected, summary, resources = self.roundtrip(Path(directory), with_tropical=True,
                                                                    with_storms=True)
            self.assertIn(ANALYSIS_PATH, manifest['files'])
            self.assertIn(FORECAST_PATH, manifest['files'])
            self.assertEqual(json.loads(resources[ANALYSIS_PATH]), valid_analysis())
            self.assertEqual(selected['content']['image_hashes'], {})  # graphic_url is not an image key
            self.assertEqual(summary['json_files'], len(resources))

    def test_storm_files_without_index_still_pack(self):
        # No cross-file check (design.md 4.3): orphan storm files never block a snapshot.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            manifest, _, summary, resources = self.roundtrip(Path(directory), with_tropical=False, with_storms=True)
            self.assertNotIn(OFFICIAL_INDEX_PATH, resources)
            self.assertEqual(summary['json_files'], len(resources))

    def test_invalid_storm_file_is_reported_not_raised(self):
        from tropical_testing import ANALYSIS_PATH
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory) / 'data'
            write_seed(root, 2)
            path = root / ANALYSIS_PATH
            path.parent.mkdir(parents=True)
            for content in (b'{"agencies": [[]]}', b'[]', b'not json', b'\xff\xfe', b'{"schema_version": 1}'):
                path.write_bytes(content)
                valid, invalid = read_resources(root, strict=False)
                self.assertEqual(invalid, [ANALYSIS_PATH])
                self.assertTrue(all(name in valid for name in REQUIRED))

    def test_fetched_at_is_not_content_but_heartbeat_is(self):
        from src.content_versions import resource_identity
        base = valid_index()
        later = deepcopy(base)
        later['fetched_at'] = '2026-11-11T10:33:40Z'
        self.assertEqual(resource_identity(base), resource_identity(later))
        beat = deepcopy(base)
        beat['sources']['jtwc']['last_ok_at'] = '2026-11-11T09:33:00Z'
        self.assertNotEqual(resource_identity(base), resource_identity(beat))


if __name__ == '__main__':
    unittest.main()
