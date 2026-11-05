from pathlib import Path
import unittest
import yaml


class PagesWorkflowTests(unittest.TestCase):
    def test_scheduled_and_manual_events_keep_failure_gates(self):
        path = Path(__file__).resolve().parents[2] / '.github/workflows/pages-manual.yml'
        text = path.read_text(encoding='utf-8')
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch', 'schedule'})
        # Pin ten-minute cadence while allowing a cron-only phase adjustment.
        self.assertEqual(len(workflow['on']['schedule']), 1)
        self.assertRegex(workflow['on']['schedule'][0]['cron'], r'^(?:\*|[0-9]-59)/10 \* \* \* \*$')
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
        build = workflow['jobs']['build']
        deploy = workflow['jobs']['deploy']
        self.assertEqual(deploy['needs'], 'build')
        self.assertIn("needs.build.outputs.deploy == 'true'", deploy['if'])
        self.assertEqual(deploy['environment']['name'], 'github-pages')
        self.assertEqual(deploy['permissions']['pages'], 'write')
        self.assertEqual(build['permissions']['pages'], 'read')
        steps = build['steps']
        scripts = '\n'.join(step.get('run', '') for step in steps)
        for command in ('refresh_pages.py prepare', 'unittest discover', 'npm test -- --run',
                        'build:pages', 'verify_pages_build.py'):
            self.assertIn(command, scripts)
        self.assertNotIn('update_snapshot.py', text)
        self.assertIn('secrets.CWA_API_KEY', text)
        self.assertNotIn('continue-on-error', text)
        self.assertNotIn('git push', text)
        self.assertNotIn('git commit', text)
        upload_index = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
        self.assertTrue(all(next(i for i, step in enumerate(steps) if command in step.get('run', '')) < upload_index
                            for command in ('unittest discover', 'npm test -- --run', 'verify_pages_build.py')))
        self.assertEqual(steps[upload_index]['with']['retention-days'], '1')
        self.assertEqual(steps[upload_index]['with']['path'], 'frontend/dist')

    def test_refresh_is_persisted_before_deploy_and_retention_is_explicit(self):
        path = Path(__file__).resolve().parents[2] / '.github/workflows/pages-manual.yml'
        workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(inputs['mode']['options'], ['publish', 'refresh'])
        self.assertEqual(inputs['snapshot_retention_days']['default'], '7')
        self.assertEqual(inputs['snapshot_retention_days']['required'], 'true')
        build = workflow['jobs']['build']
        self.assertEqual(build['permissions']['actions'], 'read')
        steps = build['steps']
        saved = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/upload-artifact@'))
        verified = next(i for i, step in enumerate(steps) if 'verify_pages_build.py' in step.get('run', ''))
        website = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
        self.assertLess(verified, saved)
        self.assertLess(saved, website)
        self.assertEqual(steps[saved]['with']['if-no-files-found'], 'error')
        self.assertEqual(steps[saved]['with']['path'], '${{ runner.temp }}/pages-work/output/weather-snapshot.zip')
        self.assertEqual(steps[saved]['with']['retention-days'], '${{ env.RETENTION_DAYS }}')
        download = next(step for step in steps if step.get('uses', '').startswith('actions/download-artifact@'))
        self.assertEqual(download['with']['run-id'], '${{ inputs.snapshot_run_id }}')
        self.assertEqual(download['with']['name'], 'weather-snapshot')

    def test_auto_due_recovery_readback_and_separate_cleanup_permissions(self):
        path = Path(__file__).resolve().parents[2] / '.github/workflows/pages-manual.yml'
        workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(inputs['snapshot_source']['default'], 'auto')
        self.assertEqual(inputs['snapshot_sha256']['required'], 'false')
        steps = workflow['jobs']['build']['steps']
        pages = next(i for i,s in enumerate(steps) if s.get('id') == 'pages')
        online = next(i for i,s in enumerate(steps) if 'manage_snapshots.py deployment' in s.get('run',''))
        prepare = next(i for i,s in enumerate(steps) if 'refresh_pages.py prepare' in s.get('run',''))
        self.assertLess(pages,online)
        self.assertLess(online,prepare)
        self.assertEqual(steps[online]['env']['SITE_URL'],'${{ steps.pages.outputs.base_url }}')
        self.assertNotIn('if',steps[pages])
        recorded = next(step for step in steps if step.get('name') == 'Record selected code and data')
        self.assertEqual(recorded['env']['ASSET_SHA'], '${{ steps.resolve.outputs.sha256 || inputs.snapshot_sha256 }}')
        scripts = '\n'.join(step.get('run', '') for step in steps)
        for command in ('manage_snapshots.py resolve', 'manage_snapshots.py verify-data',
                        'manage_snapshots.py verify-state', 'manage_snapshots.py guard'):
            self.assertIn(command, scripts)
        saved = next(step for step in steps if step.get('id') == 'save_data')
        self.assertIn("save_snapshot == 'true'", saved['if'])
        cleanup = workflow['jobs']['cleanup']
        self.assertEqual(cleanup['permissions']['actions'], 'write')
        self.assertNotIn('contents: write', path.read_text())
        self.assertIn('deploy', cleanup['needs'])
        self.assertIn('manage_snapshots.py cleanup', '\n'.join(step.get('run', '') for step in cleanup['steps']))
