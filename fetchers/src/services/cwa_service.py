from datetime import date, datetime, timedelta
import re
from zoneinfo import ZoneInfo

import requests

from ..http_client import HttpFailure, http_get
from ..history_reconciliation import current_history_context
import urllib3

from .base import BaseImageService

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _candidate_event(category, *, fatal=False):
    """Record safe counters only; no URL, raw response or exception text."""
    context = current_history_context()
    if context is None:
        return
    kind = getattr(context, 'active_kind', None)
    if isinstance(kind, str) and kind:
        field = f'candidate_{category}_count'
        count = context.outcomes.get(kind, {}).get(field, 0)
        context.outcome(kind, **{field: count + 1})
    if fatal:
        code = 'candidate_validation_error' if category == 'invalid' else 'candidate_source_error'
        raise RuntimeError(code) from None


def _index_fault(error):
    response = getattr(error, 'response', None)
    if response is not None and response.status_code in (404, 410):
        _candidate_event('missing')
    else:
        _candidate_event('fault', fatal=True)


class CWAService(BaseImageService):
    source_name = "CWA"
    cwa_base_url = "https://www.cwa.gov.tw"
    satellite_source_url = "https://www.cwa.gov.tw/V8/C/W/OBS_Sat.html"
    satellite_image_prefix = "https://www.cwa.gov.tw/Data/satellite/LCC_IR1_CR_2750"
    satellite_image_pattern = "LCC_IR1_CR_2750-{timestamp}.jpg"
    radar_source_url = "https://www.cwa.gov.tw/V8/C/W/OBS_Radar.html"
    radar_data_url = "https://www.cwa.gov.tw/Data/js/obs_img/Observe_radar.js"
    radar_image_prefix = "https://www.cwa.gov.tw/Data/radar"
    radar_image_pattern = "CV1_3600_{timestamp}.png"
    radar_data_regex = re.compile(r"""0:\{"img":'(?P<filename>CV1_3600_(?P<timestamp>\d{12})\.png)',\s*'text':'(?P<text>\d{4}/\d{2}/\d{2} \d{2}:\d{2})'\}""")
    radar_image_regex = re.compile(r"(?:https://www\.cwa\.gov\.tw)?(/Data/radar/CV1_3600_(\d{12})\.png)")
    temperature_data_url = "https://www.cwa.gov.tw/Data/js/obs_img/Observe_temp.js"
    rainfall_data_url = "https://www.cwa.gov.tw/Data/js/rainfall/RainfallImg_Day.js"
    temperature_source_url = "https://www.cwa.gov.tw/V8/C/W/OBS_Temp.html"
    temperature_image_prefix = "https://www.cwa.gov.tw/Data/temperature"
    temperature_image_pattern = "{timestamp}.GTP8w.jpg"
    temperature_image_regex = re.compile(
        r"(?:https://www\.cwa\.gov\.tw)?(?P<path>/Data/temperature/(?P<timestamp>\d{4}-\d{2}-\d{2}_\d{4})\.GTP8w\.jpg)"
    )
    rainfall_source_url = "https://www.cwa.gov.tw/V8/C/P/Rainfall/Rainfall_QZJ.html"
    rainfall_image_prefix = "https://www.cwa.gov.tw/Data/rainfall"
    rainfall_image_pattern = "{timestamp}.QZJ8.jpg"
    rainfall_image_regex = re.compile(
        r"(?:https://www\.cwa\.gov\.tw)?(?P<path>/Data/rainfall/(?P<timestamp>\d{4}-\d{2}-\d{2}_\d{4})\.QZJ8\.jpg)"
    )
    weather_chart_source_url = "https://www.cwa.gov.tw/V8/C/W/analysis.html"
    weather_chart_image_url = "https://www.cwa.gov.tw/Data/fcst_img/FI04.png"
    weather_chart_image_regex = re.compile(
        r"(?:https://www\.cwa\.gov\.tw)?(?P<path>/Data/fcst_img/FI04\.png\?t=(?P<timestamp>\d{10}-\d+))"
    )
    tchp_data_url = "https://www.cwa.gov.tw/Data/js/TDD_TCHP.js"
    tchp_image_regex = re.compile(
        r"""var\s+TDD_TCHP\s*=\s*['"](?P<filename>(?P<date>\d{4}-\d{2}-\d{2})_TCHP_[^'"]+\.png)['"]"""
    )
    satellite_timezone = ZoneInfo("Asia/Taipei")
    satellite_publish_delay_minutes = 30
    satellite_slot_minutes = 10
    radar_publish_delay_minutes = 20
    radar_slot_minutes = 10
    temperature_publish_delay_minutes = 20
    rainfall_publish_delay_minutes = 20
    rainfall_slot_minutes = 30

    @staticmethod
    def no_cache_headers() -> dict[str, str]:
        return {
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        }

    def image_exists(self, image_url: str) -> bool:
        response = None
        try:
            response = http_get(
                image_url,
                timeout=5,
                stream=True,
                headers=self.no_cache_headers(),
                params={"_": datetime.now(self.satellite_timezone).timestamp()},
                verify=False,
            )
            if response.status_code in (404, 410):
                _candidate_event('missing')
                return False
            if not response.ok:
                _candidate_event('fault', fatal=True)
                return False
            exists = (response.headers.get('Content-Type') or response.headers.get("content-type") or "").lower().startswith("image/")
            if not exists:
                _candidate_event('invalid', fatal=True)
            elif current_history_context() is not None and not next(response.iter_content(chunk_size=1), b''):
                _candidate_event('invalid', fatal=True)
            return exists
        except requests.RequestException:
            _candidate_event('fault', fatal=True)
            return False
        finally:
            if response is not None:
                response.close()

    def check_image_url(self, image_url: str) -> bool:
        """Distinguish absent slots (404/410) from transient source failures."""
        try:
            with http_get(image_url, timeout=15, stream=True,
                              headers=self.no_cache_headers(), verify=False) as response:
                if response.status_code in (404, 410):
                    _candidate_event('missing')
                    return False
                response.raise_for_status()
                if not (response.headers.get('Content-Type') or '').lower().startswith('image/'):
                    _candidate_event('invalid', fatal=True)
                    raise RuntimeError('CWA URL did not return an image')
                if not next(response.iter_content(chunk_size=1), b''):
                    _candidate_event('invalid', fatal=True)
                    raise RuntimeError('CWA image response was empty')
                return True
        except requests.RequestException:
            _candidate_event('fault', fatal=True)
            raise RuntimeError('CWA image request failed') from None

    def fetch_rainfall_day_script(self) -> str:
        try:
            with http_get(f'{self.cwa_base_url}/Data/js/rainfall/RainfallImg_Day.js',
                              timeout=20, headers=self.no_cache_headers(), verify=False) as response:
                response.raise_for_status()
                return response.text
        except requests.RequestException:
            raise RuntimeError('CWA daily rainfall index request failed') from None

    def resolve_latest_image(
        self,
        *,
        image_prefix: str,
        image_pattern: str,
        publish_delay_minutes: int,
        excluded_urls=(),
    ) -> tuple[str, str] | None:
        context = current_history_context()
        now = (context.now if context else datetime.now(self.satellite_timezone)).astimezone(self.satellite_timezone).replace(second=0, microsecond=0)
        delayed_now = now - timedelta(minutes=publish_delay_minutes)
        step = self.rainfall_slot_minutes if image_pattern == self.rainfall_image_pattern else 10
        rounded_now = delayed_now - timedelta(minutes=delayed_now.minute % step)

        for offset in range(0, 360, step):
            candidate_time = rounded_now - timedelta(minutes=offset)
            if image_pattern == self.rainfall_image_pattern and candidate_time.hour == 0 and candidate_time.minute == 0:
                continue  # Midnight is a completed daily product, not latest.
            timestamp = candidate_time.strftime("%Y%m%d%H%M")
            if image_pattern == self.satellite_image_pattern:
                timestamp = candidate_time.strftime("%Y-%m-%d-%H-%M")
            elif image_pattern in (self.temperature_image_pattern, self.rainfall_image_pattern):
                timestamp = candidate_time.strftime("%Y-%m-%d_%H%M")

            filename = image_pattern.format(timestamp=timestamp)
            image_url = f"{image_prefix}/{filename}"

            if image_url not in excluded_urls and self.check_image_url(image_url):
                display_time = candidate_time.strftime("%Y-%m-%d %H:%M")
                return image_url, display_time

        return None

    def resolve_satellite_image_url(self) -> tuple[str, str] | None:
        return self.resolve_latest_image(
            image_prefix=self.satellite_image_prefix,
            image_pattern=self.satellite_image_pattern,
            publish_delay_minutes=self.satellite_publish_delay_minutes,
        )

    def fetch_satellite(self):
        resolved = self.resolve_satellite_image_url()
        if resolved is None:
            return

        image_url, display_time = resolved
        yield self.build_payload(
            "satellite",
            f"CWA Color Satellite Cloud {display_time}",
            image_url,
            self.satellite_source_url,
            image_time=datetime.strptime(display_time, "%Y-%m-%d %H:%M").replace(
                tzinfo=self.satellite_timezone
            ).isoformat(),
        )

    def build_satellite_image_url(self, image_time: datetime) -> str:
        timestamp = image_time.astimezone(self.satellite_timezone).strftime("%Y-%m-%d-%H-%M")
        filename = self.satellite_image_pattern.format(timestamp=timestamp)
        return f"{self.satellite_image_prefix}/{filename}"

    def satellite_time_slots_for_date(self, image_date: date, now: datetime | None = None) -> list[datetime]:
        current_time = now or datetime.now(self.satellite_timezone)
        current_time = current_time.astimezone(self.satellite_timezone).replace(second=0, microsecond=0)
        start = datetime.combine(image_date, datetime.min.time(), tzinfo=self.satellite_timezone)
        end = datetime.combine(image_date, datetime.max.time(), tzinfo=self.satellite_timezone).replace(
            second=0,
            microsecond=0,
        )

        if image_date == current_time.date():
            publishable_time = current_time - timedelta(minutes=self.satellite_publish_delay_minutes)
            end = publishable_time - timedelta(minutes=publishable_time.minute % self.satellite_slot_minutes)
        elif image_date > current_time.date():
            return []

        if end < start:
            return []

        slots = []
        candidate_time = start
        while candidate_time <= end:
            slots.append(candidate_time)
            candidate_time += timedelta(minutes=self.satellite_slot_minutes)
        return slots
        
    def _read_index(self, url):
        """A missing/changed metadata route may use another existing route.

        The shared HTTP policy already exhausted retries before HttpFailure;
        never bypass a blocked source with guesses for dozens of timestamps.
        """
        try:
            with http_get(url, timeout=10, headers=self.no_cache_headers(),
                          params={"_": datetime.now(self.satellite_timezone).timestamp()},
                          verify=False) as response:
                response.raise_for_status()
                return response.text
        except HttpFailure:
            _candidate_event('fault')
            raise RuntimeError('candidate_source_error') from None
        except requests.RequestException as error:
            response = getattr(error, 'response', None)
            _candidate_event('missing' if response is not None and response.status_code in (404, 410) else 'fault')
            return None

    def _index_candidates(self, kind, text, *, script):
        """Parse only this product/colour, then try newest verified image first."""
        if text is None:
            return []
        if script and kind == 'temperature':
            day = re.search(r"['\"]Day0['\"]\s*:\s*\{(.*?)(?=['\"]Day1['\"]|\Z)", text, re.S)
            size = re.search(r"['\"]size1['\"]\s*:\s*\{(.*?)(?=['\"]size\d['\"]|\Z)", day[1], re.S) if day else None
            text = size[1] if size else ''
        elif script and kind == 'rainfall':
            tab = re.search(r"['\"]Tab0['\"]\s*:\s*\{(.*?)(?=['\"]Tab1['\"]|\Z)", text, re.S)
            day = re.search(r"['\"]Day0['\"]\s*:\s*\{(.*?)(?=['\"]Day1['\"]|\Z)", tab[1], re.S) if tab else None
            text = day[1] if day else ''
        if kind == 'radar':
            pattern = r"(?:/Data/radar/)?CV1_3600_(?P<stamp>\d{12})\.png"
            fmt = '%Y%m%d%H%M'
        else:
            suffix = 'GTP8w' if kind == 'temperature' else 'QZJ8'
            pattern = r"(?P<stamp>\d{4}-\d{2}-\d{2}_\d{4})\." + suffix + r"(?:\.jpg)?"
            fmt = '%Y-%m-%d_%H%M'
        context = current_history_context()
        now = context.now if context else datetime.now(self.satellite_timezone)
        candidates = {}
        for match in re.finditer(pattern, text):
            try:
                time = datetime.strptime(match['stamp'], fmt).replace(tzinfo=self.satellite_timezone)
                grid = 30 if kind == 'rainfall' else 10
                if time > now or time.minute % grid or (kind == 'rainfall' and time.hour == 0 and time.minute == 0):
                    raise ValueError('Invalid product slot')
                filename = getattr(self, f'{kind}_image_pattern').format(timestamp=match['stamp'])
                candidates[time] = f"{getattr(self, f'{kind}_image_prefix')}/{filename}"
            except ValueError:
                _candidate_event('invalid')
        if not candidates:
            _candidate_event('invalid')
        return [(url, time.strftime('%Y-%m-%d %H:%M'))
                for time, url in sorted(candidates.items(), reverse=True)[:36]]

    def _resolve_indexed_image(self, kind):
        tried = set()
        for url, script in ((getattr(self, f'{kind}_data_url'), True),
                            (getattr(self, f'{kind}_source_url'), False)):
            for image_url, display_time in self._index_candidates(kind, self._read_index(url), script=script):
                if image_url in tried:
                    continue
                tried.add(image_url)
                if self.check_image_url(image_url):
                    return image_url, display_time
        return self.resolve_latest_image(
            image_prefix=getattr(self, f'{kind}_image_prefix'),
            image_pattern=getattr(self, f'{kind}_image_pattern'),
            publish_delay_minutes=getattr(self, f'{kind}_publish_delay_minutes'),
            excluded_urls=tried,
        )

    def resolve_radar_image_url(self) -> tuple[str, str] | None:
        return self._resolve_indexed_image('radar')

    def fetch_radar(self):
        resolved = self.resolve_radar_image_url()
        if resolved is None:
            return

        image_url, display_time = resolved
        yield self.build_payload(
            "radar",
            f"CWA Radar Echo {display_time}",
            image_url,
            self.radar_source_url,
            image_time=datetime.strptime(display_time, "%Y-%m-%d %H:%M").replace(
                tzinfo=self.satellite_timezone
            ).isoformat(),
        )

    def build_radar_image_url(self, image_time: datetime) -> str:
        timestamp = image_time.astimezone(self.satellite_timezone).strftime("%Y%m%d%H%M")
        filename = self.radar_image_pattern.format(timestamp=timestamp)
        return f"{self.radar_image_prefix}/{filename}"

    def radar_time_slots_for_date(self, image_date: date, now: datetime | None = None) -> list[datetime]:
        current_time = now or datetime.now(self.satellite_timezone)
        current_time = current_time.astimezone(self.satellite_timezone).replace(second=0, microsecond=0)
        start = datetime.combine(image_date, datetime.min.time(), tzinfo=self.satellite_timezone)
        end = datetime.combine(image_date, datetime.max.time(), tzinfo=self.satellite_timezone).replace(
            second=0,
            microsecond=0,
        )

        if image_date == current_time.date():
            publishable_time = current_time - timedelta(minutes=self.radar_publish_delay_minutes)
            end = publishable_time - timedelta(minutes=publishable_time.minute % self.radar_slot_minutes)
        elif image_date > current_time.date():
            return []

        if end < start:
            return []

        slots = []
        candidate_time = start
        while candidate_time <= end:
            slots.append(candidate_time)
            candidate_time += timedelta(minutes=self.radar_slot_minutes)
        return slots

    def resolve_temperature_image_url(self) -> tuple[str, str] | None:
        return self._resolve_indexed_image('temperature')

    def fetch_temperature(self):
        resolved = self.resolve_temperature_image_url()
        if resolved is None:
            return

        image_url, display_time = resolved
        yield self.build_payload(
            "temperature",
            f"CWA Temperature Distribution {display_time}",
            image_url,
            self.temperature_source_url,
            image_time=datetime.strptime(display_time, "%Y-%m-%d %H:%M").replace(
                tzinfo=self.satellite_timezone
            ).isoformat(),
        )

    def resolve_rainfall_image_url(self) -> tuple[str, str] | None:
        return self._resolve_indexed_image('rainfall')

    def build_rainfall_image_url(self, image_time: datetime) -> str:
        timestamp = image_time.astimezone(self.satellite_timezone).strftime("%Y-%m-%d_%H%M")
        filename = self.rainfall_image_pattern.format(timestamp=timestamp)
        return f"{self.rainfall_image_prefix}/{filename}"

    def rainfall_time_slots_for_date(self, image_date: date, now: datetime | None = None) -> list[datetime]:
        current_time = now or datetime.now(self.satellite_timezone)
        current_time = current_time.astimezone(self.satellite_timezone).replace(second=0, microsecond=0)
        start = datetime.combine(image_date, datetime.min.time(), tzinfo=self.satellite_timezone) + timedelta(
            minutes=self.rainfall_slot_minutes
        )
        end = datetime.combine(image_date, datetime.max.time(), tzinfo=self.satellite_timezone).replace(
            second=0,
            microsecond=0,
        )

        if image_date == current_time.date():
            publishable_time = current_time - timedelta(minutes=self.rainfall_publish_delay_minutes)
            end = publishable_time - timedelta(minutes=publishable_time.minute % self.rainfall_slot_minutes)
        elif image_date > current_time.date():
            return []

        slots = []
        candidate_time = start
        while candidate_time <= end:
            slots.append(candidate_time)
            candidate_time += timedelta(minutes=self.rainfall_slot_minutes)
        return slots

    def fetch_rainfall(self):
        resolved = self.resolve_rainfall_image_url()
        if resolved is None:
            return

        image_url, display_time = resolved
        yield self.build_payload(
            "rainfall",
            f"CWA Accumulated Rainfall {display_time}",
            image_url,
            self.rainfall_source_url,
            image_time=datetime.strptime(display_time, "%Y-%m-%d %H:%M").replace(
                tzinfo=self.satellite_timezone
            ).isoformat(),
        )

    def resolve_direct_weather_chart_image_url(self) -> tuple[str, str | None] | None:
        cache_bust = str(int(datetime.now(self.satellite_timezone).timestamp()))
        image_url = f"{self.weather_chart_image_url}?t={cache_bust}"

        if not self.check_image_url(image_url):
            return None

        return image_url, None

    def resolve_weather_chart_image_url(self) -> tuple[str, str | None] | None:
        text = self._read_index(self.weather_chart_source_url)
        match = self.weather_chart_image_regex.search(text) if text is not None else None
        if match:
            try:
                timestamp = datetime.strptime(match.group('timestamp').split('-')[0], '%Y%m%d%H').replace(
                    tzinfo=self.satellite_timezone)
            except ValueError:
                _candidate_event('invalid')
            else:
                image_url = f"{self.cwa_base_url}{match.group('path')}"
                if self.check_image_url(image_url):
                    return image_url, timestamp.strftime('%Y-%m-%d %H:00')
        elif text is not None:
            _candidate_event('invalid')
        # Direct FI04 has no trustworthy product timestamp; never invent one.
        return self.resolve_direct_weather_chart_image_url()

    def fetch_weather_chart(self):
        resolved = self.resolve_weather_chart_image_url()
        if resolved is None:
            return

        image_url, display_time = resolved
        title = "CWA Surface Weather Chart"
        if display_time:
            title = f"{title} {display_time}"

        yield self.build_payload(
            "weather_chart",
            title,
            image_url,
            self.weather_chart_source_url,
            image_time=(datetime.strptime(display_time, "%Y-%m-%d %H:%M").replace(
                tzinfo=self.satellite_timezone
            ).isoformat() if display_time else None),
        )

    def resolve_tchp_image_url(self) -> tuple[str, str] | None:
        try:
            response = http_get(
                self.tchp_data_url,
                timeout=10,
                headers=self.no_cache_headers(),
                params={"_": datetime.now(self.satellite_timezone).timestamp()},
                verify=False,
            )
            response.raise_for_status()
            match = self.tchp_image_regex.search(response.text)
            if match:
                cache_bust = str(int(datetime.now(self.satellite_timezone).timestamp()))
                image_url = f"{self.cwa_base_url}/Data/TCHP/{match.group('filename')}?T={cache_bust}"
                image_date = datetime.strptime(match.group("date"), "%Y-%m-%d").replace(tzinfo=self.satellite_timezone)
                display_time = image_date.strftime("%Y-%m-%d")
                return image_url, display_time
            _candidate_event('invalid', fatal=True)
        except requests.RequestException as error:
            _index_fault(error)
        except (ValueError, TypeError):
            _candidate_event('invalid', fatal=True)

        return None

    def fetch_tchp(self):
        resolved = self.resolve_tchp_image_url()
        if resolved is None:
            return

        image_url, display_time = resolved
        yield self.build_payload(
            "tchp",
            f"CWA TCHP {display_time}",
            image_url,
            self.weather_chart_source_url,
            image_time=display_time,
        )

    def fetch(self):
        yield from self.fetch_satellite()
        yield from self.fetch_radar()
        yield from self.fetch_temperature()
        yield from self.fetch_rainfall()
        yield from self.fetch_weather_chart()
        yield from self.fetch_tchp()
