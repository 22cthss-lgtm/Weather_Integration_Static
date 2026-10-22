"""Publish registered latest-image resources, without Flask or a database."""

import argparse
from pathlib import Path
import sys

from src.publication import publish_image
from src.services.cwa_service import CWAService
from src.services.kma_service import KMAService
from src.services.ocean_service import OceanService


OUTPUT_ROOT = Path(__file__).resolve().parent.parent / 'frontend/public/data/images'
PRODUCTS = {
    'sst': (OceanService, 'fetch'),
    'temperature': (CWAService, 'fetch_temperature'),
    'weather_chart': (CWAService, 'fetch_weather_chart'),
    '850hpa': (KMAService, 'fetch_850hpa'),
    'tchp': (CWAService, 'fetch_tchp'),
}


def update_image(image_type, output_root=OUTPUT_ROOT):
    service_class, method = PRODUCTS[image_type]
    service = service_class()

    def verified_payloads():
        for payload in getattr(service, method)():
            # SST already checks the image response in its resolver. The other
            # services may only have read a metadata page or JavaScript file.
            if image_type != 'sst' and not service.image_exists(payload.image_url):
                raise RuntimeError(f'{image_type}: image URL did not return an image')
            yield payload

    return publish_image(image_type, verified_payloads(), Path(output_root) / image_type / 'latest.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('types', nargs='*', help='Product names; default: all registered products')
    parser.add_argument('--output-root', type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    unknown = set(args.types) - PRODUCTS.keys()
    if unknown:
        parser.error(f'Unknown products: {", ".join(sorted(unknown))}')
    failed = False
    for kind in dict.fromkeys(args.types or PRODUCTS):
        try:
            data = update_image(kind, args.output_root)
            print(f'{kind}: updated; image_time={data["image_time"]}; fetched_at={data["fetched_at"]}')
        except Exception as exc:
            failed = True
            print(f'{kind}: update failed; previous JSON preserved: {exc}', file=sys.stderr)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
