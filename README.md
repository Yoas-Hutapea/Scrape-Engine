# Scrape Engine

Product scrape engine for **Tokopedia**, **Shopee**, **Lazada**, **Blibli**, **Amazon**, and **Alibaba**. Results are inserted into **PostgreSQL** (`IdeaSearch.scraped_products`) by default. Optional XLSX/JSON file export is still available.

## Requirements

- Python 3.11+
- Chromium via Playwright
- PostgreSQL database `IdeaSearch`

## Install

```bash
cd "Scrape-Engine"
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -e .
playwright install chromium
```

Copy `.env.example` → `.env` and set DB credentials.

## Database

```bash
# Create table scraped_products
py -m scrape_engine.cli init-db
```

Credentials are read from `.env`:

```
DB_HOST=127.0.0.1
DB_PORT=5432
DB_DATABASE=IdeaSearch
DB_USERNAME=postgres
DB_PASSWORD=...
```

## CLI

```bash
# Scrape → insert PostgreSQL only (default)
py -m scrape_engine.cli scrape "https://www.tokopedia.com/..."

# Also export files
py -m scrape_engine.cli scrape "https://www.tokopedia.com/..." --format both --out output

# Skip DB
py -m scrape_engine.cli scrape "https://www.tokopedia.com/..." --no-db --format json

# Shopee (recommended)
py -m scrape_engine.cli open-chrome
# login + buka URL produk MANUAL, lalu:
py -m scrape_engine.cli scrape "https://shopee.co.id/..." --use-open-chrome --active-tab
```

## API / Postman

Use port **8001** when IDISys (Laravel) already occupies 8000.

```bash
py -m scrape_engine.cli serve --port 8001
```

```json
POST http://127.0.0.1:8001/scrape
{
  "urls": ["https://www.tokopedia.com/..."],
  "to_db": true,
  "format": "none"
}
```

Response includes `db_batch_id` and `db_inserted`.

### IDISys Price Comparison

IDISys (`/Procurement/PriceComparison`) uses Google Programmable Search (`cx`) to collect marketplace product links, then calls this `/scrape` endpoint and renders a comparison table. Keep this API running while using that page. Set `SCRAPE_ENGINE_URL=http://127.0.0.1:8001` in the IDISys `.env`.

## Table `scraped_products`

One row per variation, plus `id`, `scrape_batch_id`, `marketplace`, `scraped_at`.
Thumbnail uses **`product_image_1` only** (no multi-image / variation-image columns).

## Notes

- Use reasonably (rate limits, marketplace Terms of Service).
- **Tokopedia** usually returns full variants/prices/stock from public HTML.
- **Lazada / Blibli / Amazon / Alibaba**: parsed from public HTML (Open Graph / JSON-LD / embedded page data), with Playwright fallback.
- **Shopee**: use `--use-open-chrome --active-tab` after opening the product page manually.
- Supported URL hosts include `tokopedia.com`, `shopee.*`, `lazada.*`, `blibli.com`, `amazon.*`, `alibaba.com`, `1688.com`.
