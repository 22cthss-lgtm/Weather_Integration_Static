from datetime import datetime, timedelta, timezone

import requests

from ..http_client import HttpFailure, http_get

from .base import BaseImageService


class KMAService(BaseImageService):
    source_name = "KMA"
    analysis_chart_url = "https://www.kma.go.kr/nchn/image/chart/analysis-chart.do"
    analysis_image_api_url = "https://www.weather.go.kr/w/wnuri-img/rest/cht/images/analysis.do"
    weather_base_url = "https://www.weather.go.kr"
    image_prefix = f"{weather_base_url}/w/repositary/image/cht/img"
    image_pattern = "up85_{timestamp}.png"

    @staticmethod
    def no_cache_headers() -> dict[str, str]:
        return {
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        }

    def image_exists(self, image_url: str) -> bool:
        try:
            with http_get(image_url, timeout=10, stream=True,
                          headers=self.no_cache_headers(),
                          params={"_": datetime.now(timezone.utc).timestamp()}) as response:
                if response.status_code in (404, 410):
                    return False
                response.raise_for_status()
                if not (response.headers.get('Content-Type') or '').lower().startswith('image/'):
                    raise RuntimeError('KMA candidate validation failed')
                if not next(response.iter_content(chunk_size=1), b''):
                    raise RuntimeError('KMA candidate validation failed')
                return True
        except requests.RequestException:
            raise RuntimeError('KMA candidate source failed') from None

    def resolve_latest_850hpa_image_by_probe(self) -> tuple[str, str] | None:
        now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        rounded_hour = now_utc.hour - (now_utc.hour % 6)
        candidate = now_utc.replace(hour=rounded_hour)

        for offset in range(0, 15):
            candidate_time = candidate - timedelta(hours=offset * 6)
            timestamp = candidate_time.strftime("%Y%m%d%H")
            image_url = f"{self.image_prefix}/{self.image_pattern.format(timestamp=timestamp)}"
            if self.image_exists(image_url):
                display_time = (candidate_time + timedelta(hours=9)).strftime("%Y-%m-%d %H:00")
                return image_url, display_time

        return None

    def resolve_850hpa_image_url(self) -> tuple[str, str] | None:
        candidate = None
        try:
            with http_get(self.analysis_image_api_url, timeout=10,
                          headers=self.no_cache_headers(),
                          params={"type": "M", "data": "up85",
                                  "_": datetime.now(timezone.utc).timestamp()}) as response:
                response.raise_for_status()
                items = response.json()
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    image_path, image_tm = items[0].get('url'), items[0].get('tm')
                    if isinstance(image_path, str) and image_path and isinstance(image_tm, str):
                        image_time = datetime.strptime(image_tm, '%Y%m%d%H').strftime('%Y-%m-%d %H:00')
                        image_url = f'{self.weather_base_url}{image_path}' if image_path.startswith('/') else image_path
                        candidate = image_url, image_time
        except HttpFailure:
            # Common retries/source budget are exhausted; do not fan out probes.
            raise RuntimeError('KMA index source failed') from None
        except (requests.RequestException, ValueError, TypeError):
            pass
        if candidate and self.image_exists(candidate[0]):
            return candidate
        return self.resolve_latest_850hpa_image_by_probe()

    def fetch_850hpa(self):
        resolved = self.resolve_850hpa_image_url()
        if resolved is None:
            return

        image_url, display_time = resolved
        yield self.build_payload(
            "850hpa",
            f"KMA 850hPa Analysis {display_time}",
            image_url,
            self.analysis_chart_url,
            image_time=datetime.strptime(display_time, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone(timedelta(hours=9))
            ).isoformat(),
        )

    def fetch(self):
        yield from self.fetch_850hpa()
