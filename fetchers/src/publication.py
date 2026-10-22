"""Validate a single image resource and atomically publish its JSON."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


def publish_image(image_type, payloads, output_path):
    items = list(payloads)
    if len(items) != 1:
        raise RuntimeError(f'{image_type}: expected exactly one image; previous JSON preserved')
    data = asdict(items[0])
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
        if image_type != 'weather_chart':
            raise RuntimeError(f'{image_type}: missing image_time')
    elif image_type in ('sst', 'tchp'):
        if len(image_time) != 10:
            raise RuntimeError(f'{image_type}: expected product date only')
        date.fromisoformat(image_time)
    elif datetime.fromisoformat(image_time).utcoffset() is None:
        raise RuntimeError(f'{image_type}: image_time must include a timezone')
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', newline='\n', dir=output_path.parent,
            prefix=f'.{image_type}-', suffix='.tmp', delete=False,
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
