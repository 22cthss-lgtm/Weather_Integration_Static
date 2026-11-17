"""The tropical prune step (design.md 3.6): storm files of systems no longer indexed.

Synthetic seeds, fixed instants; the network is blocked. Separate from the
history removals and from their ``pruned_history`` report field.
"""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tropical_testing as tt
from snapshot_fixtures import DAY, write_seed
from test_history_pruning import KINDS, add_past_days, bump_radar, history_names

from src.snapshots import read_resources
from src.tropical_contract import OFFICIAL_INDEX_PATH

UTC = timezone.utc
# 2026-10-21T16:30Z is 10-22 00:30 in Taipei, the synthetic seed's day.
NOW = datetime(2026, 10, 21, 16, 30, tzinfo=UTC)
KEPT = '2026-jma-tc2638'          # listed by tt.valid_index()
GONE = '2026-jtwc-32w'            # not listed: an orphan
STORMS = 'tropical/official/storms'


def storm_files(identity):
    return {f'{STORMS}/{identity}/analysis.json': dict(tt.valid_analysis(), cyclone_id=identity),
            f'{STORMS}/{identity}/forecast.json': dict(tt.valid_forecast(), cyclone_id=identity)}


def orphan_paths():
    return sorted(storm_files(GONE))


def write_json(root, name, data):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_tropical(root, *, index=True, files=(KEPT, GONE)):
    if index is True:
        write_json(root, OFFICIAL_INDEX_PATH, tt.valid_index())
    elif index is not None:
        path = Path(root) / OFFICIAL_INDEX_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(index)
    for identity in files:
        for name, data in storm_files(identity).items():
            write_json(root, name, data)


def tropical_names(root):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).glob('tropical/**/*') if p.is_file())


def setUpModule():
    tt.block_network()


def tearDownModule():
    tt.unblock_network()


class PruneFunctionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prune(self):
        from src.snapshot_runner import _prune_tropical
        return _prune_tropical(self.root)

    def test_only_files_of_unlisted_systems_go(self):
        write_tropical(self.root)
        self.assertEqual(self.prune(), orphan_paths())
        self.assertEqual(tropical_names(self.root), sorted([OFFICIAL_INDEX_PATH, *storm_files(KEPT)]))
        self.assertFalse((self.root / STORMS / GONE).exists())   # the emptied directory itself

    def test_only_exact_storm_file_paths_are_touched(self):
        write_tropical(self.root)
        strays = [f'{STORMS}/{GONE}/readme.txt', f'{STORMS}/{GONE}/analysis.json.bak',
                  f'{STORMS}/{GONE}/old/analysis.json', f'{STORMS}/Bad-ID/analysis.json',
                  f'{STORMS}/2026-jtwc-33w/history.json', 'tropical/official/analysis.json',
                  'tropical/models/storms/2026-jtwc-32w/2026111100.json', f'images/radar/{GONE}/analysis.json']
        for name in strays:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}', encoding='utf-8')
        self.assertEqual(self.prune(), orphan_paths())
        for name in strays:
            self.assertTrue((self.root / name).exists(), name)
        self.assertTrue((self.root / STORMS / GONE).is_dir())   # not empty: kept

    def test_missing_unreadable_or_invalid_index_removes_nothing(self):
        broken = json.dumps(dict(tt.valid_index(), status='NOPE')).encode()
        for index in (None, b'{not json', b'\xff\xfe', broken, b'[]'):
            with self.subTest(index=index):
                for path in self.root.iterdir():
                    shutil.rmtree(path)
                write_tropical(self.root, index=index)
                before = tropical_names(self.root)
                self.assertEqual(self.prune(), [])
                self.assertEqual(tropical_names(self.root), before)

    def test_index_without_storms_removes_every_storm_file(self):
        write_json(self.root, OFFICIAL_INDEX_PATH, tt.no_storm_index())
        write_tropical(self.root, index=None)
        self.assertEqual(self.prune(), sorted([*storm_files(KEPT), *storm_files(GONE)]))
        self.assertEqual(tropical_names(self.root), [OFFICIAL_INDEX_PATH])

    def test_nothing_to_do_without_a_tropical_tree(self):
        write_seed(self.root, 2)
        self.assertEqual(self.prune(), [])


class RunCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.seed = self.base / 'old'
        write_seed(self.seed, 2)
        add_past_days(self.seed)
        write_tropical(self.seed)
        self.seed_before = {p: p.read_bytes() for p in self.seed.rglob('*') if p.is_file()}

    def run_candidate(self, update=lambda product, images: bump_radar(images), products=('radar',), **options):
        from src.snapshot_runner import run_candidate
        return run_candidate(list(products), self.seed, self.base / 'store', update, **options)

    def data(self, report):
        return self.base / 'store/snapshots' / report['snapshot_id'] / 'data'

    def test_orphans_go_are_reported_apart_and_are_not_expected(self):
        report = self.run_candidate(prune_tropical=True)
        self.assertTrue(report['publishable'] and report['complete'])
        self.assertEqual(report['pruned_tropical'], orphan_paths())
        self.assertEqual(report['pruned_history'], [])
        for name in orphan_paths():
            self.assertNotIn(name, report['resources'])
        self.assertEqual(tropical_names(self.data(report)), sorted([OFFICIAL_INDEX_PATH, *storm_files(KEPT)]))
        # The seed is never edited.
        self.assertEqual({p: p.read_bytes() for p in self.seed.rglob('*') if p.is_file()}, self.seed_before)

    def test_default_keeps_every_storm_file(self):
        report = self.run_candidate()
        self.assertEqual(report['pruned_tropical'], [])
        self.assertIn(orphan_paths()[0], tropical_names(self.data(report)))
        self.assertEqual(report['resources'][orphan_paths()[0]]['state'], 'retained')

    def test_pruning_alone_does_not_publish_or_move_the_pointer(self):
        report = self.run_candidate(update=lambda product, images: None, prune_tropical=True)
        self.assertFalse(report['publishable'])
        self.assertEqual((report['updated_count'], report['pruned_tropical']), (0, []))
        self.assertFalse((self.base / 'store/current.json').exists())

    def test_history_and_tropical_removals_stay_in_their_own_fields(self):
        report = self.run_candidate(history_today=date(2026, 10, 22), prune_tropical=True)
        self.assertEqual(len(report['pruned_history']), 6)
        self.assertEqual(report['pruned_tropical'], orphan_paths())
        self.assertEqual(history_names(self.data(report)), sorted(f'images/{k}/history/{DAY}.json' for k in KINDS))

    def test_system_dropped_by_the_task_loses_its_files_in_the_same_run(self):
        def update(product, images):
            if product == 'tropical_official':
                write_json(Path(images).parent, OFFICIAL_INDEX_PATH, tt.no_storm_index(NOW))
        report = self.run_candidate(update=update, products=('tropical_official',), prune_tropical=True)
        self.assertTrue(report['publishable'])
        self.assertEqual(report['pruned_tropical'], sorted([*storm_files(KEPT), *storm_files(GONE)]))
        self.assertEqual(tropical_names(self.data(report)), [OFFICIAL_INDEX_PATH])

    def test_invalid_index_written_by_the_task_is_rolled_back_before_pruning(self):
        def update(product, images):
            bump_radar(images)
            (Path(images).parent / OFFICIAL_INDEX_PATH).write_text('{"broken": true}', encoding='utf-8')
            raise RuntimeError('task failed after a bad write')
        report = self.run_candidate(update=update, prune_tropical=True)
        # The validated previous index is restored, so only the true orphan goes.
        self.assertEqual(report['pruned_tropical'], orphan_paths())
        self.assertEqual((self.data(report) / OFFICIAL_INDEX_PATH).read_bytes(),
                         (self.seed / OFFICIAL_INDEX_PATH).read_bytes())

    def test_task_deleting_files_itself_is_still_undone_and_only_pruning_removes(self):
        def update(product, images):
            bump_radar(images)
            for name in storm_files(KEPT):
                (Path(images).parent / name).unlink()
        report = self.run_candidate(update=update, prune_tropical=True)
        names = tropical_names(self.data(report))
        for name in storm_files(KEPT):
            self.assertIn(name, names)
            self.assertEqual(report['resources'][name]['error_code'], 'invalid_output')


class PrepareDueTests(unittest.TestCase):
    def package(self, root, tropical):
        from src.pages_package import pack_snapshot
        from src.snapshots import export_snapshot
        write_seed(root / 'data', 2)
        add_past_days(root / 'data')
        if tropical == 'index':
            write_tropical(root / 'data', files=())
        elif tropical == 'files':
            write_tropical(root / 'data')
        export_snapshot(root / 'data', root / 'seed')
        return pack_snapshot(root / 'seed', root / 'input.zip', now=NOW)

    def prepare(self, root, mode, *, tropical='files', policy=None, change=True):
        from src.due_refresh import load_policy, prepare_due
        from src.history_reconciliation import current_history_context
        from src.scheduling import default_tasks
        package = self.package(root, tropical)

        def update(kind, images):
            if change:
                bump_radar(images)
            current_history_context().outcome(kind, latest_ok=True, history_state='complete')
        return prepare_due(root / 'input.zip', package['sha256'], root / 'work', mode=mode,
                           policy=policy or load_policy(), now=NOW,
                           task_config={'radar': default_tasks()['radar']}, update=update,
                           image_hasher=lambda resources, previous=None: dict(previous or {}))

    def test_refresh_prunes_whatever_the_history_policy(self):
        from src.due_refresh import load_policy
        keep = load_policy()
        keep['history']['keep_past_dates'] = True
        for name, policy in (('confirmed', None), ('keep_past_dates', keep)):
            with self.subTest(policy=name), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                root = Path(directory)
                result = self.prepare(root, 'refresh', policy=policy)
                self.assertEqual(result['pruned_tropical'], orphan_paths())
                self.assertEqual(len(result['pruned_history']), 0 if name == 'keep_past_dates' else 6)
                self.assertTrue(result['data_changed'])
                self.assertEqual(result['deployment_reason'], 'content_changed')
                self.assertEqual(tropical_names(root / 'work/site-data'),
                                 sorted([OFFICIAL_INDEX_PATH, *storm_files(KEPT)]))

    def test_publish_mode_keeps_everything(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            result = self.prepare(root, 'publish')
            self.assertEqual((result['pruned_tropical'], result['pruned_history']), ([], []))
            self.assertEqual(tropical_names(root / 'work/site-data'), tropical_names(root / 'data'))

    def test_refresh_with_only_removals_publishes_nothing(self):
        from src.due_refresh import load_policy
        policy = load_policy()
        policy['history']['keep_past_dates'] = True
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            result = self.prepare(root, 'refresh', policy=policy, change=False)
            self.assertFalse(result['publishable'])
            self.assertFalse(result['data_changed'])
            self.assertEqual(result['pruned_tropical'], [])
            self.assertEqual(result['deployment_reason'], 'no_content_change')

    def test_old_snapshot_shapes_restore_package_and_verify(self):
        for shape in ('none', 'index', 'files'):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                root = Path(directory)
                result = self.prepare(root, 'refresh', tropical=shape)
                self.assertTrue(result['publishable'])
                self.assertEqual(result['pruned_tropical'], orphan_paths() if shape == 'files' else [])
                files, invalid = read_resources(root / 'work/site-data')
                self.assertEqual(invalid, [])
                self.assertEqual(sorted(n for n in files if n.startswith('tropical/')),
                                 [] if shape == 'none' else
                                 [OFFICIAL_INDEX_PATH] if shape == 'index' else
                                 sorted([OFFICIAL_INDEX_PATH, *storm_files(KEPT)]))


class EntryPointTests(unittest.TestCase):
    def test_other_entry_points_never_ask_for_pruning(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('src/pages_refresh.py', 'update_snapshot.py', 'refresh_pages.py', 'src/local_updater.py'):
            path = root / name
            if path.exists():
                self.assertNotIn('prune_tropical', path.read_text(encoding='utf-8'), name)
        self.assertIn("prune_tropical=mode == 'refresh'", (root / 'src/due_refresh.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
