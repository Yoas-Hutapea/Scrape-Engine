# Scrape Engine

Product scrape engine for **Tokopedia**, **Shopee**, **Lazada**, **Blibli**, **Amazon**, and **Alibaba**. Results are inserted into **PostgreSQL** (`IdeaSearch.scraped_products`) by default. Optional XLSX/JSON file export is still available.

## Requirements

- Python 3.11+
- Chromium via Playwright
- Camoufox (Shopee stealth — Firefox + fingerprint)
- PostgreSQL database `IdeaSearch`

## Install

```bash
cd "Scrape-Engine"
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -e .
playwright install chromium
python -m camoufox fetch
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

# Tokopedia listing /find (BigSeller-style: collect PDPs then scrape each)
py -m scrape_engine.cli scrape "https://www.tokopedia.com/find/baterai-alkaline-aa" --listing-limit 10

# Also export files
py -m scrape_engine.cli scrape "https://www.tokopedia.com/..." --format both --out output

# Skip DB
py -m scrape_engine.cli scrape "https://www.tokopedia.com/..." --no-db --format json

# Shopee (Camoufox — recommended)
py -m scrape_engine.cli setup-session
# login + selesaikan captcha di jendela Firefox, tunggu sampai sesi stabil
py -m scrape_engine.cli scrape "https://shopee.co.id/..."
py -m scrape_engine.cli search-shopee "laptop"

# Shopee fallback (Chrome debug, tab dibuka manual)
py -m scrape_engine.cli open-chrome
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

Shopee search (top cheapest products):

```
GET http://127.0.0.1:8001/shopee/search?q=laptop&limit=3
```

Session helpers: `GET /shopee/session`, `POST /shopee/session/setup`, `POST /shopee/session/warm`.

### IDISys Price Comparison

IDISys (`/Procurement/PriceComparison`) uses Google Programmable Search (`cx`) to collect marketplace product links, then calls this `/scrape` endpoint and renders a comparison table. Keep this API running while using that page. Set `SCRAPE_ENGINE_URL=http://127.0.0.1:8001` in the IDISys `.env`.

## Table `scraped_products`

One row per variation, plus `id`, `scrape_batch_id`, `marketplace`, `scraped_at`.
Thumbnail uses **`product_image_1` only** (no multi-image / variation-image columns).

## Notes

- Use reasonably (rate limits, marketplace Terms of Service).
- **Tokopedia**: Camoufox first (same stealth stack as Shopee), then HTTP fallback. A `/find/` or `/search` listing URL is expanded then each PDP is scraped.
- **Lazada / Blibli / Amazon / Alibaba**: parsed from public HTML (Open Graph / JSON-LD / embedded page data), with Playwright fallback.
- **Shopee**: Camoufox persistent profile + human simulation + API intercept, with DOM fallback. Run `setup-session` once. Chrome `--use-open-chrome --active-tab` remains as fallback.
- Supported URL hosts include `tokopedia.com`, `shopee.*`, `lazada.*`, `blibli.com`, `amazon.*`, `alibaba.com`, `1688.com`.

## Ubuntu Server

Camoufox runs on Linux. On a headless VPS it uses **Xvfb** (`headless="virtual"`) automatically.

```bash
sudo apt update
sudo apt install -y xvfb fonts-liberation
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
python -m camoufox fetch
```

Login Shopee still needs a screen (captcha). Either:

1. Run `setup-session` on a desktop PC, then copy `output/shopee-profile` to the server, or
2. Install VNC / a desktop on Ubuntu, set `DISPLAY`, and run `setup-session` there.

Keep `SHOPEE_HEADLESS=auto` (default). Override with `virtual` to force Xvfb, or `false` if a real display/VNC is attached.
