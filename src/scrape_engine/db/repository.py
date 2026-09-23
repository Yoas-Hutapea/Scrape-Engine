from __future__ import annotations

import struct
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import pyodbc

from scrape_engine.db.schema import (
    OBSOLETE_IMAGE_COLUMNS,
    ROW_COLUMNS,
    SCHEMA_STATEMENTS,
    SCRAPED_AT_OFFSET,
    row_to_db_values,
)
from scrape_engine.db.settings import get_db_settings

# pyodbc has no built-in handler for SQL Server DATETIMEOFFSET (ODBC type -155)
_SQL_DATETIMEOFFSET = -155


def _convert_datetimeoffset(raw: bytes) -> datetime:
    year, month, day, hour, minute, second, fraction_ns, tz_h, tz_m = struct.unpack("<6hI2h", raw)
    return datetime(
        year, month, day, hour, minute, second, fraction_ns // 1000,
        timezone(timedelta(hours=tz_h, minutes=tz_m)),
    )


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


def connect() -> pyodbc.Connection:
    settings = get_db_settings()
    conn = pyodbc.connect(settings.dsn, timeout=10)
    conn.add_output_converter(_SQL_DATETIMEOFFSET, _convert_datetimeoffset)
    return conn


def _fetch_dicts(cur: pyodbc.Cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def init_db() -> None:
    """Create scraped_products table and drop unused image columns if present."""
    with closing(connect()) as conn:
        cur = conn.cursor()
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)
        for col in OBSOLETE_IMAGE_COLUMNS:
            cur.execute(
                f"IF COL_LENGTH(N'dbo.scraped_products', N'{col}') IS NOT NULL "
                f"ALTER TABLE dbo.scraped_products DROP COLUMN {col}"
            )
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
    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    sql = f"INSERT INTO dbo.scraped_products ({col_sql}) VALUES ({placeholders})"

    payloads: list[tuple[Any, ...]] = []
    for row in rows:
        mapped = row_to_db_values(row)
        mapped["scrape_batch_id"] = batch_id
        mapped["marketplace"] = detect_marketplace_from_link(
            mapped.get("product_source_link")
        )
        payloads.append(tuple(mapped.get(c) for c in cols))

    with closing(connect()) as conn:
        cur = conn.cursor()
        cur.executemany(sql, payloads)
        conn.commit()

    return batch_id, len(payloads)


def ping() -> bool:
    with closing(connect()) as conn:
        row = conn.cursor().execute("SELECT 1 AS ok").fetchone()
        return bool(row and row[0] == 1)


# Sortable columns for list_products (API name -> column on the grouped result)
PRODUCT_SORT_COLUMNS: dict[str, str] = {
    "scraped_at": "scraped_at",
    "product_name": "product_name",
    "marketplace": "marketplace",
    "price_min": "price_min",
    "price_max": "price_max",
    "variant_count": "variant_count",
    "stock": "total_stock",
}

# scraped_products stores one row per variant; group back to one row per product per batch.
# Name/marketplace/description come from the group's first row; image and currency from
# the first row that has one.
_GROUPED_PRODUCTS_SQL = """
SELECT
    g.id,
    g.scrape_batch_id,
    f.product_source_link,
    f.marketplace,
    f.product_name,
    f.short_description,
    img.product_image_1,
    cur.currency,
    g.price_min,
    g.price_max,
    g.total_stock,
    g.variant_count,
    g.scraped_at
FROM (
    SELECT
        MIN(id)                                                AS id,
        scrape_batch_id,
        MIN(CASE WHEN product_image_1 IS NOT NULL THEN id END) AS image_id,
        MIN(CASE WHEN currency IS NOT NULL THEN id END)        AS currency_id,
        MIN(price)                                             AS price_min,
        MAX(price)                                             AS price_max,
        SUM(stock)                                             AS total_stock,
        COUNT(*)                                               AS variant_count,
        MAX(scraped_at)                                        AS scraped_at
    FROM dbo.scraped_products
    {where}
    GROUP BY scrape_batch_id, source_link_hash,
             CASE WHEN product_source_link IS NULL THEN id END
) g
JOIN dbo.scraped_products f ON f.id = g.id
LEFT JOIN dbo.scraped_products img ON img.id = g.image_id
LEFT JOIN dbo.scraped_products cur ON cur.id = g.currency_id
"""

_COUNT_GROUPS_SQL = """
SELECT COUNT(*) FROM (
    SELECT 1 AS x FROM dbo.scraped_products
    {where}
    GROUP BY scrape_batch_id, source_link_hash,
             CASE WHEN product_source_link IS NULL THEN id END
) g
"""


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("[", "\\[")
    )


def list_products(
    *,
    search: str | None = None,
    marketplace: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    sort: str = "scraped_at",
    direction: str = "desc",
    offset: int = 0,
    limit: int = 25,
) -> dict[str, Any]:
    """List scraped products grouped per (product_source_link, scrape_batch_id).

    Returns {total, filtered, items, marketplaces}. Dates are inclusive, in GMT+7.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if search and search.strip():
        conditions.append(
            "(product_name LIKE ? ESCAPE '\\' OR product_source_link LIKE ? ESCAPE '\\'"
            " OR sku LIKE ? ESCAPE '\\')"
        )
        params.extend([f"%{_escape_like(search.strip())}%"] * 3)
    if marketplace and marketplace.strip():
        conditions.append("marketplace = ?")
        params.append(marketplace.strip().lower())
    if start_date:
        conditions.append(f"CAST(SWITCHOFFSET(scraped_at, '{SCRAPED_AT_OFFSET}') AS DATE) >= ?")
        params.append(start_date)
    if end_date:
        conditions.append(f"CAST(SWITCHOFFSET(scraped_at, '{SCRAPED_AT_OFFSET}') AS DATE) <= ?")
        params.append(end_date)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sort_col = PRODUCT_SORT_COLUMNS.get(sort, "scraped_at")
    sort_dir = "ASC" if str(direction).lower() == "asc" else "DESC"

    with closing(connect()) as conn:
        cur = conn.cursor()
        total = int(cur.execute(_COUNT_GROUPS_SQL.format(where="")).fetchone()[0])

        if conditions:
            filtered = int(cur.execute(_COUNT_GROUPS_SQL.format(where=where), params).fetchone()[0])
        else:
            filtered = total

        cur.execute(
            f"SELECT * FROM ({_GROUPED_PRODUCTS_SQL.format(where=where)}) p"
            f" ORDER BY CASE WHEN {sort_col} IS NULL THEN 1 ELSE 0 END,"
            f" {sort_col} {sort_dir}, id {sort_dir}"
            " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            [*params, max(0, offset), max(1, limit)],
        )
        items = _fetch_dicts(cur)

        cur.execute(
            "SELECT DISTINCT marketplace FROM dbo.scraped_products"
            " WHERE marketplace IS NOT NULL ORDER BY marketplace"
        )
        marketplaces = [r[0] for r in cur.fetchall()]

    return {
        "total": total,
        "filtered": filtered,
        "items": items,
        "marketplaces": marketplaces,
    }
