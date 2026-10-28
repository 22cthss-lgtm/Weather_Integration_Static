"""Check deployed JSON hashes, all static routes and base-path assets after build."""
import argparse
import hashlib
import json
from pathlib import Path
from src.snapshots import read_resources, IMAGE_TYPES
from src.pages_package import site_summary


def verify_build(public_data, output, base, manifest_path):
    if not base.startswith('/') or not base.endswith('/') or '..' in base or '//' in base:
        raise ValueError('Invalid Pages base')
    public_data, output = Path(public_data), Path(output)
    before, _ = read_resources(public_data)
    after, _ = read_resources(output / 'data')
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in after.items()}
    site_summary(public_data)
    if before != after or hashes != manifest['files']:
        raise ValueError('Built data does not match selected snapshot')
    html = (output / 'index.html').read_bytes()
    if f'{base}assets/'.encode() not in html:
        raise ValueError('Build does not use selected base path')
    for kind in IMAGE_TYPES:
        if (output / 'images' / kind / 'index.html').read_bytes() != html:
            raise ValueError('A static detail entry is missing or inconsistent')
    if not (output / 'Hero_Section_Image.jpeg').is_file():
        raise ValueError('Hero asset is missing')
    return {'verified_json_files': len(after), 'detail_entries': len(IMAGE_TYPES),
            'data_sha256': {name: hashlib.sha256(content).hexdigest() for name, content in after.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_build(args.data, args.output, args.base, args.manifest), indent=2))
