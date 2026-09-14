from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from scrape_engine.scrapers.browser import DEFAULT_CDP_URL
from scrape_engine.service import ScrapeService

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Scrape Engine CLI (Tokopedia, Shopee, Lazada, Blibli, Amazon, Alibaba)",
)


def _resolve_urls(url_or_file: str) -> list[str]:
    path = Path(url_or_file)
    if path.exists() and path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    return [url_or_file.strip()]


def _find_chrome_exe() -> str | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    which = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if which:
        return which
    for path in candidates:
        if path.exists():
            return str(path)
    return None


@app.command("init-db")
def init_db() -> None:
    """Create scraped_products table in PostgreSQL (from .env)."""
    from scrape_engine.db import get_db_settings, init_db as _init, ping

    settings = get_db_settings()
    typer.echo(f"Connecting to {settings.host}:{settings.port}/{settings.database} as {settings.username}")
    if not ping():
        raise typer.Exit("Database ping failed.")
    _init()
    typer.echo("OK: table scraped_products ready.")


@app.command("scrape")
def scrape(
    url_or_file: str = typer.Argument(..., help="Product URL or text file with one URL per line"),
    format: str = typer.Option(
        "none",
        "--format",
        "-f",
        help="Optional file export: none | json | xlsx | both (default: none — DB only)",
    ),
    out: Path = typer.Option(Path("output"), "--out", "-o", help="Output directory (if exporting files)"),
    to_db: bool = typer.Option(True, "--to-db/--no-db", help="Insert rows into PostgreSQL"),
    headed: bool = typer.Option(False, "--headed", help="Show a new browser window (debug)"),
    cdp: str | None = typer.Option(
        None,
        "--cdp",
        help=(
            "Attach to already-open Chrome via CDP "
            f"(e.g. {DEFAULT_CDP_URL}). Reuses your Shopee login."
        ),
    ),
    use_open_chrome: bool = typer.Option(
        False,
        "--use-open-chrome",
        help=f"Shortcut for --cdp {DEFAULT_CDP_URL}",
    ),
    active_tab: bool = typer.Option(
        False,
        "--active-tab",
        help=(
            "With --use-open-chrome: scrape the Shopee product tab you opened manually "
            "(hindari page.goto otomatis yang sering kena detect)"
        ),
    ),
    timeout: int = typer.Option(60_000, "--timeout", help="Page timeout in ms"),
    delay: float = typer.Option(1.0, "--delay", help="Delay between URLs in seconds"),
) -> None:
    """Scrape product URL(s), insert into PostgreSQL, optionally export XLSX/JSON."""
    fmt = format.lower().strip()
    if fmt not in {"json", "xlsx", "both", "none"}:
        raise typer.BadParameter("format must be none, json, xlsx, or both")

    urls = _resolve_urls(url_or_file)
    if not urls:
        raise typer.Exit(code=1)

    cdp_url = cdp
    if use_open_chrome and not cdp_url:
        cdp_url = DEFAULT_CDP_URL

    if active_tab and not cdp_url:
        raise typer.BadParameter("--active-tab requires --use-open-chrome or --cdp")

    if to_db:
        from scrape_engine.db import init_db as _init

        _init()

    service = ScrapeService()
    result = service.scrape_and_export(
        urls,
        out_dir=out,
        fmt=fmt,  # type: ignore[arg-type]
        headed=headed,
        timeout_ms=timeout,
        delay_sec=delay,
        cdp_url=cdp_url,
        active_tab=active_tab,
        to_db=to_db,
    )

    typer.echo(f"Products scraped: {len(result.products)}")
    typer.echo(f"Rows: {len(result.rows)}")
    if result.db_batch_id:
        typer.echo(f"DB batch: {result.db_batch_id} ({result.db_inserted} rows inserted)")
    if result.xlsx_path:
        typer.echo(f"XLSX: {result.xlsx_path}")
    if result.json_path:
        typer.echo(f"JSON: {result.json_path}")
    for err in result.errors:
        typer.echo(f"ERROR {err['url']}: {err['error']}", err=True)

    if result.errors and not result.rows:
        raise typer.Exit(code=2)


@app.command("setup-session")
def setup_session() -> None:
    """Login Shopee sekali di Camoufox (profil persisten, anti-bot bypass)."""
    from scrape_engine.scrapers.shopee_session import setup_session as _setup

    typer.echo("Membuka Camoufox. Login Shopee, selesaikan captcha, jangan tutup jendelanya.")
    result = _setup()
    if result.get("success"):
        typer.echo("Sesi Shopee siap. Lanjut scrape URL atau search-shopee.")
        return
    raise typer.Exit(result.get("error") or "Setup sesi Shopee gagal.")


@app.command("warm-session")
def warm_session() -> None:
    """Refresh cookie / token Shopee di profil Camoufox yang sudah ada."""
    from scrape_engine.scrapers.shopee_session import warm_session as _warm

    result = _warm(keep_open=False)
    if result.get("success"):
        typer.echo("Session warming berhasil.")
        return
    raise typer.Exit(result.get("error") or "Warm sesi Shopee gagal.")


@app.command("search-shopee")
def search_shopee(
    keyword: str = typer.Argument(..., help="Kata kunci produk Shopee"),
    limit: int = typer.Option(3, "--limit", "-n", help="Jumlah produk termurah"),
    timeout: int = typer.Option(60_000, "--timeout", help="Page timeout in ms"),
) -> None:
    """Cari produk Shopee (Camoufox) dan tampilkan yang termurah."""
    service = ScrapeService()
    result = service.search_shopee(keyword, limit=limit, timeout_ms=timeout)
    items = result.get("items") or []
    typer.echo(f"reason={result.get('reason')} count={len(items)}")
    for i, item in enumerate(items, start=1):
        typer.echo(f"{i}. {item.get('name')}")
        typer.echo(f"   Harga: {item.get('price_str') or item.get('price')}")
        typer.echo(f"   Link: {item.get('link')}")
    if result.get("error"):
        typer.echo(f"ERROR: {result['error']}", err=True)
    if not items:
        raise typer.Exit(code=2)


@app.command("open-chrome")
def open_chrome(
    port: int = typer.Option(9222, "--port", help="Remote debugging port"),
    profile_dir: Path = typer.Option(
        Path("output/chrome-debug-profile"),
        "--profile-dir",
        help="Chrome user-data-dir (login Shopee sekali di profile ini)",
    ),
) -> None:
    """Start Chrome with remote debugging so scrape can attach via --use-open-chrome.

    Tutup Chrome biasa dulu, jalankan perintah ini, login Shopee di jendela yang muncul,
    lalu scrape dengan --use-open-chrome.
    """
    chrome = _find_chrome_exe()
    if not chrome:
        raise typer.Exit("Chrome executable not found. Install Google Chrome first.")

    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://shopee.co.id/",
    ]
    typer.echo(f"Starting: {' '.join(args)}")
    subprocess.Popen(args)  # noqa: S603
    typer.echo(
        f"Chrome debug ready on http://127.0.0.1:{port}\n"
        "1) Login Shopee di jendela Chrome ini\n"
        "2) Buka URL produk manual, lalu:\n"
        "   py -m scrape_engine.cli scrape URL --use-open-chrome --active-tab"
    )


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run("scrape_engine.api:app", host=host, port=port, reload=False)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
