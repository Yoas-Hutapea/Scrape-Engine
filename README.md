# Scrape Engine

Product scrape engine for **Tokopedia**, **Shopee**, **Blibli**, **Amazon**, and **Alibaba**. Results are inserted into **SQL Server** (`IdeaSearch.dbo.scraped_products`) by default. Optional XLSX/JSON file export is still available.

## Requirements

- Python 3.11+
- Chromium via Playwright
- Camoufox (Shopee stealth — Firefox + fingerprint)
- SQL Server database `IdeaSearch` + Microsoft ODBC Driver 18 (or 17) for SQL Server

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
DB_CONNECTION=sqlsrv
DB_HOST=127.0.0.1
DB_PORT=1433
DB_DATABASE=IdeaSearch
DB_USERNAME=...
DB_PASSWORD=...
# optional: DB_URL="sqlsrv:Server=127.0.0.1,1433;Database=IdeaSearch;Encrypt=no;TrustServerCertificate=yes;"
# optional: DB_ODBC_DRIVER=ODBC Driver 17 for SQL Server
```

## CLI

```bash
# Scrape → insert SQL Server only (default)
py -m scrape_engine.cli scrape "https://www.tokopedia.com/..."

# Keyword search across 4 marketplaces (top 10 each, BigSeller-style; Amazon excluded)
py -m scrape_engine.cli search-all "Baterai Alkaline AA" --limit 10
py -m scrape_engine.cli scrape --keyword "Baterai Alkaline AA" --listing-limit 10 --no-db

# Tokopedia listing /find (collect PDPs then scrape each)
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
POST http://127.0.0.1:8001/search
{
  "q": "Baterai Alkaline AA",
  "limit": 10
}
```

```json
POST http://127.0.0.1:8001/scrape
{
  "keyword": "Baterai Alkaline AA",
  "listing_limit": 10,
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

IDISys (`/Procurement/PriceComparison`) sends the keyword to this engine. The engine opens Shopee, Tokopedia, Blibli, and Alibaba search pages, collects the top N product URLs (default 10), then scrapes each PDP. Amazon is excluded from keyword search. Google CSE is only a fallback if this API is down. Keep this API running while using that page. Set `SCRAPE_ENGINE_URL=http://127.0.0.1:8001` and `SCRAPE_ENGINE_TIMEOUT=1800` in the IDISys `.env`.

## Table `scraped_products`

One row per variation, plus `id`, `scrape_batch_id`, `marketplace`, `scraped_at`.
Thumbnail uses **`product_image_1` only** (no multi-image / variation-image columns).

## Notes

- Use reasonably (rate limits, marketplace Terms of Service).
- **Tokopedia**: Camoufox first (same stealth stack as Shopee), then HTTP fallback. A `/find/` or `/search` listing URL is expanded then each PDP is scraped.
- **Shopee**: Camoufox persistent profile + human simulation + API intercept, with DOM fallback. Keyword search keeps listing order when expanding a search page. Run `setup-session` once.
- **Blibli / Alibaba**: listing pages are opened in Camoufox and the top product hrefs are collected, then each PDP is parsed from public HTML (Open Graph / JSON-LD) with Camoufox/Playwright fallback. Alibaba USD/CNY prices are converted to IDR using a live FX rate (fallback `USD_IDR_RATE`). **Amazon is not included in keyword search.**
- Supported URL hosts for keyword search: `tokopedia.com`, `shopee.*`, `blibli.com`, `alibaba.com` / `1688.com`.

## Ubuntu Server

Camoufox runs on Linux. On a headless VPS it uses **Xvfb** (`headless="virtual"`) automatically.

```bash
sudo apt update
sudo apt install -y xvfb fonts-liberation curl

# Microsoft ODBC Driver 18 for SQL Server (required by pyodbc)
curl -sSL -O https://packages.microsoft.com/config/ubuntu/$(grep VERSION_ID /etc/os-release | cut -d '"' -f 2)/packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb && rm packages-microsoft-prod.deb
sudo apt update
sudo ACCEPT_EULA=Y apt install -y msodbcsql18 unixodbc-dev

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install --with-deps chromium
python -m camoufox fetch
python -m scrape_engine.cli init-db
```

In `.env`, point `DB_HOST` at the SQL Server machine (not `127.0.0.1` unless SQL Server runs on the same box). That server must accept TCP connections on port 1433 from the Ubuntu host (SQL Server Configuration Manager → TCP/IP enabled, firewall open).

Login Shopee still needs a screen (captcha). Either:

1. Run `setup-session` on a desktop PC, then copy `output/shopee-profile` to the server, or
2. Install VNC / a desktop on Ubuntu, set `DISPLAY`, and run `setup-session` there.

Keep `SHOPEE_HEADLESS=auto` (default). Override with `virtual` to force Xvfb, or `false` if a real display/VNC is attached.

### Captcha verification (Shopee / Blibli / Alibaba)

Pages that answer with a captcha / verify wall are reported as `code: "captcha_required"` and the
rest of that marketplace is skipped. A person can then solve the captcha once in a headed browser on
the server (Xvfb + noVNC); the engine keeps the per-marketplace Camoufox profile
(`output/profiles/<marketplace>`) and reuses its cookies on later scrapes.

- `POST /verify/sessions` `{"marketplace": "blibli", "url": "<page that showed the captcha>"}`
- `GET /verify/sessions/{id}` → `starting | waiting | solved | expired | error | cancelled`
- `POST /verify/sessions/{id}/cancel`
- `GET /verify/status` → display availability, `VERIFY_VIEWER_URL`, last `verified_at` per marketplace

Server setup (systemd units, noVNC behind a proxy): [deploy/ubuntu/README.md](deploy/ubuntu/README.md).
