"""Publish the latest real JMA SST metadata without Flask or a database."""

from pathlib import Path
import sys

from src.services.ocean_service import OceanService
from src.publication import publish_image


OUTPUT_PATH = Path(__file__).resolve().parent.parent / "frontend/public/data/images/sst/latest.json"


def update_sst(output_path: Path = OUTPUT_PATH) -> dict:
    return publish_image("sst", OceanService().fetch(), output_path)


def main() -> int:
    try:
        data = update_sst()
    except Exception as exc:
        print(f"SST update failed; previous JSON was preserved: {exc}", file=sys.stderr)
        return 1
    print(f"Updated {OUTPUT_PATH}\nProduct date: {data['image_time']}\nFetched at: {data['fetched_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
