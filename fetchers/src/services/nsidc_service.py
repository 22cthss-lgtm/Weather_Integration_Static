from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

import requests

from .base import BaseImageService


class NSIDCService(BaseImageService):
    source_name = "NSIDC"
    sea_ice_today_url = "https://nsidc.org/sea-ice-today"
    extent_image_url = "https://nsidc.org/data/seaice_index/images/daily_images/N_daily_extent_hires.png"
    concentration_image_url = "https://nsidc.org/data/seaice_index/images/daily_images/N_daily_concentration_hires.png"
    timeseries_image_url = "https://nsidc.org/data/seaice_index/images/daily_images/N_iqr_timeseries.png"
    antarctic_extent_image_url = "https://nsidc.org/data/seaice_index/images/daily_images/S_daily_extent_hires.png"
    antarctic_concentration_image_url = "https://nsidc.org/data/seaice_index/images/daily_images/S_daily_concentration_hires.png"
    antarctic_timeseries_image_url = "https://nsidc.org/data/seaice_index/images/daily_images/S_iqr_timeseries.png"
    month_names_regex = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    image_date_regex = re.compile(
        rf"(?:Sea Ice Extent|Sea Ice Concentration|Arctic Sea Ice Extent(?: Time Series)?|Antarctic Sea Ice Extent(?: Time Series)?).*?(\d{{2}} {month_names_regex} \d{{4}})"
    )

    @staticmethod
    def no_cache_headers() -> dict[str, str]:
        return {
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        }

    def fetch_page_html(self) -> str | None:
        try:
            response = requests.get(
                self.sea_ice_today_url,
                timeout=20,
                headers=self.no_cache_headers(),
                params={"_": int(datetime.now(timezone.utc).timestamp())},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            return None

    def fetch_image_response(self, image_url: str) -> requests.Response | None:
        response = None
        try:
            response = requests.get(
                image_url,
                timeout=20,
                headers=self.no_cache_headers(),
                params={"_": int(datetime.now(timezone.utc).timestamp())},
            )
            response.raise_for_status()
            if not response.content or not (response.headers.get('Content-Type') or '').lower().startswith('image/'):
                response.close()
                return None
            return response
        except requests.RequestException:
            if response is not None:
                response.close()
            return None

    def extract_image_time_from_bytes(self, image_bytes: bytes) -> str | None:
        if not image_bytes:
            return None

        text = image_bytes.decode("latin1", errors="ignore")
        match = self.image_date_regex.search(text)
        if match is None:
            return None

        parsed_date = datetime.strptime(match.group(1), "%d %b %Y")
        return parsed_date.strftime("%Y-%m-%d")

    def extract_image_time_from_headers(self, response: requests.Response) -> str | None:
        last_modified = response.headers.get("Last-Modified")
        if not last_modified:
            return None

        parsed_date = parsedate_to_datetime(last_modified)
        return parsed_date.strftime("%Y-%m-%d")

    def resolve_image_time(self, image_url: str) -> str | None:
        response = self.fetch_image_response(image_url)
        if response is None:
            raise RuntimeError("NSIDC image request failed")

        try:
            image_time = self.extract_image_time_from_bytes(response.content)
            if image_time:
                return image_time
            # A file modification date is not the daily product date.
            return None
        finally:
            response.close()

    def resolve_image_set(self, required_urls: dict[str, str]) -> dict[str, dict[str, str | None]] | None:
        page_html = self.fetch_page_html()
        if page_html is None:
            return None

        if not all(image_url in page_html for image_url in required_urls.values()):
            return None

        resolved_images: dict[str, dict[str, str | None]] = {}
        for image_type, image_url in required_urls.items():
            image_time = self.resolve_image_time(image_url)
            resolved_images[image_type] = {
                "image_url": image_url,
                "image_time": image_time,
            }

        return resolved_images

    def resolve_latest_arctic_sea_ice_images(self) -> dict[str, dict[str, str | None]] | None:
        return self.resolve_image_set(
            {
                "seaice_arctic_extent": self.extent_image_url,
                "seaice_arctic_concentration": self.concentration_image_url,
                "seaice_arctic_timeseries": self.timeseries_image_url,
            }
        )

    def resolve_latest_antarctic_sea_ice_images(self) -> dict[str, dict[str, str | None]] | None:
        return self.resolve_image_set(
            {
                "seaice_antarctic_extent": self.antarctic_extent_image_url,
                "seaice_antarctic_concentration": self.antarctic_concentration_image_url,
                "seaice_antarctic_timeseries": self.antarctic_timeseries_image_url,
            }
        )

    def emit_payloads(
        self,
        resolved_images: dict[str, dict[str, str | None]] | None,
        titles: dict[str, str],
        image_types: tuple[str, str, str],
    ):
        if resolved_images is None:
            return

        for image_type in image_types:
            resolved = resolved_images[image_type]
            yield self.build_payload(
                image_type,
                titles[image_type] + (f" {resolved['image_time']}" if resolved["image_time"] else ""),
                f"{resolved['image_url']}?ts={int(datetime.now(timezone.utc).timestamp())}",
                self.sea_ice_today_url,
                image_time=resolved["image_time"],
            )

    def fetch(self):
        yield from self.fetch_arctic()
        yield from self.fetch_antarctic()

    def fetch_arctic(self):
        yield from self.emit_payloads(
            self.resolve_latest_arctic_sea_ice_images(),
            {
                "seaice_arctic_extent": "NSIDC Arctic Sea Ice Extent",
                "seaice_arctic_concentration": "NSIDC Arctic Sea Ice Concentration",
                "seaice_arctic_timeseries": "NSIDC Arctic Sea Ice Extent Time Series",
            },
            ("seaice_arctic_extent", "seaice_arctic_concentration", "seaice_arctic_timeseries"),
        )

    def fetch_antarctic(self):
        yield from self.emit_payloads(
            self.resolve_latest_antarctic_sea_ice_images(),
            {
                "seaice_antarctic_extent": "NSIDC Antarctic Sea Ice Extent",
                "seaice_antarctic_concentration": "NSIDC Antarctic Sea Ice Concentration",
                "seaice_antarctic_timeseries": "NSIDC Antarctic Sea Ice Extent Time Series",
            },
            (
                "seaice_antarctic_extent",
                "seaice_antarctic_concentration",
                "seaice_antarctic_timeseries",
            ),
        )
