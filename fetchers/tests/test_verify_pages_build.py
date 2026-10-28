import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_pages_build import verify_build
from src.snapshots import IMAGE_TYPES, read_resources


class VerifyPagesBuildTests(unittest.TestCase):
    def test_routes_and_selected_manifest_are_required(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
            base = Path(d)
            source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
            shutil.copytree(source, base / 'input')
            shutil.copytree(source, base / 'dist/data')
            data, _ = read_resources(base / 'input')
            manifest = base / 'manifest.json'
            manifest.write_text(json.dumps({'files': {n: hashlib.sha256(c).hexdigest() for n, c in data.items()}}))
            html = '<script src="/repo/assets/app.js"></script>'
            (base / 'dist/index.html').write_text(html)
            (base / 'dist/Hero_Section_Image.jpeg').write_bytes(b'test asset')
            for kind in IMAGE_TYPES:
                p = base / 'dist/images' / kind / 'index.html'
                p.parent.mkdir(parents=True)
                p.write_text(html)
            self.assertEqual(verify_build(base / 'input', base / 'dist', '/repo/', manifest)['detail_entries'], 12)
            # Two matching modified copies must still fail the selected manifest.
            for root in ('input', 'dist/data'):
                p = base / root / 'images/radar/latest.json'
                item = json.loads(p.read_text(encoding='utf-8'))
                item['fetched_at'] = '2026-10-28T01:00:00+00:00'
                p.write_text(json.dumps(item), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_build(base / 'input', base / 'dist', '/repo/', manifest)
