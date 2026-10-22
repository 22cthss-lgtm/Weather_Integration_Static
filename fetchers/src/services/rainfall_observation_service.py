from datetime import datetime, timezone
import os
import math
from typing import Any

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CWA_RAINFALL_DATASET_ID = "O-A0002-001"
CWA_RAINFALL_API_URL = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{CWA_RAINFALL_DATASET_ID}"
CWA_API_KEY_MISSING_MESSAGE = "CWA_API_KEY is required to fetch rainfall observations."

SPECIAL_RAINFALL_VALUES = {"", "X", "T", "-99", "-98"}


def parse_rainfall_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in SPECIAL_RAINFALL_VALUES:
            return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def first_coordinate(geo_info: dict[str, Any]) -> dict[str, Any]:
    coordinates = geo_info.get("Coordinates") or geo_info.get("Coordinate") or []
    if isinstance(coordinates, dict):
        return coordinates
    if isinstance(coordinates, list):
        for coordinate in coordinates:
            if coordinate.get("CoordinateName") == "WGS84":
                return coordinate
        return coordinates[0] if coordinates else {}
    return {}


def nested_value(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_cwa_rainfall_response(payload: dict[str, Any], fetched_at: str | None = None) -> list[dict[str, Any]]:
    stations = nested_value(payload, "records", "Station")
    if not isinstance(stations, list):
        raise ValueError("Unexpected CWA rainfall response format.")

    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    observations: list[dict[str, Any]] = []

    for station in stations:
        station_id = station.get("StationId")
        observed_at = nested_value(station, "ObsTime", "DateTime")
        if not station_id or not observed_at:
            continue

        geo_info = station.get("GeoInfo") or {}
        coordinate = first_coordinate(geo_info)
        rainfall = station.get("RainfallElement") or {}

        observations.append(
            {
                "station_id": station_id,
                "station_name": station.get("StationName") or "",
                "county": geo_info.get("CountyName") or "",
                "town": geo_info.get("TownName") or "",
                "latitude": parse_rainfall_number(coordinate.get("StationLatitude")),
                "longitude": parse_rainfall_number(coordinate.get("StationLongitude")),
                "elevation": parse_rainfall_number(geo_info.get("StationAltitude")),
                "observed_at": observed_at,
                "rain_10min": parse_rainfall_number(nested_value(rainfall, "Past10Min", "Precipitation")),
                "rain_1hr": parse_rainfall_number(nested_value(rainfall, "Past1hr", "Precipitation")),
                "rain_3hr": parse_rainfall_number(nested_value(rainfall, "Past3hr", "Precipitation")),
                "rain_6hr": parse_rainfall_number(nested_value(rainfall, "Past6Hr", "Precipitation")),
                "rain_12hr": parse_rainfall_number(nested_value(rainfall, "Past12hr", "Precipitation")),
                "rain_24hr": parse_rainfall_number(nested_value(rainfall, "Past24hr", "Precipitation")),
                "rain_today": parse_rainfall_number(nested_value(rainfall, "Now", "Precipitation")),
                "rain_1day": parse_rainfall_number(nested_value(rainfall, "Past2days", "Precipitation")),
                "rain_2days": parse_rainfall_number(nested_value(rainfall, "Past3days", "Precipitation")),
                "fetched_at": fetched_at,
            }
        )

    return observations


class RainfallObservationService:
    def fetch_observations(self) -> list[dict[str, Any]]:
        api_key = os.getenv("CWA_API_KEY")
        if not api_key:
            raise RuntimeError(CWA_API_KEY_MISSING_MESSAGE)

        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            response = requests.get(
                CWA_RAINFALL_API_URL,
                params={"Authorization": api_key, "format": "JSON"},
                timeout=15,
                verify=False,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError("CWA rainfall API request failed.") from None

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("CWA rainfall API response was not valid JSON.") from None

        try:
            return parse_cwa_rainfall_response(payload, fetched_at=fetched_at)
        except ValueError as exc:
            raise RuntimeError("Unexpected CWA rainfall response format.") from None

    def refresh_observations(self) -> int:
        # Legacy database entry point, never imported by the static pipeline.
        from ..models.rainfall_observation_repository import upsert_rainfall_observations
        observations = self.fetch_observations()
        if not observations:
            raise RuntimeError("No rainfall observation data available.")
        return upsert_rainfall_observations(observations)
