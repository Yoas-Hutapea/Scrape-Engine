from __future__ import annotations

from typing import Any

# Map export headers → DB column names (thumbnail only)
HEADER_TO_COLUMN: dict[str, str] = {
    "Product Name": "product_name",
    "Long Description": "long_description",
    "short description": "short_description",
    "Product Source Link": "product_source_link",
    "Variation Name 1": "variation_name_1",
    "Variation Option 1": "variation_option_1",
    "Variation Name 2": "variation_name_2",
    "Variation Option 2": "variation_option_2",
    "Variation Name 3": "variation_name_3",
    "Variation Option 3": "variation_option_3",
    "price": "price",
    "Discount": "discount",
    "Currency": "currency",
    "Stock": "stock",
    "SKU": "sku",
    "Package Weight": "package_weight",
    "Package Length": "package_length",
    "Package Width": "package_width",
    "Package Height": "package_height",
    "Product Image 1": "product_image_1",
}

ROW_COLUMNS: list[str] = list(HEADER_TO_COLUMN.values())

OBSOLETE_IMAGE_COLUMNS: list[str] = [
    "product_image",  # legacy alias; keep product_image_1 only
    "product_image_2",
    "product_image_3",
    "product_image_4",
    "product_image_5",
    "product_image_6",
    "product_image_7",
    "product_image_8",
    "product_image_9",
    "variation_image_1",
    "variation_image_2",
    "variation_image_3",
    "variation_image_4",
    "variation_image_5",
    "variation_image_6",
    "variation_image_7",
    "variation_image_8",
    "variation_image_9",
]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scraped_products (
    id                  BIGSERIAL PRIMARY KEY,
    scrape_batch_id     VARCHAR(64) NOT NULL,
    marketplace         VARCHAR(32),
    product_name        TEXT,
    long_description    TEXT,
    short_description   TEXT,
    product_source_link TEXT,
    variation_name_1    TEXT,
    variation_option_1  TEXT,
    variation_name_2    TEXT,
    variation_option_2  TEXT,
    variation_name_3    TEXT,
    variation_option_3  TEXT,
    price               DOUBLE PRECISION,
    discount            DOUBLE PRECISION,
    currency            VARCHAR(16),
    stock               DOUBLE PRECISION,
    sku                 TEXT,
    package_weight      TEXT,
    package_length      TEXT,
    package_width       TEXT,
    package_height      TEXT,
    product_image_1     TEXT,
    scraped_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraped_products_batch
    ON scraped_products (scrape_batch_id);
CREATE INDEX IF NOT EXISTS idx_scraped_products_source
    ON scraped_products (product_source_link);
CREATE INDEX IF NOT EXISTS idx_scraped_products_sku
    ON scraped_products (sku);
"""


def row_to_db_values(row: dict[str, Any]) -> dict[str, Any]:
    return {col: row.get(header) for header, col in HEADER_TO_COLUMN.items()}
