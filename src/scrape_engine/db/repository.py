from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from scrape_engine.db.schema import (
    CREATE_TABLE_SQL,
    OBSOLETE_IMAGE_COLUMNS,
    ROW_COLUMNS,
    row_to_db_values,
)
from scrape_engine.db.settings import get_db_settings


def detect_marketplace_from_link(link: str | None) -> str | None:
    if not link:
        return None
    try:
        from scrape_engine.detect import detect_marketplace

        return detect_marketplace(link).value
    except Exception:
        host = (urlparse(link).netloc or "").lower()
        for name in ("tokopedia", "shopee", "lazada", "blibli", "amazon", "alibaba", "1688"):
            if name in host:
                return "alibaba" if name == "1688" else name
        return None


def connect() -> psycopg.Connection:
    settings = get_db_settings()
    return psycopg.connect(settings.dsn, row_factory=dict_row)


def init_db() -> None:
    """Create scraped_products table and drop unused image columns if present."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            for col in OBSOLETE_IMAGE_COLUMNS:
                cur.execute(f"ALTER TABLE scraped_products DROP COLUMN IF EXISTS {col}")
        conn.commit()


def insert_rows(
    rows: list[dict[str, Any]],
    *,
    scrape_batch_id: str | None = None,
) -> tuple[str, int]:
    """Insert flattened scrape rows. Returns (batch_id, inserted_count)."""
    if not rows:
        return scrape_batch_id or "", 0

    batch_id = scrape_batch_id or datetime.now(timezone.utc).strftime("batch_%Y%m%d%H%M%S%f")[:-3]
    cols = ["scrape_batch_id", "marketplace", *ROW_COLUMNS]
    placeholders = ", ".join(f"%({c})s" for c in cols)
    col_sql = ", ".join(cols)
    sql = f"INSERT INTO scraped_products ({col_sql}) VALUES ({placeholders})"

    payloads: list[dict[str, Any]] = []
    for row in rows:
        mapped = row_to_db_values(row)
        mapped["scrape_batch_id"] = batch_id
        mapped["marketplace"] = detect_marketplace_from_link(
            mapped.get("product_source_link")
        )
        payloads.append(mapped)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, payloads)
        conn.commit()

    return batch_id, len(payloads)


def ping() -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
            return bool(row and row.get("ok") == 1)
