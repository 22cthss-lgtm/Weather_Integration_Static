import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ContentVersionTests(unittest.TestCase):
    def test_check_times_and_synthetic_query_are_not_data_changes(self):
        from src.content_versions import resource_identity
        one = {'image_type': 'sst', 'image_url': 'https://www.data.jma.go.jp/a.gif?fetched=old',
               'image_time': '2026-10-29', 'fetched_at': 'old'}
        two = dict(one, image_url=one['image_url'].replace('old', 'new'), fetched_at='new')
        self.assertEqual(resource_identity(one), resource_identity(two))
        self.assertNotEqual(resource_identity(one), resource_identity(dict(two, image_time='2026-10-30')))

    def test_nested_observation_times_order_and_history_gaps_are_data(self):
        from src.content_versions import resource_identity
        data = {'updated_at': 'old', 'items': [{'id': 1, 'observed_at': '2026-10-29', 'fetched_at': 'old'},
                                               {'id': 2}], 'missing': ['10:40']}
        same = json.loads(json.dumps(data))
        same['updated_at'] = 'new'
        same['items'][0]['fetched_at'] = 'new'
        self.assertEqual(resource_identity(data), resource_identity(same))
        for changed in (dict(same, missing=[]), dict(same, items=list(reversed(same['items'])))):
            self.assertNotEqual(resource_identity(data), resource_identity(changed))

    def test_only_known_generated_parameters_are_removed(self):
        from src.content_versions import canonical_url
        self.assertEqual(canonical_url('https://www.cwa.gov.tw/Data/fcst_img/FI04.png?t=123'),
                         'https://www.cwa.gov.tw/Data/fcst_img/FI04.png')
        self.assertIn('t=123', canonical_url('https://example.org/analysis?t=123&basin=westpac'))

    def test_fixed_urls_require_content_hash_not_last_modified(self):
        from src.content_versions import needs_image_hash, resource_identity
        image = {'image_url': 'https://nsidc.org/data/seaice_index/images/daily_images/N_daily_extent_hires.png',
                 'image_time': None}
        self.assertTrue(needs_image_hash(image))
        self.assertNotEqual(resource_identity(image, {'https://nsidc.org/data/seaice_index/images/daily_images/N_daily_extent_hires.png': 'a' * 64}),
                            resource_identity(image, {'https://nsidc.org/data/seaice_index/images/daily_images/N_daily_extent_hires.png': 'b' * 64}))
