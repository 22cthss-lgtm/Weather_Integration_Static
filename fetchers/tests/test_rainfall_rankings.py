from contextlib import redirect_stderr, redirect_stdout
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RankingTests(unittest.TestCase):
    def observations(self):
        from src.rainfall_rankings import METRICS
        items = []
        for i in range(14):
            item = dict(station_id=str(i), station_name=f'Station {i:02}', county='County', town='Town',
                        observed_at='2026-10-22T10:00:00+08:00', fetched_at='2026-10-22T02:05:00+00:00')
            item.update({field: float(i) for field in METRICS.values()})
            items.append(item)
        return items

    def test_all_periods_top10_rank_time_and_zero_value(self):
        from src.rainfall_rankings import build_rankings, METRICS
        data = build_rankings(self.observations())
        self.assertEqual(set(data['rankings']), set(METRICS))
        for ranking in data['rankings'].values():
            self.assertEqual(len(ranking['items']), 10)
            self.assertEqual([p['rank'] for p in ranking['items']], list(range(1, 11)))
            self.assertEqual([p['rainfall'] for p in ranking['items']], list(map(float, range(13, 3, -1))))
            self.assertEqual(ranking['items'][0]['observed_at'], '2026-10-22T10:00:00+08:00')
        zero = self.observations()[:1]
        self.assertEqual(build_rankings(zero)['rankings']['10min']['items'][0]['rainfall'], 0)

    def test_nonfinite_negative_missing_and_duplicate_station_values(self):
        from src.rainfall_rankings import build_rankings
        items = self.observations()
        for item, value in zip(items, [float('nan'), float('inf'), -99, None]):
            item['rain_10min'] = value
        items.append(dict(items[-1], observed_at='2026-10-22T09:00:00+08:00', rain_10min=999))
        ranking = build_rankings(items)['rankings']['10min']['items']
        self.assertEqual(ranking[0]['rainfall'], 13)
        self.assertTrue(all(math.isfinite(p['rainfall']) and p['rainfall'] >= 0 for p in ranking))
        self.assertEqual(len({p['station_id'] for p in ranking}), len(ranking))

    def test_invalid_snapshot_does_not_replace_success(self):
        from src.rainfall_rankings import update_rankings
        from src.services.rainfall_observation_service import RainfallObservationService
        for observations in ([], [{'bad': True}]):
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                output = Path(directory) / 'latest.json'
                output.write_bytes(b'previous ranking')
                with patch.object(RainfallObservationService, 'fetch_observations', return_value=observations):
                    with self.assertRaises((RuntimeError, ValueError)):
                        update_rankings(output)
                self.assertEqual(output.read_bytes(), b'previous ranking')

    def test_failed_source_never_exposes_key_in_error(self):
        from src.services.rainfall_observation_service import RainfallObservationService
        import requests
        with patch.dict(os.environ, {'CWA_API_KEY': 'test-secret-never-publish'}), \
             patch('requests.get', side_effect=requests.RequestException('Authorization=test-secret-never-publish')):
            try:
                RainfallObservationService().fetch_observations()
            except RuntimeError:
                self.assertNotIn('test-secret', traceback.format_exc())
            else:
                self.fail('Must fail safely')

    def test_observation_fetch_import_is_database_free(self):
        script = "import src.rainfall_rankings,sys; assert not any(n in sys.modules for n in ('sqlite3','src.db','src.config','flask'))"
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_key_preserves_previous_file(self):
        from src.rainfall_rankings import update_rankings
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / 'latest.json'
            output.write_bytes(b'previous success')
            with patch.dict(os.environ, {'CWA_API_KEY': ''}):
                with self.assertRaisesRegex(RuntimeError, 'CWA_API_KEY'):
                    update_rankings(output)
            self.assertEqual(output.read_bytes(), b'previous success')
