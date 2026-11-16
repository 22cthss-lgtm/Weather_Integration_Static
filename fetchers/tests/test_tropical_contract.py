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
                                   validate_official_index)

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
                     'tropical/official/storms/2026-jma-tc2638/analysis.json', 'tropical/models/index.json',
                     'tropical/official/../official/index.json'):
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


class SnapshotCompatibilityTests(unittest.TestCase):
    def roundtrip(self, root, *, with_tropical):
        from src.pages_package import pack_snapshot, site_summary, unpack_snapshot
        from src.snapshots import export_snapshot, restore_snapshot
        write_seed(root / 'data', 2)
        if with_tropical:
            path = root / 'data' / OFFICIAL_INDEX_PATH
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(valid_index(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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
