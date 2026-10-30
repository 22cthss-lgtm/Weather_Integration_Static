from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DueCliTests(unittest.TestCase):
    def test_publish_with_corrupt_state_resets_without_fetching(self):
        import refresh_pages
        from src.pages_package import pack_snapshot
        from src.snapshots import export_snapshot
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            export_snapshot(Path(__file__).resolve().parents[2]/'frontend/public/data', root/'seed')
            package = pack_snapshot(root/'seed', root/'input.zip')
            (root/'source-state.json').write_text('broken JSON')
            env = {'MODE':'publish','RETENTION_DAYS':'7','RUNNER_TEMP':str(root),
                   'ARCHIVE':str(root/'input.zip'),'ASSET_SHA':package['sha256'],'WORK':str(root/'work'),
                   'RESULT':str(root/'result.json'),'GITHUB_STEP_SUMMARY':str(root/'summary.md'),
                   'GITHUB_OUTPUT':str(root/'outputs.txt')}
            with patch.dict(os.environ, env, clear=True), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(refresh_pages.main(['prepare']), 0)
            result=json.loads((root/'result.json').read_text())
            self.assertEqual(result['state_warning'], 'corrupt')
            self.assertTrue(result['deploy'])
            self.assertFalse(result['save_snapshot'])
            self.assertTrue(all(task['last_successful_check_at'] is None for task in result['scheduler_state']['scheduler']['tasks'].values()))

    def test_auto_inputs_require_no_manual_ids_and_match_confirmed_policy(self):
        import refresh_pages
        env = {'MODE':'refresh','SOURCE_MODE':'auto','RETENTION_DAYS':'7'}
        with patch.dict(os.environ, env, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(refresh_pages.main(['inputs']), 0)
            os.environ['ASSET_SHA']='a'*64
            self.assertEqual(refresh_pages.main(['inputs']), 1)
