from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.cwa_service import CWAService
from src.services.kma_service import KMAService


class ProductTimeTests(unittest.TestCase):
    def test_tchp_resolver_keeps_daily_precision(self):
        response = Mock(text="var TDD_TCHP = '2026-10-18_TCHP_ostia.png';")
        with patch('src.services.cwa_service.requests.get', return_value=response):
            resolved = CWAService().resolve_tchp_image_url()
        self.assertEqual(resolved[1], '2026-10-18')

    def test_kma_api_and_probe_describe_same_instant(self):
        service = KMAService()
        response = Mock()
        response.json.return_value = [{
            'tm': '2026102209',
            'url': '/w/repositary/image/cht/img/up85_2026102200.png',
        }]
        with patch('src.services.kma_service.requests.get', return_value=response):
            api_url, api_time = service.resolve_850hpa_image_url()
        from datetime import datetime, timezone
        with patch('src.services.kma_service.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 22, 1, tzinfo=timezone.utc)
            with patch.object(service, 'image_exists', return_value=True):
                probe_url, probe_time = service.resolve_latest_850hpa_image_by_probe()
        self.assertEqual((api_url, api_time), (probe_url, probe_time))

    def test_cwa_html_error_page_is_not_an_image(self):
        response = Mock(ok=True, headers={'content-type': 'text/html'})
        with patch('src.services.cwa_service.requests.get', return_value=response):
            self.assertFalse(CWAService().image_exists('https://example.com/missing.png'))

    def test_cwa_temperature_has_taipei_offset(self):
        service = CWAService()
        with patch.object(service, 'resolve_temperature_image_url', return_value=(
            'https://example.com/temp.jpg', '2026-10-22 08:00'
        )):
            item = next(service.fetch_temperature())
        self.assertEqual(item.image_time, '2026-10-22T08:00:00+08:00')

    def test_weather_chart_unknown_time_stays_null(self):
        service = CWAService()
        with patch.object(service, 'resolve_weather_chart_image_url', return_value=(
            'https://example.com/FI04.png', None
        )):
            self.assertIsNone(next(service.fetch_weather_chart()).image_time)

    def test_weather_chart_known_time_has_offset(self):
        service = CWAService()
        with patch.object(service, 'resolve_weather_chart_image_url', return_value=(
            'https://example.com/FI04.png', '2026-10-22 08:00'
        )):
            self.assertEqual(next(service.fetch_weather_chart()).image_time,
                             '2026-10-22T08:00:00+08:00')

    def test_tchp_only_publishes_product_date(self):
        service = CWAService()
        with patch.object(service, 'resolve_tchp_image_url', return_value=(
            'https://example.com/tchp.png', '2026-10-18'
        )):
            self.assertEqual(next(service.fetch_tchp()).image_time, '2026-10-18')

    def test_kma_has_korean_offset(self):
        service = KMAService()
        with patch.object(service, 'resolve_850hpa_image_url', return_value=(
            'https://example.com/up85.png', '2026-10-22 09:00'
        )):
            self.assertEqual(next(service.fetch_850hpa()).image_time,
                             '2026-10-22T09:00:00+09:00')


class WriterTests(unittest.TestCase):
    def test_registered_services_publish_only_requested_product(self):
        import update_images as runner
        from src.services.base import ImagePayload
        for kind, (service_class, method) in runner.PRODUCTS.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                image_time = '2026-10-20' if kind in ('sst', 'tchp') else '2026-10-22T08:00:00+08:00'
                item = ImagePayload(kind, 'SOURCE', 'Title', 'https://example.com/image.png',
                                    'https://example.com/', '2026-10-22T00:00:00+00:00', image_time)
                service = Mock()
                getattr(service, method).return_value = iter([item])
                service.image_exists.return_value = True
                with patch.dict(runner.PRODUCTS, {kind: (Mock(return_value=service), method)}):
                    runner.update_image(kind, directory)
                output = Path(directory) / kind / 'latest.json'
                self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['image_type'], kind)
                self.assertEqual(list(Path(directory).iterdir()), [output.parent])
                getattr(service, method).assert_called_once_with()

    def test_generator_failure_preserves_json(self):
        from src.publication import publish_image
        from src.services.base import ImagePayload
        def interrupted():
            yield ImagePayload('tchp', 'CWA', 'TCHP', 'https://example.com/image.png',
                               'https://example.com/', '2026-10-22T00:00:00+00:00', '2026-10-18')
            raise RuntimeError('interrupted fetch')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / 'latest.json'
            output.write_bytes(b'previous success')
            with self.assertRaisesRegex(RuntimeError, 'interrupted fetch'):
                publish_image('tchp', interrupted(), output)
            self.assertEqual(output.read_bytes(), b'previous success')

    def test_failed_image_verification_preserves_previous_resource(self):
        import update_images as runner
        service = CWAService()
        item = service.build_payload('tchp', 'TCHP', 'https://example.com/img.png',
                                     'https://example.com/', '2026-10-18')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / 'tchp/latest.json'
            output.parent.mkdir()
            output.write_bytes(b'previous success')
            with patch.object(CWAService, 'fetch_tchp', return_value=iter([item])):
                with patch.object(CWAService, 'image_exists', return_value=False):
                    with self.assertRaises(RuntimeError):
                        runner.update_image('tchp', Path(directory))
            self.assertEqual(output.read_bytes(), b'previous success')

    def test_all_types_publish_same_contract_and_preserve_on_bad_data(self):
        import update_images as runner
        from src.services.base import ImagePayload
        for kind in runner.PRODUCTS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                output = Path(directory) / 'latest.json'
                time = ('2026-10-20' if kind in ('sst', 'tchp') else
                        None if kind == 'weather_chart' else '2026-10-22T08:00:00+08:00')
                item = ImagePayload(kind, 'SOURCE', 'Title', 'https://example.com/img.png',
                                    'https://example.com/', '2026-10-22T01:00:00+00:00', time)
                data = runner.publish_image(kind, iter([item]), output)
                self.assertEqual(json.loads(output.read_text(encoding='utf-8')), data)
                original = output.read_bytes()
                for invalid in ([], [item, item]):
                    with self.assertRaises(RuntimeError):
                        runner.publish_image(kind, iter(invalid), output)
                    self.assertEqual(output.read_bytes(), original)
                for field, bad in [('image_type', 'wrong'), ('fetched_at', '2026-10-22T01:00:00'),
                                   ('image_url', ''), ('image_time', 'bad-date')]:
                    old = getattr(item, field)
                    setattr(item, field, bad)
                    with self.assertRaises((RuntimeError, ValueError)):
                        runner.publish_image(kind, iter([item]), output)
                    self.assertEqual(output.read_bytes(), original)
                    setattr(item, field, old)

    def test_batch_continues_after_one_source_fails(self):
        import update_images as runner
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            calls = []
            def update(kind, root):
                calls.append(kind)
                if kind == 'temperature':
                    raise RuntimeError('unavailable')
                return {'image_time': None, 'fetched_at': '2026-10-22T00:00:00+00:00'}
            errors = io.StringIO()
            with patch.object(runner, 'update_image', side_effect=update), redirect_stderr(errors), redirect_stdout(io.StringIO()):
                code = runner.main(['temperature', '850hpa', '--output-root', directory])
            self.assertEqual(code, 1)
            self.assertEqual(calls, ['temperature', '850hpa'])
            self.assertIn('previous JSON preserved', errors.getvalue())

    def test_entrypoint_does_not_import_flask_or_database(self):
        script = "import update_images, sys; assert not any(n == 'flask' or n.startswith('flask.') or n in ('sqlite3', 'src.config', 'src.db') for n in sys.modules)"
        result = subprocess.run([sys.executable, '-B', '-c', script],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
