from datetime import datetime, timedelta, timezone

import requests

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
            response = requests.get(
                image_url,
                timeout=10,
                stream=True,
                headers=self.no_cache_headers(),
                params={"_": datetime.now(timezone.utc).timestamp()},
            )
            exists = response.ok and (response.headers.get("content-type") or "").startswith("image/")
            response.close()
            return exists
        except requests.RequestException:
            return False

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
        try:
            response = requests.get(
                self.analysis_image_api_url,
                timeout=10,
                headers=self.no_cache_headers(),
                params={
                    "type": "M",
                    "data": "up85",
                    "_": datetime.now(timezone.utc).timestamp(),
                },
            )
            response.raise_for_status()
            items = response.json()
            if items:
                latest_item = items[0]
                image_path = latest_item.get("url", "")
                image_tm = latest_item.get("tm", "")
                if image_path and image_tm:
                    image_url = image_path
                    if image_url.startswith("/"):
                        image_url = f"{self.weather_base_url}{image_url}"
                    image_time = datetime.strptime(image_tm, "%Y%m%d%H").strftime("%Y-%m-%d %H:00")
                    return image_url, image_time
        except requests.RequestException:
            pass

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
