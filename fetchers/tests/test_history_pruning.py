"""Past-day history inventories are dropped on refresh (user-confirmed 2026-11-10).

Synthetic fixtures only; never reads live/public files or the network.
"""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from snapshot_fixtures import DAY, write_seed

KINDS = ('radar', 'satellite', 'rainfall')
PAST = ('2026-10-21', '2026-10-20')


def add_past_days(data, days=PAST):
    """Copy each fixture day inventory to earlier dates (valid, same shape)."""
    for kind in KINDS:
        text = (data / f'images/{kind}/history/{DAY}.json').read_text(encoding='utf-8')
        for day in days:
            (data / f'images/{kind}/history/{day}.json').write_text(text.replace(DAY, day), encoding='utf-8')


def bump_radar(images):
    """A real-looking successful radar update on the fixture day."""
    path = images / 'radar/latest.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['fetched_at'] = '2026-10-22T00:15:00+00:00'
    data['title'] += ' updated'
    path.write_text(json.dumps(data), encoding='utf-8')


def history_names(root):
    return sorted(p.relative_to(root).as_posix() for p in root.glob('images/*/history/*.json'))


class HistoryPruningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.seed = self.base / 'old'
        write_seed(self.seed, 2)
        add_past_days(self.seed)
        self.seed_before = {p: p.read_bytes() for p in self.seed.rglob('*.json')}

    def run_candidate(self, today, update=lambda product, images: bump_radar(images)):
        from src.snapshot_runner import run_candidate
        return run_candidate(['radar'], self.seed, self.base / 'store', update, history_today=today)

    def snapshot_data(self, report):
        return self.base / 'store/snapshots' / report['snapshot_id'] / 'data'

    def test_only_today_inventories_survive_and_others_untouched(self):
        report = self.run_candidate(date(2026, 10, 22))
        self.assertTrue(report['publishable'])
        self.assertEqual(sorted(report['pruned_history']),
                         sorted(f'images/{k}/history/{d}.json' for k in KINDS for d in PAST))
        data = self.snapshot_data(report)
        self.assertEqual(history_names(data), sorted(f'images/{k}/history/{DAY}.json' for k in KINDS))
        for name in ('images/rainfall/daily/latest.json', 'rainfall/rankings/latest.json',
                     'images/sst/latest.json', 'images/satellite/latest.json'):
            self.assertEqual((data / name).read_bytes(), (self.seed / name).read_bytes(), name)
        manifest = json.loads((data.parent / 'manifest.json').read_text(encoding='utf-8'))
        self.assertFalse(any('/history/2026-10-2' in name and DAY not in name for name in manifest['files']))
        self.assertNotIn('images/radar/history/2026-10-21.json', report['resources'])
        # The seed (restored archive copy) is never edited.
        self.assertEqual({p: p.read_bytes() for p in self.seed.rglob('*.json')}, self.seed_before)

    def test_latest_still_on_previous_day_keeps_that_inventory(self):
        # Just after Taipei midnight: today is 10-23 but every latest is still 10-22.
        report = self.run_candidate(date(2026, 10, 23))
        self.assertTrue(report['complete'])
        self.assertTrue(report['publishable'])
        data = self.snapshot_data(report)
        self.assertEqual(history_names(data), sorted(f'images/{k}/history/{DAY}.json' for k in KINDS))

    def test_disabled_by_default_keeps_every_inventory(self):
        from src.snapshot_runner import run_candidate
        report = run_candidate(['radar'], self.seed, self.base / 'store', lambda p, i: bump_radar(i))
        self.assertEqual(report['pruned_history'], [])
        self.assertEqual(len(history_names(self.snapshot_data(report))), 9)

    def test_pruning_alone_does_not_publish_or_move_pointer(self):
        report = self.run_candidate(date(2026, 10, 22), update=lambda product, images: None)
        self.assertEqual(report['pruned_history'], [])   # nothing ships, so nothing reported
        self.assertFalse(report['publishable'])
        self.assertFalse((self.base / 'store/current.json').exists())

    def test_failed_update_still_prunes_only_history_and_keeps_fallbacks(self):
        def fail(product, images):
            bump_radar(images)
            raise RuntimeError('source down after partial write')
        report = self.run_candidate(date(2026, 10, 22), update=fail)
        self.assertEqual(report['products'], {'radar': 'failed'})
        self.assertTrue(all(r['state'] != 'no_data' for r in report['resources'].values()))
        # The partially written radar latest is kept as a sub-resource success; it
        # stays on the fixture day, so pruning still removes exactly the past days.
        self.assertTrue(report['publishable'])
        self.assertEqual(len(report['pruned_history']), 6)
        data = self.snapshot_data(report)
        self.assertEqual(history_names(data), sorted(f'images/{k}/history/{DAY}.json' for k in KINDS))
        for name in ('images/satellite/latest.json', 'images/rainfall/daily/latest.json'):
            self.assertEqual((data / name).read_bytes(), (self.seed / name).read_bytes())

    def test_only_exact_history_paths_are_touched(self):
        from src.snapshot_runner import _prune_past_history
        root = self.base / 'tree'
        write_seed(root, 2)
        add_past_days(root)
        stray = root / 'images/radar/history/readme.txt'
        stray.write_text('keep', encoding='utf-8')
        other = root / 'images/sst/history'
        other.mkdir(parents=True)
        (other / '2026-10-01.json').write_text('{}', encoding='utf-8')
        pruned = _prune_past_history(root, date(2026, 10, 22))
        self.assertEqual(len(pruned), 6)
        self.assertTrue(stray.exists())
        self.assertTrue((other / '2026-10-01.json').exists())


class PrepareDuePruningTests(unittest.TestCase):
    def package(self, root, now):
        from src.pages_package import pack_snapshot
        from src.snapshots import export_snapshot
        write_seed(root / 'data', 2)
        add_past_days(root / 'data')
        export_snapshot(root / 'data', root / 'seed')
        return pack_snapshot(root / 'seed', root / 'input.zip', now=now)

    def prepare(self, root, mode, policy, now):
        from src.due_refresh import prepare_due
        from src.history_reconciliation import current_history_context
        from src.scheduling import default_tasks
        package = self.package(root, now)
        def update(kind, images):
            bump_radar(images)
            current_history_context().outcome(kind, latest_ok=True, history_state='complete')
        return prepare_due(root / 'input.zip', package['sha256'], root / 'work', mode=mode, policy=policy,
                           now=now, task_config={'radar': default_tasks()['radar']}, update=update)

    def test_confirmed_policy_drops_past_days_on_refresh_using_taipei_date(self):
        from src.due_refresh import load_policy
        policy = load_policy()
        self.assertIs(policy['history']['keep_past_dates'], False)
        # 2026-10-21T16:30Z is already 10-22 00:30 in Taipei.
        now = datetime(2026, 10, 21, 16, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            result = self.prepare(root, 'refresh', policy, now)
            self.assertEqual(len(result['pruned_history']), 6)
            self.assertTrue(result['data_changed'])
            self.assertEqual(history_names(root / 'work/site-data'),
                             sorted(f'images/{k}/history/{DAY}.json' for k in KINDS))

    def test_publish_mode_and_absent_flag_keep_past_days(self):
        from src.due_refresh import load_policy
        now = datetime(2026, 10, 21, 16, 30, tzinfo=timezone.utc)
        legacy = load_policy()
        legacy['history'] = {k: v for k, v in legacy['history'].items() if k != 'keep_past_dates'}
        for mode, policy in (('publish', load_policy()), ('refresh', legacy)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                root = Path(directory)
                result = self.prepare(root, mode, policy, now)
                self.assertEqual(result['pruned_history'], [])


if __name__ == '__main__':
    unittest.main()
