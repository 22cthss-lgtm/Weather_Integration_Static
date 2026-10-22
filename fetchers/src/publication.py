"""Validate image resources and atomically publish single images or groups."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


GROUPS = {
    'cimss_wind_analysis': ('cimss_wind_shear', 'cimss_850mb_vorticity'),
    'cimss_steering_flow': tuple('cimss_steering_flow_' + layer for layer in (
        '200_700mb', '250_850mb', '300_850mb', '400_850mb', '500_850mb', '700_850mb')),
    'seaice_arctic': tuple('seaice_arctic_' + view for view in ('extent', 'concentration', 'timeseries')),
    'seaice_antarctic': tuple('seaice_antarctic_' + view for view in ('extent', 'concentration', 'timeseries')),
}
GROUP_CHILDREN = frozenset(child for children in GROUPS.values() for child in children)


def validate_image(image_type, data):
    if data['image_type'] != image_type or any(
        not isinstance(data.get(field), str) or not data[field].strip()
        for field in ('source', 'title', 'image_url', 'source_url', 'fetched_at')
    ):
        raise RuntimeError(f'{image_type}: incomplete metadata')
    for field in ('image_url', 'source_url'):
        url = urlsplit(data[field])
        if url.scheme not in ('https', 'http') or not url.netloc:
            raise RuntimeError(f'{image_type}: invalid {field}')
    if datetime.fromisoformat(data['fetched_at']).utcoffset() != timedelta(0):
        raise RuntimeError(f'{image_type}: fetched_at must be UTC with an offset')
    image_time = data['image_time']
    if image_time is None:
        if image_type != 'weather_chart' and image_type not in GROUP_CHILDREN:
            raise RuntimeError(f'{image_type}: missing image_time')
    elif image_type in ('sst', 'tchp') or image_type.startswith('seaice_'):
        if len(image_time) != 10:
            raise RuntimeError(f'{image_type}: expected product date only')
        date.fromisoformat(image_time)
    elif datetime.fromisoformat(image_time).utcoffset() is None:
        raise RuntimeError(f'{image_type}: image_time must include a timezone')


def publish_image(image_type, payloads, output_path):
    items = [asdict(item) for item in payloads]
    if image_type in GROUPS:
        expected = GROUPS[image_type]
        if len(items) != len(expected) or {item['image_type'] for item in items} != set(expected):
            raise RuntimeError(f'{image_type}: incomplete or duplicate group; previous JSON preserved')
        by_type = {item['image_type']: item for item in items}
        images = [by_type[child] for child in expected]
        for image in images:
            validate_image(image['image_type'], image)
        if len({image['source'] for image in images}) != 1:
            raise RuntimeError(f'{image_type}: inconsistent group sources')
        data = dict(images[0], image_type=image_type, images=images)
    else:
        if len(items) != 1:
            raise RuntimeError(f'{image_type}: expected exactly one image; previous JSON preserved')
        data = items[0]
        validate_image(image_type, data)
    return atomic_write_json(data, output_path, prefix=f'.{image_type}-')


def atomic_write_json(data, output_path, prefix='.data-'):
    """Serialize before touching the destination; use one atomic writer for all resources."""
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', newline='\n', dir=output_path.parent,
            prefix=prefix, suffix='.tmp', delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return data
