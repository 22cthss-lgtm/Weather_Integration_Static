"""Generate one public ranking snapshot; no database and no credentials in output."""

from datetime import datetime, timezone
import math

from .publication import atomic_write_json
from .services.rainfall_observation_service import RainfallObservationService

METRICS = {
    '10min': 'rain_10min', '1hr': 'rain_1hr', '3hr': 'rain_3hr',
    '6hr': 'rain_6hr', '12hr': 'rain_12hr', '24hr': 'rain_24hr',
    'today': 'rain_today', '1day': 'rain_1day', '2days': 'rain_2days',
}


def build_rankings(observations):
    if not observations:
        raise RuntimeError('No rainfall observations; previous ranking preserved')
    stations = {}
    try:
        for item in observations:
            if not isinstance(item.get('station_id'), str) or not item['station_id']:
                raise ValueError('missing station')
            observed = datetime.fromisoformat(item['observed_at'])
            fetched = datetime.fromisoformat(item['fetched_at'])
            if observed.utcoffset() is None or fetched.utcoffset() != timezone.utc.utcoffset(fetched):
                raise ValueError('missing timezone')
            if observed > fetched:
                raise ValueError('future observation')
            old = stations.get(item['station_id'])
            if old is None or observed > datetime.fromisoformat(old['observed_at']):
                stations[item['station_id']] = item
        fetched_times = {p['fetched_at'] for p in stations.values()}
        if len(fetched_times) != 1:
            raise ValueError('mixed fetch batches')
    except (KeyError, TypeError, ValueError):
        raise RuntimeError('Invalid rainfall observation snapshot; previous ranking preserved') from None
    fetched_at = next(iter(fetched_times))
    rankings = {}
    for metric, column in METRICS.items():
        eligible = [p for p in stations.values() if isinstance(p.get(column), (float, int))
                    and not isinstance(p[column], bool) and math.isfinite(p[column]) and p[column] >= 0]
        if not eligible:
            raise RuntimeError(f'No valid rainfall observations for {metric}; previous ranking preserved')
        eligible.sort(key=lambda p: (-p[column], p.get('station_name', ''), p['station_id']))
        items = [dict(rank=index, station_id=p['station_id'], station_name=p.get('station_name', ''),
                      county=p.get('county', ''), town=p.get('town', ''), rainfall=p[column],
                      observed_at=p['observed_at'], fetched_at=p['fetched_at'])
                 for index, p in enumerate(eligible[:10], start=1)]
        rankings[metric] = {'metric': metric, 'fetched_at': fetched_at, 'unit': 'mm', 'items': items}
    return {'source': 'CWA', 'dataset_id': 'O-A0002-001', 'fetched_at': fetched_at, 'rankings': rankings}


def update_rankings(output_path):
    data = build_rankings(RainfallObservationService().fetch_observations())
    return atomic_write_json(data, output_path)
