"""Execute validated event inputs and check the workflow's shared wiring."""
from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import refresh_pages

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/pages-manual.yml'


class ScheduleEventTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load(WORKFLOW.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        self.build = self.workflow['jobs']['build']
        self.steps = self.build['steps']

    def event_env(self, event, inputs):
        # Interpret this small, intentionally fixed GitHub expression shape,
        # using the literal values and input names from the real workflow.
        env = {}
        for key in ('SOURCE_MODE', 'MODE', 'RETENTION_DAYS'):
            expression = self.build.get('env', {}).get(key, '')
            match = re.fullmatch(r"\$\{\{ inputs\.([a-z_]+) \}\}", expression)
            self.assertIsNotNone(match, f'{key} must use dispatched inputs')
            env[key] = str(inputs.get(match[1], ''))
        for key, name in {'SOURCE_RUN':'snapshot_run_id', 'RELEASE_TAG':'snapshot_release',
                          'ASSET_NAME':'snapshot_asset', 'ASSET_SHA':'snapshot_sha256'}.items():
            env[key] = str(inputs.get(name, ''))
        return env

    def check_inputs(self, env):
        with patch.dict(os.environ, env, clear=True), redirect_stderr(io.StringIO()):
            return refresh_pages.main(['inputs'])

    def test_schedule_has_explicit_auto_refresh_seven_day_inputs(self):
        from chain_controller import Controller, PUBLISH
        import test_chain_controller as fixtures
        api = fixtures.FakeAPI()
        settings = dict(GITHUB_REPOSITORY='owner/repo', DEFAULT_BRANCH='main',
                        GITHUB_REF='refs/heads/main', GITHUB_RUN_ID='10',
                        GITHUB_RUN_ATTEMPT='1', GITHUB_EVENT_NAME='schedule')
        controller = Controller(api, settings, report=lambda *_: None)
        controller.dispatch(PUBLISH, dict(snapshot_source='auto', mode='refresh',
                            snapshot_retention_days='15', chain_request_id='u10a1'),
                            'Pages chain u10a1', fixtures.NOW)
        env = self.event_env('workflow_dispatch', api.posts[0][1]['inputs'])
        self.assertEqual((env['SOURCE_MODE'], env['MODE'], env['RETENTION_DAYS']), ('auto','refresh','15'))
        self.assertEqual(self.check_inputs(env), 0)

    def test_manual_publish_refresh_and_explicit_sources_keep_input_validation(self):
        for mode in ('publish', 'refresh'):
            for source, extra in (('auto', {}),
                                  ('explicit', {'snapshot_run_id':'123','snapshot_sha256':'a'*64}),
                                  ('explicit', {'snapshot_release':'backup','snapshot_asset':'data.zip','snapshot_sha256':'a'*64})):
                with self.subTest(mode=mode, source=source, extra=extra):
                    env = self.event_env('workflow_dispatch', dict(snapshot_source=source, mode=mode,
                        snapshot_retention_days=15, **extra))
                    self.assertEqual((env['SOURCE_MODE'], env['MODE']), (source,mode))
                    self.assertEqual(self.check_inputs(env), 0)
        for extra in ({'mode':''}, {'snapshot_retention_days':0}, {'snapshot_retention_days':6}, {'snapshot_retention_days':7},
                      {'snapshot_run_id':'123'}, {'snapshot_source':''}):
            with self.subTest(invalid=extra):
                inputs=dict(snapshot_source='auto',mode='refresh',snapshot_retention_days=15)
                inputs.update(extra)
                self.assertEqual(self.check_inputs(self.event_env('workflow_dispatch', inputs)), 1)

    def test_restore_marker_secret_and_retention_use_shared_event_settings(self):
        self.assertEqual(self.workflow['on']['workflow_dispatch']['inputs']['mode']['default'], 'publish')
        resolve = next(s for s in self.steps if s.get('id') == 'resolve')
        prepare = next(s for s in self.steps if s.get('id') == 'snapshot')
        online = next(s for s in self.steps if 'manage_snapshots.py deployment' in s.get('run',''))
        self.assertEqual(resolve['if'], "env.SOURCE_MODE == 'auto'")
        self.assertEqual(online['if'], "env.MODE == 'refresh'")
        self.assertEqual(prepare['env']['CWA_API_KEY'], "${{ env.MODE == 'refresh' && secrets.CWA_API_KEY || '' }}")
        for step in self.steps:
            self.assertFalse({'SOURCE_MODE','MODE','RETENTION_DAYS'} & set(step.get('env', {})), step.get('name'))
            if step.get('uses','').startswith('actions/upload-artifact@'):
                # Data snapshots follow the shared 15-day setting; state stays 7 days.
                expected = '7' if step['with']['name'] == 'weather-scheduler-state' else '${{ env.RETENTION_DAYS }}'
                self.assertEqual(step['with']['retention-days'], expected, step.get('name'))
            if 'inputs.snapshot_source' in step.get('if','') or 'inputs.mode' in step.get('if',''):
                self.fail('Event-specific branches must use normalized settings')
        self.assertEqual(self.workflow['concurrency'], {'group':'pages-manual','cancel-in-progress':'false'})
        for step in self.steps:
            if 'manage_snapshots.py guard' in step.get('run',''):
                self.assertNotIn('if',step)

    def test_schedule_missing_key_stops_before_source_update_or_outputs(self):
        env = self.event_env('workflow_dispatch', dict(snapshot_source='auto', mode='refresh', snapshot_retention_days=15))
        with patch.dict(os.environ,env,clear=True), redirect_stderr(io.StringIO()), \
             patch.object(refresh_pages,'prepare_due') as prepare:
            self.assertEqual(refresh_pages.main(['prepare']),1)
            prepare.assert_not_called()
