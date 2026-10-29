from pathlib import Path
import unittest
import yaml


class PagesWorkflowTests(unittest.TestCase):
    def test_manual_only_and_failure_gates(self):
        path = Path(__file__).resolve().parents[2] / '.github/workflows/pages-manual.yml'
        text = path.read_text(encoding='utf-8')
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
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

    def test_refresh_is_manual_persisted_before_deploy_and_retention_is_explicit(self):
        path = Path(__file__).resolve().parents[2] / '.github/workflows/pages-manual.yml'
        workflow = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(inputs['mode']['options'], ['publish', 'refresh'])
        self.assertNotIn('default', inputs['snapshot_retention_days'])
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
        self.assertIn('inputs.snapshot_retention_days', steps[saved]['with']['retention-days'])
        download = next(step for step in steps if step.get('uses', '').startswith('actions/download-artifact@'))
        self.assertEqual(download['with']['run-id'], '${{ inputs.snapshot_run_id }}')
        self.assertEqual(download['with']['name'], 'weather-snapshot')
