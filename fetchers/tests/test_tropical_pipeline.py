"""tropical_official inside the due pipeline: isolation from the 13 image tasks.

Synthetic seed, fixed instants, fake transport; the network is blocked.
"""
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tropical_testing as tt
from snapshot_fixtures import write_seed
from tropical_testing import (CWA_URL, JMA_FEED, JMA_LONG, JMA_TARGET, JTWC_RSS, SECRET, FakeTransport,
                              quiet_policy)

from src import tropical_official as official
from src.due_refresh import deployment_decision, load_policy, prepare_due
from src.http_client import SourceBudgetExceeded, http_scope
from src.scheduling import default_tasks
from src.snapshot_runner import belongs
from src.snapshots import REQUIRED, read_resources
from src.tropical_contract import OFFICIAL_INDEX_PATH

UTC = timezone.utc
NOW = datetime(2026, 10, 22, 2, 0, tzinfo=UTC)  # the synthetic seed's day, 10:00 in Taipei
IMAGE_TASKS = [kind for kind in default_tasks() if not kind.startswith('tropical_')]
# Most cases need only a few image tasks beside the tropical one; the full set
# is used where "all 13" is the point.
FEW = ('sst', 'radar', 'rainfall_rankings')


def subset(*kinds):
    tasks = default_tasks()
    return {kind: tasks[kind] for kind in kinds}


def setUpModule():
    tt.block_network()


def tearDownModule():
    tt.unblock_network()


def keep_hashes(resources, previous=None):
    """Image hasher stand-in: the synthetic images all carry an image time."""
    keep_hashes.seen.extend(resources)
    return dict(previous or {})


keep_hashes.seen = []


def package(root, *, tropical=None):
    from src.pages_package import pack_snapshot
    from src.snapshots import export_snapshot
    write_seed(root / 'data', 2)
    if tropical is not None:
        path = root / 'data' / OFFICIAL_INDEX_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(tropical, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    export_snapshot(root / 'data', root / 'seed')
    return pack_snapshot(root / 'seed', root / 'input.zip', now=NOW)


def tropical_ok(routes=None, now=None):
    def update(kind, images):
        return official.update_tropical_official(
            Path(images).parent, now=now or update.now, transport=FakeTransport(routes or tt.no_storm_routes()),
            wait=lambda seconds: None, clock=lambda: 0.0, api_key=SECRET, policy=quiet_policy())
    update.now = NOW
    return update


def tropical_fails(kind, images):
    raise RuntimeError('private tropical failure')


def make_update(tropical, *, change=(), fail=()):
    calls = []

    def update(kind, images):
        calls.append(kind)
        if kind.startswith('tropical_'):
            return tropical(kind, images)
        if kind in fail:
            raise RuntimeError('private image failure')
        if kind in change:
            path = Path(images) / kind / 'latest.json'
            data = json.loads(path.read_bytes())
            data['title'] += ' changed'
            path.write_text(json.dumps(data), encoding='utf-8')
    update.calls = calls
    return update


def prepare(root, name, update, *, tasks=None, now=NOW, state=None, online=None, sha=None, archive=None):
    keep_hashes.seen = []
    return prepare_due(archive or root / 'input.zip', sha, root / name, mode='refresh', policy=load_policy(),
                       task_config=tasks, update=update, now=now, state_document=state,
                       image_hasher=keep_hashes, deployment_document=online)


def image_view(result, root, name, kinds=tuple(IMAGE_TASKS)):
    """Everything about the 13 image tasks that a tropical failure must not change."""
    data = root / name / ('site-data' if (root / name / 'site-data').exists() else 'seed')
    files, _ = read_resources(data)
    scheduler = result['scheduler_state']['scheduler']['tasks']
    return {
        'files': {path: content for path, content in files.items() if not path.startswith('tropical/')},
        'checks': {kind: result['checks'][kind] for kind in kinds},
        'scheduler': {kind: scheduler[kind] for kind in kinds},
        'resources': {path: value for path, value in result['resources'].items() if not path.startswith('tropical/')},
        'products': {kind: value for kind, value in result['products'].items() if kind in kinds},
        'history': result['scheduler_state']['history'],
    }


class BelongsTests(unittest.TestCase):
    def test_prefixes_do_not_overlap_image_products(self):
        self.assertTrue(belongs(OFFICIAL_INDEX_PATH, 'tropical_official'))
        self.assertTrue(belongs('tropical/official/storms/x/analysis.json', 'tropical_official'))
        self.assertFalse(belongs('tropical/models/index.json', 'tropical_official'))
        self.assertFalse(belongs('images/tropical_official/latest.json', 'tropical_official'))
        for kind in IMAGE_TASKS:
            self.assertFalse(belongs(OFFICIAL_INDEX_PATH, kind), kind)
        self.assertTrue(belongs('images/radar/latest.json', 'radar'))
        self.assertTrue(belongs('rainfall/rankings/latest.json', 'rainfall_rankings'))

    def test_task_is_last_and_matches_the_design_schedule(self):
        tasks = default_tasks()
        # Official before models: the models task reads the official index (design.md 5.1).
        self.assertEqual(list(tasks)[-2:], ['tropical_official', 'tropical_models'])
        self.assertEqual(len(IMAGE_TASKS), 13)
        self.assertEqual(tasks['tropical_official'], {'mode': 'interval', 'interval_seconds': 1800,
                                                      'retry_delays_seconds': [600, 1200, 2400, 3600]})


class IsolationTests(unittest.TestCase):
    def test_tropical_failure_leaves_image_files_hashes_and_schedule_unchanged(self):
        cases = (('all 13: one changed, one failed', IMAGE_TASKS, ('sst',), ('radar',)),
                 ('unchanged images', FEW, (), ()), ('all images failed', FEW, (), FEW))
        for label, kinds, change, fail in cases:
            with self.subTest(label), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                root = Path(directory)
                sha = package(root)['sha256']
                with_tropical = prepare(root, 'with', make_update(tropical_fails, change=change, fail=fail),
                                        tasks=subset(*kinds, 'tropical_official'), sha=sha)
                control = prepare(root, 'control', make_update(tropical_fails, change=change, fail=fail),
                                  tasks=subset(*kinds), sha=sha)
                self.assertEqual(image_view(with_tropical, root, 'with', kinds),
                                 image_view(control, root, 'control', kinds))
                for field in ('deploy', 'save_snapshot', 'data_changed', 'deployment_reason', 'content_id', 'reason'):
                    self.assertEqual(with_tropical[field], control[field], field)
                self.assertEqual(with_tropical.get('image_hashes'), control.get('image_hashes'))
                check = with_tropical['checks']['tropical_official']
                self.assertEqual((check['state'], check['error_code']), ('retained_after_failure', 'source_error'))
                task = with_tropical['scheduler_state']['scheduler']['tasks']['tropical_official']
                self.assertEqual((task['consecutive_failures'], task['next_retry_at']), (1, '2026-10-22T02:10:00Z'))
                self.assertEqual(with_tropical['products']['tropical_official'], 'failed')
                self.assertFalse(any(path.startswith('tropical/') for path in with_tropical['resources']))
                self.assertNotIn('private tropical failure', json.dumps(with_tropical))

    def test_all_sources_failed_keeps_the_previous_index_bytes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            previous = tt.no_storm_index(NOW - timedelta(hours=1))
            sha = package(root, tropical=previous)['sha256']
            before = (root / 'seed/data' / OFFICIAL_INDEX_PATH).read_bytes()
            routes = {CWA_URL: 403, JMA_FEED: 404, JTWC_RSS: 403}
            result = prepare(root, 'work', make_update(tropical_ok(routes), change=('sst',)),
                             tasks=subset('sst', 'tropical_official'), sha=sha)
            self.assertEqual(result['checks']['tropical_official']['state'], 'retained_after_failure')
            self.assertTrue(result['deploy'])  # the image change still ships
            self.assertEqual((root / 'work/site-data' / OFFICIAL_INDEX_PATH).read_bytes(), before)
            self.assertEqual(result['resources'][OFFICIAL_INDEX_PATH]['state'], 'retained')

    def test_invalid_tropical_output_is_rolled_back_without_touching_images(self):
        def broken(kind, images):
            path = Path(images).parent / OFFICIAL_INDEX_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"storms": [[]]}', encoding='utf-8')
            stray = Path(images).parent / 'tropical/official/storms/x/analysis.json'
            stray.parent.mkdir(parents=True)
            stray.write_text('{}', encoding='utf-8')
            return {}
        for seeded in (False, True):
            with self.subTest(seeded=seeded), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                root = Path(directory)
                sha = package(root, tropical=tt.no_storm_index(NOW - timedelta(hours=1)) if seeded else None)['sha256']
                result = prepare(root, 'work', make_update(broken, change=('sst',)),
                                 tasks=subset('sst', 'tropical_official'), sha=sha)
                self.assertEqual(result['checks']['tropical_official']['state'], 'retained_after_failure')
                self.assertTrue(result['deploy'])
                files, _ = read_resources(root / 'work/site-data')
                self.assertEqual(OFFICIAL_INDEX_PATH in files, seeded)
                self.assertFalse(any('storms' in path for path in files))
                self.assertTrue(all(name in files for name in REQUIRED))

    def test_successful_task_adds_only_its_index_and_is_not_hashed_or_reformatted(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            sha = package(root)['sha256']
            seed_files, _ = read_resources(root / 'seed/data')
            result = prepare(root, 'work', make_update(tropical_ok()), tasks=subset(*FEW, 'tropical_official'), sha=sha)
            self.assertEqual(result['checks']['tropical_official']['state'], 'updated')
            self.assertTrue(result['data_changed'] and result['deploy'])
            files, _ = read_resources(root / 'work/site-data')
            self.assertEqual({path: content for path, content in files.items() if path != OFFICIAL_INDEX_PATH}, seed_files)
            index = json.loads(files[OFFICIAL_INDEX_PATH])
            self.assertEqual((index['status'], index['fetched_at']), ('OK_NO_STORMS', '2026-10-22T02:00:00Z'))
            # No image hashing for tropical resources, and no image hash recorded.
            self.assertFalse(any(name.startswith('tropical/') for name in keep_hashes.seen))
            self.assertEqual(result['content']['image_hashes'], {})
            self.assertNotIn(SECRET, json.dumps(result, ensure_ascii=False))

    def test_tropical_bytes_are_not_rewritten_in_another_layout(self):
        compact = json.dumps(tt.no_storm_index(NOW), separators=(',', ':')).encode()

        def compact_writer(kind, images):
            path = Path(images).parent / OFFICIAL_INDEX_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(compact)
            return {}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            sha = package(root)['sha256']
            prepare(root, 'work', make_update(compact_writer), tasks=subset('tropical_official'), sha=sha)
            self.assertEqual((root / 'work/site-data' / OFFICIAL_INDEX_PATH).read_bytes(), compact)

    def test_recheck_in_same_minute_is_discarded_and_heartbeat_change_is_kept(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            sha = package(root)['sha256']
            tasks = {'tropical_official': default_tasks()['tropical_official']}
            first = prepare(root, 'first', make_update(tropical_ok()), tasks=tasks, sha=sha)
            archive, sha2 = root / 'first/output/weather-snapshot.zip', first['sha256']
            saved = (root / 'first/site-data' / OFFICIAL_INDEX_PATH).read_bytes()
            # Same minute, different second: only fetched_at differs -> old bytes, no new version.
            soon = tropical_ok()
            soon.now = NOW + timedelta(seconds=40)
            again = prepare(root, 'again', make_update(soon), tasks=tasks, now=NOW + timedelta(seconds=40),
                            sha=sha2, archive=archive)
            self.assertEqual(again['checks']['tropical_official']['state'], 'checked_unchanged')
            self.assertFalse(again['data_changed'])
            self.assertEqual((root / 'again/seed' / OFFICIAL_INDEX_PATH).read_bytes(), saved)
            # Not due 29 minutes later; due after 30, and the heartbeat is real content.
            state = first['scheduler_state']
            waiting = prepare(root, 'waiting', make_update(tropical_ok()), tasks=tasks, state=state,
                              now=NOW + timedelta(minutes=29), sha=sha2, archive=archive)
            self.assertEqual(waiting['checks']['tropical_official']['state'], 'not_due')
            later = tropical_ok()
            later.now = NOW + timedelta(minutes=30)
            due = prepare(root, 'due', make_update(later), tasks=tasks, state=state,
                          now=NOW + timedelta(minutes=30), sha=sha2, archive=archive)
            self.assertEqual(due['checks']['tropical_official']['state'], 'updated')
            self.assertTrue(due['data_changed'])

    def test_adding_the_task_resets_the_schedule_once(self):
        from src.cloud_snapshots import validate_state
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            sha = package(root)['sha256']
            old_tasks = subset(*IMAGE_TASKS)
            before = prepare(root, 'before', make_update(tropical_fails), tasks=old_tasks, sha=sha)
            self.assertEqual(before['state_warning'], 'missing')
            old_state = before['scheduler_state']
            # The pre-tropical state restores cleanly under the pre-tropical task set...
            same = prepare(root, 'same', make_update(tropical_fails), tasks=old_tasks, state=old_state,
                           now=NOW + timedelta(minutes=1), sha=sha)
            self.assertIsNone(same['state_warning'])
            self.assertEqual(same['checks']['radar']['state'], 'not_due')
            # ...and is rejected once the task set includes the tropical tasks: everything is due once
            # (S8 adds tropical_models, design.md 5.1).
            update = make_update(tropical_ok())
            after = prepare(root, 'after', update, state=old_state, now=NOW + timedelta(minutes=1), sha=sha)
            self.assertEqual(after['state_warning'], 'corrupt')
            self.assertEqual(update.calls, [*IMAGE_TASKS, 'tropical_official', 'tropical_models'])
            with self.assertRaises(ValueError):
                validate_state(json.dumps(old_state).encode(), old_state['content_id'], NOW + timedelta(minutes=1))
            validate_state(json.dumps(after['scheduler_state']).encode(), after['content_id'], NOW + timedelta(minutes=2))


STORM_ANALYSIS = 'tropical/official/storms/2026-jma-tc2638/analysis.json'
STORM_FORECAST = 'tropical/official/storms/2026-jma-tc2638/forecast.json'


class StormFilePipelineTests(unittest.TestCase):
    """analysis.json / forecast.json through checked_update and run_candidate (design.md 5.2, 5.5, 11b #1)."""

    def first(self, root):
        sha = package(root)['sha256']
        tasks = subset('sst', 'tropical_official')
        cempaka = tropical_ok(tt.cempaka_routes(), now=tt.NOW)
        result = prepare(root, 'first', make_update(cempaka), tasks=tasks, sha=sha)
        return result, tasks

    def test_storm_files_are_published_unhashed_in_their_own_layout(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            result, _ = self.first(root)
            seed_files, _ = read_resources(root / 'seed/data')
            self.assertEqual(result['checks']['tropical_official']['state'], 'updated')
            files, _ = read_resources(root / 'first/site-data')
            for name in (OFFICIAL_INDEX_PATH, STORM_ANALYSIS, STORM_FORECAST):
                self.assertIn(name, files)
                self.assertEqual(result['resources'][name]['state'], 'updated')
                # atomic_write_json layout, untouched by the image hash rewrite.
                self.assertEqual(files[name], (json.dumps(json.loads(files[name]), ensure_ascii=False, indent=2)
                                               + '\n').encode('utf-8'))
            self.assertEqual({k: v for k, v in files.items() if not k.startswith('tropical/')}, seed_files)
            self.assertFalse(any(name.startswith('tropical/') for name in keep_hashes.seen))
            self.assertEqual(result['content']['image_hashes'], {})
            self.assertNotIn(SECRET, json.dumps(result, ensure_ascii=False))

    def test_rewrite_that_only_changes_fetched_at_is_discarded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            first, tasks = self.first(root)
            saved = {name: (root / 'first/site-data' / name).read_bytes() for name in (STORM_ANALYSIS, STORM_FORECAST)}
            again = tropical_ok(tt.cempaka_routes(), now=tt.NOW + timedelta(seconds=40))
            result = prepare(root, 'again', make_update(again), tasks=tasks, now=NOW + timedelta(seconds=40),
                             sha=first['sha256'], archive=root / 'first/output/weather-snapshot.zip')
            # (The index itself changes here: match "name" becomes "id" on the second run, 11a.)
            for name, content in saved.items():
                self.assertEqual((root / 'again/site-data' / name).read_bytes(), content)
                self.assertEqual(result['resources'][name]['state'], 'retained')

    def test_write_failure_rolls_back_the_whole_prefix_and_spares_images(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            first, tasks = self.first(root)
            archive = root / 'first/output/weather-snapshot.zip'
            before = {name: (root / 'first/site-data' / name).read_bytes()
                      for name in (OFFICIAL_INDEX_PATH, STORM_ANALYSIS, STORM_FORECAST)}
            real = official.atomic_write_json

            def failing(data, path, prefix):
                if Path(path).name == 'forecast.json':
                    raise OSError('disk full')
                return real(data, path, prefix=prefix)
            later = tropical_ok(tt.cempaka_routes(), now=tt.NOW + timedelta(hours=1))
            with patch.object(official, 'atomic_write_json', failing):
                result = prepare(root, 'second', make_update(later, change=('sst',)), tasks=tasks,
                                 now=NOW + timedelta(hours=1), sha=first['sha256'], archive=archive)
            self.assertEqual(result['checks']['tropical_official']['state'], 'retained_after_failure')
            self.assertTrue(result['deploy'])  # the image change still ships
            for name, content in before.items():
                self.assertEqual((root / 'second/site-data' / name).read_bytes(), content, name)
            files, _ = read_resources(root / 'second/site-data')
            self.assertIn(' changed', json.loads(files['images/sst/latest.json'])['title'])

    def test_invalid_storm_file_on_disk_rolls_the_prefix_back(self):
        def writes_bad_storm_file(kind, images):
            index = official.update_tropical_official(
                Path(images).parent, now=tt.NOW, transport=FakeTransport(tt.cempaka_routes()),
                wait=lambda seconds: None, clock=lambda: 0.0, api_key=SECRET, policy=quiet_policy())
            (Path(images).parent / STORM_FORECAST).write_text('{"schema_version": 1}', encoding='utf-8')
            return index
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            sha = package(root, tropical=tt.no_storm_index(NOW - timedelta(hours=1)))['sha256']
            before = (root / 'seed/data' / OFFICIAL_INDEX_PATH).read_bytes()
            result = prepare(root, 'work', make_update(writes_bad_storm_file, change=('sst',)),
                             tasks=subset('sst', 'tropical_official'), sha=sha)
            self.assertEqual(result['checks']['tropical_official']['state'], 'retained_after_failure')
            files, _ = read_resources(root / 'work/site-data')
            self.assertEqual(files[OFFICIAL_INDEX_PATH], before)
            self.assertFalse(any('/storms/' in name for name in files))
            self.assertTrue(result['deploy'])


CONTENT = {'content_id': 'a' * 64, 'content_created_at': '2026-11-02T10:00:00+00:00'}
ONLINE = {'state': 'verified', 'marker': {'content_id': 'b' * 64}, 'content_created_at': '2026-11-02T09:00:00+00:00'}
OK, FAILED, IDLE = {'state': 'checked_unchanged'}, {'state': 'retained_after_failure'}, {'state': 'not_due'}
UPDATED = {'state': 'updated'}


class DeploymentDecisionTests(unittest.TestCase):
    """The combination table of design.md 5.5."""

    def decide(self, changed, checks, products=None, online=ONLINE):
        return deployment_decision('refresh', changed, CONTENT, checks, online, products=products)

    def test_combination_table(self):
        table = [
            ('images ok, tropical failed, image content changed',
             True, {'sst': UPDATED, 'tropical_official': FAILED}, (True, 'content_changed')),
            ('images ok, tropical failed, nothing changed',
             False, {'sst': OK, 'tropical_official': FAILED}, (True, 'saved_version_not_online')),
            ('images all failed, tropical ok and unchanged',
             False, {'sst': FAILED, 'radar': FAILED, 'tropical_official': OK}, (False, 'all_source_checks_failed')),
            ('images all failed, tropical failed',
             False, {'sst': FAILED, 'tropical_official': FAILED}, (False, 'all_source_checks_failed')),
            ('images all failed, tropical changed',
             True, {'sst': FAILED, 'tropical_official': UPDATED}, (True, 'content_changed')),
            ('no image task due, tropical failed',
             False, {'sst': IDLE, 'radar': IDLE, 'tropical_official': FAILED}, (True, 'saved_version_not_online')),
            ('no image task due, tropical changed',
             True, {'sst': IDLE, 'tropical_official': UPDATED}, (True, 'content_changed')),
        ]
        for label, changed, checks, expected in table:
            with self.subTest(label):
                self.assertEqual(self.decide(changed, checks), expected)

    def test_decision_equals_the_one_without_tropical_tasks(self):
        states = (OK, FAILED, IDLE, UPDATED, {'state': 'history_recheck'})
        product_states = ('success', 'failed')
        for sst in states:
            for radar in states:
                for tropical in states:
                    for changed in (False, True):
                        for image_product in product_states:
                            for tropical_product in product_states:
                                images = {'sst': sst, 'radar': radar}
                                products = {'sst': image_product}
                                expected = self.decide(changed, images, products)
                                actual = self.decide(changed, dict(images, tropical_official=tropical, tropical_models=tropical),
                                                     dict(products, tropical_official=tropical_product))
                                self.assertEqual(actual, expected)

    def test_products_rule_ignores_tropical_products(self):
        # Every image product failed and tropical succeeded: still "all failed".
        self.assertEqual(self.decide(False, {}, {'sst': 'failed', 'tropical_official': 'success'}),
                         (False, 'all_source_checks_failed'))
        # Only a tropical product ran and failed: same as nothing having run.
        self.assertEqual(self.decide(False, {}, {'tropical_official': 'failed'}), self.decide(False, {}, {}))

    def test_earlier_online_checks_are_unchanged(self):
        same = dict(ONLINE, marker={'content_id': CONTENT['content_id']})
        self.assertEqual(self.decide(True, {'tropical_official': UPDATED}, online=same), (False, 'already_online'))
        self.assertEqual(self.decide(True, {'tropical_official': UPDATED}, online={'state': 'unavailable'}),
                         (False, 'online_unavailable'))
        self.assertEqual(deployment_decision('publish', False, CONTENT, {'tropical_official': FAILED}, ONLINE),
                         (True, 'explicit_publish'))


JMA_OTHER = 'https://www.data.jma.go.jp/developer/xml/other.xml'
CWA_OTHER = 'https://www.cwa.gov.tw/other'


class HttpScopeTests(unittest.TestCase):
    """design.md 5.4: the task's request budget is separate from the surrounding run in both directions."""

    def run_task(self, routes, policy=None, **options):
        return official.collect(None, tt.NOW, transport=FakeTransport(routes), wait=lambda seconds: None,
                                clock=lambda: 0.0, api_key=SECRET, policy=policy, **options)

    def test_outer_exhausted_or_blocked_budget_does_not_stop_the_task(self):
        outer = quiet_policy(max_requests=1)
        plain = FakeTransport({JMA_OTHER: b'x', CWA_OTHER: b'y'})
        with http_scope(outer):
            outer.get(JMA_OTHER, transport=plain)
            outer.get(CWA_OTHER, transport=plain)
            outer.sources['jma']['blocked'] = True
            with self.assertRaises(SourceBudgetExceeded):
                outer.get(JMA_OTHER, transport=plain)
            with self.assertRaises(SourceBudgetExceeded):
                outer.get(CWA_OTHER, transport=plain)
            snapshot = json.dumps(outer.sources, sort_keys=True)
            # Default policy path: the task builds its own fresh HttpPolicy.
            results = self.run_task(tt.no_storm_routes())
            self.assertEqual({agency: result.state for agency, result in results.items()},
                             {'cwa': 'ok', 'jma': 'ok', 'jtwc': 'ok'})
            # The outer budgets were neither read nor changed, and are still exhausted afterwards.
            self.assertEqual(json.dumps(outer.sources, sort_keys=True), snapshot)
            self.assertNotIn('jtwc', outer.sources)
            with self.assertRaises(SourceBudgetExceeded):
                outer.get(JMA_OTHER, transport=plain)

    def test_task_exhausting_or_blocking_a_source_leaves_the_outer_scope_usable(self):
        outer = quiet_policy()
        plain = FakeTransport({JMA_OTHER: b'x', CWA_OTHER: b'y'})
        with http_scope(outer):
            outer.get(JMA_OTHER, transport=plain)
            snapshot = json.dumps(outer.sources, sort_keys=True)
            # Inside the task: JMA is driven into "blocked" (repeated 5xx), CWA runs out of requests.
            blocked = self.run_task(dict(tt.no_storm_routes(), **{JMA_FEED: 503}), policy=quiet_policy())
            self.assertEqual((blocked['jma'].state, blocked['cwa'].state), ('failed', 'ok'))
            starved = self.run_task(tt.no_storm_routes(), policy=quiet_policy(max_requests=1))
            self.assertEqual(starved['jma'].state, 'failed')  # feed used the only request; targetTc and long feed refused
            self.assertEqual(json.dumps(outer.sources, sort_keys=True), snapshot)
            self.assertEqual(outer.get(JMA_OTHER, transport=plain).content, b'x')
            self.assertEqual(outer.get(CWA_OTHER, transport=plain).content, b'y')
            self.assertFalse(outer.sources['jma']['blocked'])

    def test_scope_is_restored_after_the_task_even_when_it_fails(self):
        from src import http_client
        outer = quiet_policy()
        with http_scope(outer):
            with self.assertRaises(official.AllSourcesFailed):
                official.update_tropical_official(Path('unused'), now=tt.NOW, api_key=SECRET, policy=quiet_policy(),
                                                  transport=FakeTransport({CWA_URL: 403, JMA_FEED: 403, JTWC_RSS: 403}),
                                                  wait=lambda seconds: None, clock=lambda: 0.0)
            self.assertIs(http_client._policy.get(), outer)
        self.assertIsNone(http_client._policy.get())

    def test_jtwc_host_has_its_own_source_name(self):
        from src.http_client import source_name
        self.assertEqual(source_name(JTWC_RSS), 'jtwc')
        self.assertEqual(source_name('https://www.metoc.navy.mil/jtwc/products/wp3126.tcw'), 'jtwc')
        self.assertEqual(source_name(JMA_TARGET), source_name(JMA_LONG))
        self.assertEqual(source_name('https://nomads.ncep.noaa.gov/x'), 'noaa')  # S8 (design.md 11e E7)


class EntryPointTests(unittest.TestCase):
    def test_update_image_dispatches_to_the_data_root_next_to_images(self):
        import update_images
        seen = []
        with patch.dict(update_images.TROPICAL_TASKS, {'tropical_official': lambda root: seen.append(root) or {'ok': True}}):
            self.assertEqual(update_images.update_image('tropical_official', Path('some/data/images')), {'ok': True})
        self.assertEqual(seen, [Path('some/data')])
        self.assertIs(update_images.TROPICAL_TASKS['tropical_official'], official.update_tropical_official)

    def test_unknown_names_still_fail_and_images_are_not_touched(self):
        import update_images
        with self.assertRaises(KeyError):
            update_images.update_image('tropical_ensemble', Path('x/images'))  # S9

    def test_tropical_tasks_are_not_enumerated_as_image_products(self):
        import update_images
        from src.snapshots import IMAGE_TYPES
        registered = update_images.registered_products()
        self.assertEqual(set(registered), set(IMAGE_TASKS))
        self.assertFalse(any(name.startswith('tropical') for name in (*registered, *IMAGE_TYPES)))

    def test_local_cli_runs_the_task_only_when_named(self):
        import update_images
        ran = []

        def fake_batch(types, output_root, update, *args, **kwargs):
            ran.append(list(types))
            return 0
        with patch.object(update_images, 'run_batch', fake_batch), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = str(Path(directory) / 'images')
            self.assertEqual(update_images.main(['--output-root', output]), 0)
            self.assertEqual(update_images.main(['tropical_official', '--output-root', output]), 0)
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                update_images.main(['tropical_ensemble', '--output-root', output])
            self.assertEqual(update_images.main(['tropical_models', '--output-root', output]), 0)
        self.assertEqual(set(ran[0]), set(IMAGE_TASKS))
        self.assertEqual(ran[1:], [['tropical_official'], ['tropical_models']])


if __name__ == '__main__':
    unittest.main()
