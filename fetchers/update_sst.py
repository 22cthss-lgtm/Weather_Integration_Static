"""Publish the latest real JMA SST metadata without Flask or a database."""

from dataclasses import asdict
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
import tempfile

from src.services.ocean_service import OceanService


OUTPUT_PATH = Path(__file__).resolve().parent.parent / "frontend/public/data/images/sst/latest.json"


def update_sst(output_path: Path = OUTPUT_PATH) -> dict:
    payloads = list(OceanService().fetch())
    if len(payloads) != 1:
        raise RuntimeError("JMA SST fetch must return exactly one image; previous JSON was preserved")
    data = asdict(payloads[0])
    if data["image_type"] != "sst" or any(
        not isinstance(data.get(field), str) or not data[field].strip()
        for field in ("source", "title", "image_url", "source_url", "fetched_at", "image_time")
    ):
        raise RuntimeError("JMA SST metadata is incomplete; previous JSON was preserved")
    date.fromisoformat(data["image_time"])
    if datetime.fromisoformat(data["fetched_at"]).utcoffset() is None:
        raise RuntimeError("JMA SST fetched_at must include a timezone")
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    # Validate and serialize before touching the destination. Replace on the same
    # filesystem so readers never see a partially written JSON file.
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output_path.parent,
            prefix=".sst-", suffix=".tmp", delete=False,
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
