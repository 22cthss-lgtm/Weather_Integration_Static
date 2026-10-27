from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.publication import publish_image
from src.services.base import ImagePayload
from src.services.cimss_service import CIMSSService
from src.services.nsidc_service import NSIDCService

EXPECTED = {
    'cimss_wind_analysis': ('cimss_wind_shear', 'cimss_850mb_vorticity'),
    'cimss_steering_flow': tuple('cimss_steering_flow_' + layer for layer in (
        '200_700mb', '250_850mb', '300_850mb', '400_850mb', '500_850mb', '700_850mb')),
    'seaice_arctic': tuple('seaice_arctic_' + view for view in ('extent', 'concentration', 'timeseries')),
    'seaice_antarctic': tuple('seaice_antarctic_' + view for view in ('extent', 'concentration', 'timeseries')),
}
FIELDS = {'image_type', 'source', 'title', 'image_url', 'source_url', 'fetched_at', 'image_time'}


def payloads(kind):
    source = 'CIMSS' if kind.startswith('cimss') else 'NSIDC'
    return [ImagePayload(child, source, child, f'https://example.com/{child}.png',
                         'https://example.com/', '2026-10-22T08:00:00+00:00',
                         '2026-10-21' if kind.startswith('seaice') else '2026-10-22T06:00:00+00:00')
            for child in EXPECTED[kind]]


class GroupPublicationTests(unittest.TestCase):
    def test_all_groups_contract_order_representative_and_roundtrip(self):
        for kind, expected in EXPECTED.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                items = payloads(kind)
                output = Path(directory) / kind / 'latest.json'
                data = publish_image(kind, reversed(items), output)
                self.assertEqual(set(data), FIELDS | {'images'})
                self.assertEqual(tuple(child['image_type'] for child in data['images']), expected)
                self.assertEqual(len(data['images']), len(expected))
                for child in data['images']:
                    self.assertEqual(set(child), FIELDS)
                for field in FIELDS - {'image_type'}:
                    self.assertEqual(data[field], data['images'][0][field])
                self.assertEqual(data['image_type'], kind)
                self.assertEqual(json.loads(output.read_text(encoding='utf-8')), data)

    def test_incomplete_duplicate_extra_wrong_and_invalid_children_keep_old_json(self):
        for kind in EXPECTED:
            items = payloads(kind)
            variants = [[], items[:-1], items + [items[0]],
                        items[:-1] + [replace(items[-1], image_type='wrong')]]
            for field, value in [('image_url', ''), ('source_url', 'file:///bad'), ('title', ''),
                                 ('source', ''), ('fetched_at', '2026-10-22T08:00:00'),
                                 ('image_time', 'bad-time')]:
                variants.append(items[:-1] + [replace(items[-1], **{field: value})])
            variants.append(items[:-1] + [replace(items[-1], source='other source')])
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                output = Path(directory) / 'latest.json'
                for bad in variants:
                    output.write_bytes(b'previous complete group')
                    with self.assertRaises((RuntimeError, ValueError)):
                        publish_image(kind, iter(bad), output)
                    self.assertEqual(output.read_bytes(), b'previous complete group')
                    self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_unknown_child_times_are_null_without_inventing_times(self):
        for kind in EXPECTED:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                data = publish_image(kind, [replace(p, image_time=None) for p in payloads(kind)],
                                     Path(directory) / 'latest.json')
                self.assertIsNone(data['image_time'])
                self.assertTrue(all(p['image_time'] is None for p in data['images']))

    def test_replace_failure_preserves_complete_group_and_cleans_temp(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / 'latest.json'
            output.write_bytes(b'previous complete group')
            with patch('src.publication.os.replace', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    publish_image('cimss_steering_flow', payloads('cimss_steering_flow'), output)
            self.assertEqual(output.read_bytes(), b'previous complete group')
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_partial_generator_failure_and_first_failure_do_not_publish(self):
        def interrupted():
            yield payloads('seaice_arctic')[0]
            raise RuntimeError('source interrupted')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / 'latest.json'
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                publish_image('seaice_arctic', interrupted(), output)
            self.assertFalse(output.exists())
            output.write_bytes(b'previous complete group')
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                publish_image('seaice_arctic', interrupted(), output)
            self.assertEqual(output.read_bytes(), b'previous complete group')

    def test_registered_group_methods_use_resource_paths(self):
        import update_images as runner
        for kind in EXPECTED:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                _, method = runner.GROUP_PRODUCTS[kind]
                service = Mock()
                getattr(service, method).return_value = iter(payloads(kind))
                with patch.dict(runner.GROUP_PRODUCTS, {kind: (Mock(return_value=service), method)}):
                    runner.update_image(kind, directory)
                self.assertTrue((Path(directory) / kind / 'latest.json').is_file())
                service.image_exists.assert_not_called()
                getattr(service, method).assert_called_once_with()

    def test_group_failure_does_not_stop_next_group(self):
        import update_images as runner
        with patch.object(runner, 'update_image', side_effect=[RuntimeError('partial'),
                          {'image_time': None, 'fetched_at': '2026-10-22T08:00:00+00:00'}]) as update:
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                with patch('src.update_runner.runtime_directory', return_value=Path(directory) / '.runtime'), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = runner.main(['cimss_wind_analysis', 'seaice_arctic'])
        self.assertEqual(result, 1)
        self.assertEqual(update.call_count, 2)


class GroupServiceTests(unittest.TestCase):
    def test_cimss_page_fetch_uses_existing_request_contract(self):
        response = Mock(text='westpac/winds/wgmsshr.GIF')
        with patch('src.services.cimss_service.requests.get', return_value=response) as request:
            self.assertEqual(CIMSSService().fetch_page_html(), response.text)
        self.assertNotIn('image_time', request.call_args.kwargs)

    def response(self, content=b'GIF89a', mime='image/png'):
        return Mock(content=content, headers={'Content-Type': mime,
                    'Last-Modified': 'Thu, 22 Oct 2026 08:00:00 GMT'})

    def test_cimss_explicit_utc_time_and_header_only_unknown(self):
        service = CIMSSService()
        self.assertEqual(service.resolve_image_time(self.response(b'06 UTC 22 OCT 2026')),
                         '2026-10-22T06:00:00+00:00')
        self.assertIsNone(service.resolve_image_time(self.response(b'GIF89a')))

    def test_cimss_iso_time_requires_explicit_utc_marker(self):
        service = CIMSSService()
        self.assertIsNone(service.extract_image_time_from_bytes(b'2026-10-22 06:00'))
        self.assertEqual(service.extract_image_time_from_bytes(b'2026-10-22 06:00 UTC'),
                         '2026-10-22T06:00:00+00:00')

    def test_nsidc_date_precision_and_header_only_unknown(self):
        service = NSIDCService()
        self.assertEqual(service.extract_image_time_from_bytes(b'Sea Ice Extent 21 Oct 2026'), '2026-10-21')
        with patch.object(service, 'fetch_image_response', return_value=self.response()):
            self.assertIsNone(service.resolve_image_time('https://example.com/image.png'))

    def test_services_reject_html_and_http_errors(self):
        for cls in (CIMSSService, NSIDCService):
            for http_error in (False, True):
                with self.subTest(service=cls.__name__, http_error=http_error):
                    response = self.response(mime='text/html' if not http_error else 'image/png')
                    if http_error:
                        response.raise_for_status.side_effect = requests.HTTPError('404')
                    with patch('requests.get', return_value=response):
                        self.assertIsNone(cls().fetch_image_response('https://example.com/img'))
                    response.close.assert_called_once()

    def test_services_reject_empty_image_bodies(self):
        for cls in (CIMSSService, NSIDCService):
            response = self.response(content=b'')
            with self.subTest(service=cls.__name__), patch('requests.get', return_value=response):
                self.assertIsNone(cls().fetch_image_response('https://example.com/img'))
            response.close.assert_called_once()

    def test_source_page_failure_preserves_each_group(self):
        import update_images as runner
        for kind, (cls, _) in runner.GROUP_PRODUCTS.items():
            page_method = 'fetch_specific_page_html' if kind == 'cimss_steering_flow' else 'fetch_page_html'
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                output = Path(directory) / kind / 'latest.json'
                output.parent.mkdir()
                output.write_bytes(b'previous complete group')
                with patch.object(cls, page_method, return_value=None):
                    with self.assertRaises(RuntimeError):
                        runner.update_image(kind, directory)
                self.assertEqual(output.read_bytes(), b'previous complete group')

    def test_cimss_partial_source_failure_keeps_previous_group(self):
        import update_images as runner
        for kind, method, page_method, page in (
            ('cimss_wind_analysis', 'fetch_wind_analysis', 'fetch_page_html', 'westpac/winds/wgmsshr.GIF'),
            ('cimss_steering_flow', 'fetch_steering_flow', 'fetch_specific_page_html', 'wgmsdlm1.GIF'),
        ):
            count = len(EXPECTED[kind])
            responses = [self.response() for _ in range(count - 1)] + [None]
            service = CIMSSService()
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                output = Path(directory) / 'latest.json'
                output.write_bytes(b'previous complete group')
                with patch.object(service, page_method, return_value=page):
                    with patch.object(service, 'fetch_image_response', side_effect=responses):
                        with self.assertRaises(RuntimeError):
                            publish_image(kind, getattr(service, method)(), output)
                self.assertEqual(output.read_bytes(), b'previous complete group')

    def test_nsidc_partial_source_failure_keeps_previous_group(self):
        for kind, method in (('seaice_arctic', 'fetch_arctic'), ('seaice_antarctic', 'fetch_antarctic')):
            service = NSIDCService()
            page = ' '.join([service.extent_image_url, service.concentration_image_url, service.timeseries_image_url,
                             service.antarctic_extent_image_url, service.antarctic_concentration_image_url,
                             service.antarctic_timeseries_image_url])
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                output = Path(directory) / 'latest.json'
                output.write_bytes(b'previous complete group')
                with patch.object(service, 'fetch_page_html', return_value=page):
                    with patch.object(service, 'fetch_image_response', side_effect=[self.response(), self.response(), None]):
                        with self.assertRaises(RuntimeError):
                            publish_image(kind, getattr(service, method)(), output)
                self.assertEqual(output.read_bytes(), b'previous complete group')

    def test_service_payloads_include_known_or_unknown_time(self):
        for kind, cls, method, resolver in (
            ('cimss_wind_analysis', CIMSSService, 'fetch_wind_analysis', 'resolve_latest_wind_analysis_images'),
            ('cimss_steering_flow', CIMSSService, 'fetch_steering_flow', 'resolve_latest_steering_flow_images'),
            ('seaice_arctic', NSIDCService, 'fetch_arctic', 'resolve_latest_arctic_sea_ice_images'),
            ('seaice_antarctic', NSIDCService, 'fetch_antarctic', 'resolve_latest_antarctic_sea_ice_images'),
        ):
            for unknown in (False, True):
                items = payloads(kind)
                resolved = {p.image_type: {'image_url': p.image_url, 'image_time': None if unknown else p.image_time} for p in items}
                service = cls()
                with self.subTest(kind=kind, unknown=unknown), patch.object(service, resolver, return_value=resolved):
                    result = list(getattr(service, method)())
                self.assertEqual(len(result), len(items))
                for p in result:
                    self.assertEqual(p.image_time, resolved[p.image_type]['image_time'])
                    self.assertNotIn('None', p.title)
                    self.assertTrue(p.fetched_at.endswith('+00:00'))
