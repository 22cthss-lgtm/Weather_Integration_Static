from typing import Any

from ..db import get_connection


METRIC_COLUMNS = {
    "10min": "rain_10min",
    "1hr": "rain_1hr",
    "3hr": "rain_3hr",
    "6hr": "rain_6hr",
    "12hr": "rain_12hr",
    "24hr": "rain_24hr",
    "today": "rain_today",
    "1day": "rain_1day",
    "2days": "rain_2days",
}

OBSERVATION_COLUMNS = [
    "station_id",
    "station_name",
    "county",
    "town",
    "latitude",
    "longitude",
    "elevation",
    "observed_at",
    "rain_10min",
    "rain_1hr",
    "rain_3hr",
    "rain_6hr",
    "rain_12hr",
    "rain_24hr",
    "rain_today",
    "rain_1day",
    "rain_2days",
    "fetched_at",
]


def upsert_rainfall_observations(observations: list[dict[str, Any]]) -> int:
    if not observations:
        return 0

    placeholders = ", ".join(["?"] * len(OBSERVATION_COLUMNS))
    update_assignments = ", ".join(
        f"{column} = excluded.{column}"
        for column in OBSERVATION_COLUMNS
        if column not in {"station_id", "observed_at"}
    )

    with get_connection() as conn:
        conn.executemany(
            f"""
            INSERT INTO rainfall_observations ({", ".join(OBSERVATION_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT(station_id, observed_at) DO UPDATE SET
                {update_assignments}
            """,
            [
                tuple(observation.get(column) for column in OBSERVATION_COLUMNS)
                for observation in observations
            ],
        )
    return len(observations)


def get_latest_rainfall_fetched_at() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(fetched_at) AS fetched_at
            FROM rainfall_observations
            """
        ).fetchone()
    return row["fetched_at"] if row and row["fetched_at"] else None


def get_top_rainfall_observations(metric: str, limit: int = 10) -> list[dict[str, Any]]:
    column = METRIC_COLUMNS.get(metric)
    if column is None:
        raise ValueError(f"Unsupported rainfall metric: {metric}")

    with get_connection() as conn:
        latest = conn.execute(
            """
            SELECT MAX(fetched_at) AS fetched_at
            FROM rainfall_observations
            """
        ).fetchone()
        if not latest or not latest["fetched_at"]:
            return []

        rows = conn.execute(
            f"""
            SELECT
                station_id,
                station_name,
                county,
                town,
                latitude,
                longitude,
                elevation,
                observed_at,
                {column} AS rainfall,
                fetched_at
            FROM rainfall_observations
            WHERE fetched_at = ? AND {column} IS NOT NULL
            ORDER BY {column} DESC, station_name ASC
            LIMIT ?
            """,
            (latest["fetched_at"], limit),
        ).fetchall()

    return [dict(row) for row in rows]
