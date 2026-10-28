from datetime import datetime, timezone
import re

import requests

from ..http_client import http_get

from .base import BaseImageService


class OceanService(BaseImageService):
    source_name = "JMA"
    sst_source_url = "https://www.data.jma.go.jp/goos/data/rrtdb/jma-pro/him_sst_pac_D.html"
    sst_date_script_url = "https://www.data.jma.go.jp/goos/data/rrtdb/jma-pro/js/date_day_him.js"
    sst_image_base_url = "https://www.data.jma.go.jp/goos/data/pub/JMA-product/IMAGE/him_sst_pac_D"
    latest_date_regex = re.compile(
        r"var yye = (?P<year>\d{4}); var mme = (?P<month>\d{2}); var dde = (?P<day>\d{2});"
    )

    def resolve_latest_sst_image(self) -> tuple[str, str] | None:
        session = requests.Session()
        session.headers.update(
            {
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )

        try:
            try:
                date_script = http_get(self.sst_date_script_url, session=session, timeout=15)
                date_script.raise_for_status()
            except requests.RequestException as exc:
                raise RuntimeError(f"JMA SST date request failed: {exc}") from exc

            match = self.latest_date_regex.search(date_script.text)
            if match is None:
                raise RuntimeError("JMA SST latest product date was not found in date script")

            display_date = f"{match.group('year')}-{match.group('month')}-{match.group('day')}"
            try:
                datetime.strptime(display_date, "%Y-%m-%d")
            except ValueError as exc:
                raise RuntimeError(f"JMA SST product date is invalid: {display_date}") from exc
            date_string = display_date.replace("-", "")
            image_url = f"{self.sst_image_base_url}/{match.group('year')}/him_sst_pac_D{date_string}.gif"

            try:
                with http_get(image_url, session=session, timeout=15, stream=True) as response:
                    response.raise_for_status()
                    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                        raise RuntimeError("JMA SST image URL did not return an image")
            except requests.RequestException as exc:
                raise RuntimeError(f"JMA SST image request failed: {exc}") from exc
            return image_url, display_date
        finally:
            session.close()

    def fetch_sst(self):
        resolved = self.resolve_latest_sst_image()
        if resolved is None:
            raise RuntimeError("JMA SST image could not be resolved")

        image_url, display_date = resolved
        fetched_marker = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cache_busted_url = f"{image_url}?fetched={fetched_marker}"
        yield self.build_payload(
            "sst",
            f"JMA Sea Surface Temperature Western North Pacific {display_date}",
            cache_busted_url,
            self.sst_source_url,
            # Daily analysis date, not an observation instant or the fetch time.
            image_time=display_date,
        )

    def fetch(self):
        yield from self.fetch_sst()
