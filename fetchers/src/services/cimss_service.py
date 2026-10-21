from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

import requests

from .base import BaseImageService


class CIMSSService(BaseImageService):
    source_name = "CIMSS"
    source_page_url = "https://tropic.ssec.wisc.edu/real-time/windmain.php?&basin=westpac&sat=wgms&prod=shr&zoom=&time="
    steering_flow_page_url = (
        "https://tropic.ssec.wisc.edu/real-time/dlmmain.php?&basin=westpac&sat=wgms&prod=dlm1&zoom=&time="
    )
    shear_image_url = "https://tropic.ssec.wisc.edu/real-time/westpac/winds/wgmsshr.GIF"
    vorticity_image_url = "https://tropic.ssec.wisc.edu/real-time/westpac/winds/wgmsvor.GIF"
    steering_flow_layers = (
        ("cimss_steering_flow_700_850mb", "700 - 850 mb", "wgmsdlm1.GIF"),
        ("cimss_steering_flow_500_850mb", "500 - 850 mb", "wgmsdlm2.GIF"),
        ("cimss_steering_flow_400_850mb", "400 - 850 mb", "wgmsdlm3.GIF"),
        ("cimss_steering_flow_300_850mb", "300 - 850 mb", "wgmsdlm4.GIF"),
        ("cimss_steering_flow_250_850mb", "250 - 850 mb", "wgmsdlm5.GIF"),
        ("cimss_steering_flow_200_700mb", "200 - 700 mb", "wgmsdlm6.GIF"),
    )
    embedded_time_patterns = (
        re.compile(
            r"(?P<hour>\d{2})\s*UTC\s*(?P<day>\d{1,2})\s*(?P<month>[A-Z]{3})\s*(?P<year>\d{4})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<year>\d{4})[-/](?P<month>\d{2})[-/](?P<day>\d{2})\s+(?P<hour>\d{2}):(?P<minute>\d{2})"
        ),
    )
    month_lookup = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }

    @staticmethod
    def no_cache_headers() -> dict[str, str]:
        return {
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        }

    def cache_buster(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())

    def fetch_page_html(self) -> str | None:
        try:
            response = requests.get(
                self.source_page_url,
                timeout=20,
                headers=self.no_cache_headers(),
                params={"_": self.cache_buster()},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            return None

    def fetch_specific_page_html(self, page_url: str) -> str | None:
        try:
            response = requests.get(
                page_url,
                timeout=20,
                headers=self.no_cache_headers(),
                params={"_": self.cache_buster()},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            return None

    def fetch_image_response(self, image_url: str) -> requests.Response | None:
        try:
            response = requests.get(
                image_url,
                timeout=20,
                headers=self.no_cache_headers(),
                params={"_": self.cache_buster()},
            )
            response.raise_for_status()
            return response
        except requests.RequestException:
            return None

    def extract_image_time_from_bytes(self, image_bytes: bytes) -> str | None:
        if not image_bytes:
            return None

        text = image_bytes.decode("latin1", errors="ignore")
        utc_match = self.embedded_time_patterns[0].search(text)
        if utc_match is not None:
            parsed = datetime(
                year=int(utc_match.group("year")),
                month=self.month_lookup[utc_match.group("month").upper()],
                day=int(utc_match.group("day")),
                hour=int(utc_match.group("hour")),
                minute=0,
            )
            return parsed.strftime("%Y-%m-%d %H:%M")

        iso_match = self.embedded_time_patterns[1].search(text)
        if iso_match is not None:
            parsed = datetime(
                year=int(iso_match.group("year")),
                month=int(iso_match.group("month")),
                day=int(iso_match.group("day")),
                hour=int(iso_match.group("hour")),
                minute=int(iso_match.group("minute")),
            )
            return parsed.strftime("%Y-%m-%d %H:%M")

        return None

    def extract_image_time_from_headers(self, response: requests.Response) -> str | None:
        last_modified = response.headers.get("Last-Modified")
        if not last_modified:
            return None

        parsed = parsedate_to_datetime(last_modified)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y-%m-%d %H:%M")

    def resolve_image_time(self, response: requests.Response) -> str | None:
        image_time = self.extract_image_time_from_bytes(response.content)
        if image_time is not None:
            return image_time
        return self.extract_image_time_from_headers(response)

    def resolve_latest_wind_analysis_images(self) -> dict[str, dict[str, str]] | None:
        page_html = self.fetch_page_html()
        if page_html is None or "westpac/winds/wgmsshr.GIF" not in page_html:
            return None

        resolved_images: dict[str, dict[str, str]] = {}
        image_map = {
            "cimss_wind_shear": self.shear_image_url,
            "cimss_850mb_vorticity": self.vorticity_image_url,
        }

        for image_type, image_url in image_map.items():
            response = self.fetch_image_response(image_url)
            if response is None:
                return None
            try:
                image_time = self.resolve_image_time(response)
                if image_time is None:
                    return None
                resolved_images[image_type] = {
                    "image_url": f"{image_url}?ts={self.cache_buster()}",
                    "image_time": image_time,
                }
            finally:
                response.close()

        return resolved_images

    def resolve_latest_steering_flow_images(self) -> dict[str, dict[str, str]] | None:
        page_html = self.fetch_specific_page_html(self.steering_flow_page_url)
        if page_html is None:
            return None

        if "wgmsdlm1.GIF" not in page_html and "prod=dlm1" not in page_html:
            return None

        resolved_images: dict[str, dict[str, str]] = {}

        for image_type, _, image_name in self.steering_flow_layers:
            image_url = f"https://tropic.ssec.wisc.edu/real-time/westpac/winds/{image_name}"
            response = self.fetch_image_response(image_url)
            if response is None:
                return None
            try:
                image_time = self.resolve_image_time(response)
                if image_time is None:
                    return None
                resolved_images[image_type] = {
                    "image_url": f"{image_url}?ts={self.cache_buster()}",
                    "image_time": image_time,
                }
            finally:
                response.close()

        return resolved_images

    def fetch_wind_analysis(self):
        resolved_images = self.resolve_latest_wind_analysis_images()
        if resolved_images is None:
            return

        titles = {
            "cimss_wind_shear": "CIMSS Wind Shear",
            "cimss_850mb_vorticity": "CIMSS 850mb Vorticity",
        }
        for image_type in ("cimss_wind_shear", "cimss_850mb_vorticity"):
            resolved = resolved_images[image_type]
            yield self.build_payload(
                image_type,
                f"{titles[image_type]} {resolved['image_time']}",
                resolved["image_url"],
                self.source_page_url,
            )

    def fetch_steering_flow(self):
        resolved_images = self.resolve_latest_steering_flow_images()
        if resolved_images is None:
            return

        for image_type, layer_label, _ in self.steering_flow_layers:
            resolved = resolved_images[image_type]
            yield self.build_payload(
                image_type,
                f"CIMSS Steering Flow {layer_label} {resolved['image_time']}",
                resolved["image_url"],
                self.steering_flow_page_url,
            )

    def fetch(self):
        yield from self.fetch_wind_analysis()
