"""Publish the latest real JMA SST metadata without Flask or a database."""

from pathlib import Path
import sys

from src.services.ocean_service import OceanService
from src.publication import publish_image
from src.update_runner import UpdateInProgress, run_batch


OUTPUT_PATH = Path(__file__).resolve().parent.parent / "frontend/public/data/images/sst/latest.json"


def update_sst(output_path: Path = OUTPUT_PATH) -> dict:
    return publish_image("sst", OceanService().fetch(), output_path)


def main() -> int:
    try:
        return run_batch(['sst'], OUTPUT_PATH.parent.parent, lambda kind, root: update_sst())
    except UpdateInProgress:
        print('Another update is already running for this output directory.', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
