import sqlite3
from contextlib import contextmanager

from .config import DATABASE_PATH


@contextmanager
def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_type TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                image_url TEXT NOT NULL,
                source_url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                image_time TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_images_type_fetched_at
            ON images (image_type, fetched_at DESC);

            CREATE TABLE IF NOT EXISTS faq_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS faqs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                is_pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_faqs_category_updated_at
            ON faqs (category, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_faqs_pinned_updated_at
            ON faqs (is_pinned DESC, updated_at DESC);

            CREATE TABLE IF NOT EXISTS rainfall_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                station_name TEXT NOT NULL,
                county TEXT,
                town TEXT,
                latitude REAL,
                longitude REAL,
                elevation REAL,
                observed_at TEXT NOT NULL,
                rain_10min REAL,
                rain_1hr REAL,
                rain_3hr REAL,
                rain_6hr REAL,
                rain_12hr REAL,
                rain_24hr REAL,
                rain_today REAL,
                rain_1day REAL,
                rain_2days REAL,
                fetched_at TEXT NOT NULL,
                UNIQUE(station_id, observed_at)
            );

            CREATE INDEX IF NOT EXISTS idx_rainfall_observations_fetched_at
            ON rainfall_observations (fetched_at DESC);
            """
        )

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(images)").fetchall()
        }
        if "image_time" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN image_time TEXT")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_images_type_image_time
            ON images (image_type, image_time DESC)
            """
        )
