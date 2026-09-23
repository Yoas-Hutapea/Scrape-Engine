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

# scraped_at is always stored in GMT+7 (WIB), whatever the SQL Server clock's timezone is.
SCRAPED_AT_OFFSET = "+07:00"

# SQL Server (T-SQL). Each entry runs as its own batch; all are idempotent.
# product_source_link is NVARCHAR(MAX) (too long to index), so it is indexed and grouped
# via the persisted SHA-256 column source_link_hash.
SCHEMA_STATEMENTS: list[str] = [
    """
IF OBJECT_ID(N'dbo.scraped_products', N'U') IS NULL
CREATE TABLE dbo.scraped_products (
    id                  BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    scrape_batch_id     NVARCHAR(64) NOT NULL,
    marketplace         NVARCHAR(32) NULL,
    product_name        NVARCHAR(MAX) NULL,
    long_description    NVARCHAR(MAX) NULL,
    short_description   NVARCHAR(MAX) NULL,
    product_source_link NVARCHAR(MAX) NULL,
    variation_name_1    NVARCHAR(MAX) NULL,
    variation_option_1  NVARCHAR(MAX) NULL,
    variation_name_2    NVARCHAR(MAX) NULL,
    variation_option_2  NVARCHAR(MAX) NULL,
    variation_name_3    NVARCHAR(MAX) NULL,
    variation_option_3  NVARCHAR(MAX) NULL,
    price               FLOAT NULL,
    discount            FLOAT NULL,
    currency            NVARCHAR(16) NULL,
    stock               FLOAT NULL,
    sku                 NVARCHAR(450) NULL,
    package_weight      NVARCHAR(MAX) NULL,
    package_length      NVARCHAR(MAX) NULL,
    package_width       NVARCHAR(MAX) NULL,
    package_height      NVARCHAR(MAX) NULL,
    product_image_1     NVARCHAR(MAX) NULL,
    scraped_at          DATETIMEOFFSET(6) NOT NULL
        CONSTRAINT df_scraped_products_scraped_at
        DEFAULT SWITCHOFFSET(SYSDATETIMEOFFSET(), '+07:00'),
    source_link_hash    AS CAST(HASHBYTES('SHA2_256', product_source_link) AS BINARY(32)) PERSISTED
)
""",
    # Migrate tables created with the old SYSDATETIMEOFFSET() default to GMT+7.
    """
IF EXISTS (SELECT 1 FROM sys.default_constraints
           WHERE name = N'df_scraped_products_scraped_at'
             AND parent_object_id = OBJECT_ID(N'dbo.scraped_products')
             AND definition NOT LIKE N'%+07:00%')
BEGIN
    ALTER TABLE dbo.scraped_products DROP CONSTRAINT df_scraped_products_scraped_at;
    ALTER TABLE dbo.scraped_products ADD CONSTRAINT df_scraped_products_scraped_at
        DEFAULT SWITCHOFFSET(SYSDATETIMEOFFSET(), '+07:00') FOR scraped_at;
END
""",
    # Same instant, re-expressed in GMT+7 (420 minutes).
    """
UPDATE dbo.scraped_products
SET scraped_at = SWITCHOFFSET(scraped_at, '+07:00')
WHERE DATEPART(TZOFFSET, scraped_at) <> 420
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_scraped_products_batch'
               AND object_id = OBJECT_ID(N'dbo.scraped_products'))
CREATE INDEX idx_scraped_products_batch ON dbo.scraped_products (scrape_batch_id)
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_scraped_products_source'
               AND object_id = OBJECT_ID(N'dbo.scraped_products'))
CREATE INDEX idx_scraped_products_source ON dbo.scraped_products (source_link_hash)
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_scraped_products_sku'
               AND object_id = OBJECT_ID(N'dbo.scraped_products'))
CREATE INDEX idx_scraped_products_sku ON dbo.scraped_products (sku)
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'idx_scraped_products_scraped_at'
               AND object_id = OBJECT_ID(N'dbo.scraped_products'))
CREATE INDEX idx_scraped_products_scraped_at ON dbo.scraped_products (scraped_at)
""",
]


def row_to_db_values(row: dict[str, Any]) -> dict[str, Any]:
    return {col: row.get(header) for header, col in HEADER_TO_COLUMN.items()}
