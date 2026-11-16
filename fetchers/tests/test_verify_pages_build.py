import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_pages_build import APP_ROUTES, verify_build
from src.snapshots import IMAGE_TYPES, read_resources

HTML = '<script src="/repo/assets/app.js"></script>'


class VerifyPagesBuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.base = base = Path(self._tmp.name)
        source = Path(__file__).resolve().parents[2] / 'frontend/public/data'
        shutil.copytree(source, base / 'input')
        shutil.copytree(source, base / 'dist/data')
        data, _ = read_resources(base / 'input')
        self.manifest = base / 'manifest.json'
        self.manifest.write_text(json.dumps({'files': {n: hashlib.sha256(c).hexdigest() for n, c in data.items()}}))
        (base / 'dist/index.html').write_text(HTML)
        (base / 'dist/Hero_Section_Image.jpeg').write_bytes(b'test asset')
        for route in [Path('images') / kind for kind in IMAGE_TYPES] + [Path(r) for r in APP_ROUTES]:
            p = base / 'dist' / route / 'index.html'
            p.parent.mkdir(parents=True)
            p.write_text(HTML)

    def tearDown(self):
        self._tmp.cleanup()

    def verify(self):
        return verify_build(self.base / 'input', self.base / 'dist', '/repo/', self.manifest)

    def test_routes_and_selected_manifest_are_required(self):
        result = self.verify()
        self.assertEqual(result['detail_entries'], 12)
        self.assertEqual(result['app_entries'], ['tropical'])
        # Two matching modified copies must still fail the selected manifest.
        for root in ('input', 'dist/data'):
            p = self.base / root / 'images/radar/latest.json'
            item = json.loads(p.read_text(encoding='utf-8'))
            item['fetched_at'] = '2026-10-28T01:00:00+00:00'
            p.write_text(json.dumps(item), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.verify()

    def test_tropical_entry_is_a_fixed_app_route(self):
        self.assertEqual(APP_ROUTES, ('tropical',))
        self.assertNotIn('tropical', IMAGE_TYPES)

    def test_missing_tropical_entry_fails(self):
        (self.base / 'dist/tropical/index.html').unlink()
        with self.assertRaisesRegex(ValueError, 'static app entry'):
            self.verify()

    def test_tropical_directory_without_entry_fails(self):
        shutil.rmtree(self.base / 'dist/tropical')
        with self.assertRaisesRegex(ValueError, 'static app entry'):
            self.verify()

    def test_tropical_entry_differing_from_index_fails(self):
        (self.base / 'dist/tropical/index.html').write_text(HTML + '\n')
        with self.assertRaisesRegex(ValueError, 'static app entry'):
            self.verify()

    def test_image_entry_checks_are_unchanged(self):
        (self.base / 'dist/images/radar/index.html').write_text('<p>other</p>')
        with self.assertRaisesRegex(ValueError, 'static detail entry'):
            self.verify()
        (self.base / 'dist/images/radar/index.html').unlink()
        with self.assertRaises(FileNotFoundError):  # pre-existing behaviour for a missing image entry
            self.verify()


if __name__ == '__main__':
    unittest.main()
