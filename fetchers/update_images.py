"""Publish registered latest-image resources, without Flask or a database."""

import argparse
from pathlib import Path
import sys

from src.publication import publish_image
from src.services.cwa_service import CWAService
from src.services.cimss_service import CIMSSService
from src.services.nsidc_service import NSIDCService
from src.services.kma_service import KMAService
from src.services.ocean_service import OceanService
from src.current_day import CURRENT_PRODUCTS, update_current_product
from src.rainfall_rankings import update_rankings


OUTPUT_ROOT = Path(__file__).resolve().parent.parent / 'frontend/public/data/images'
PRODUCTS = {
    'sst': (OceanService, 'fetch'),
    'temperature': (CWAService, 'fetch_temperature'),
    'weather_chart': (CWAService, 'fetch_weather_chart'),
    '850hpa': (KMAService, 'fetch_850hpa'),
    'tchp': (CWAService, 'fetch_tchp'),
}

GROUP_PRODUCTS = {
    'cimss_wind_analysis': (CIMSSService, 'fetch_wind_analysis'),
    'cimss_steering_flow': (CIMSSService, 'fetch_steering_flow'),
    'seaice_arctic': (NSIDCService, 'fetch_arctic'),
    'seaice_antarctic': (NSIDCService, 'fetch_antarctic'),
}


def update_image(image_type, output_root=OUTPUT_ROOT):
    if image_type in CURRENT_PRODUCTS:
        return update_current_product(image_type, output_root)
    if image_type == 'rainfall_rankings':
        return update_rankings(Path(output_root).parent / 'rainfall/rankings/latest.json')
    service_class, method = (GROUP_PRODUCTS if image_type in GROUP_PRODUCTS else PRODUCTS)[image_type]
    service = service_class()

    def verified_payloads():
        for payload in getattr(service, method)():
            # SST and group Services verify image responses in their resolvers.
            # The other Services may only have read metadata pages or scripts.
            if image_type != 'sst' and image_type not in GROUP_PRODUCTS and not service.image_exists(payload.image_url):
                raise RuntimeError(f'{image_type}: image URL did not return an image')
            yield payload

    return publish_image(image_type, verified_payloads(), Path(output_root) / image_type / 'latest.json')


def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', encoding='utf-8-sig')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('types', nargs='*', help='Product names; default: all registered products')
    parser.add_argument('--output-root', type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    registered = PRODUCTS | GROUP_PRODUCTS | dict.fromkeys((*CURRENT_PRODUCTS, 'rainfall_rankings'))
    unknown = set(args.types) - registered.keys()
    if unknown:
        parser.error(f'Unknown products: {", ".join(sorted(unknown))}')
    failed = False
    for kind in dict.fromkeys(args.types or registered):
        try:
            data = update_image(kind, args.output_root)
            print(f'{kind}: updated; image_time={data.get("image_time")}; fetched_at={data["fetched_at"]}')
        except Exception as exc:
            failed = True
            message = ('update incomplete; successful resources kept; failed resources preserved'
                       if kind in CURRENT_PRODUCTS else 'update failed; previous JSON preserved')
            print(f'{kind}: {message}: {exc}', file=sys.stderr)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
