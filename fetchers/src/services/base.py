from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests

from ..http_client import http_get


@dataclass
class ImagePayload:
    image_type: str
    source: str
    title: str
    image_url: str
    source_url: str
    fetched_at: str
    image_time: str | None = None


class BaseImageService:
    source_name = ""

    def fetch(self) -> Iterable[ImagePayload]:
        raise NotImplementedError

    def build_payload(
        self,
        image_type: str,
        title: str,
        image_url: str,
        source_url: str,
        image_time: str | None = None,
    ) -> ImagePayload:
        return ImagePayload(
            image_type=image_type,
            source=self.source_name,
            title=title,
            image_url=image_url,
            source_url=source_url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            image_time=image_time,
        )

    def request_placeholder(self, url: str) -> None:
        try:
            http_get(url, timeout=5)
        except requests.RequestException:
            # Placeholder fetch failures should not stop the pipeline.
            return
