from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from scrape_engine.detect import Marketplace, canonicalize_product_url, detect_marketplace, is_product_url
from scrape_engine.exporters.excel import export_xlsx
from scrape_engine.exporters.json_out import export_json, rows_as_ordered
from scrape_engine.models import Product, flatten_products
from scrape_engine.scrapers.alibaba import AlibabaScraper
from scrape_engine.scrapers.amazon import AmazonScraper
from scrape_engine.scrapers.blibli import BlibliScraper
from scrape_engine.scrapers.lazada import LazadaScraper
from scrape_engine.scrapers.shopee import ShopeeScraper
from scrape_engine.scrapers.tokopedia import TokopediaScraper

FormatName = Literal["json", "xlsx", "both", "none"]


@dataclass
class ScrapeResult:
    products: list[Product] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    xlsx_path: Path | None = None
    json_path: Path | None = None
    db_batch_id: str | None = None
    db_inserted: int = 0


class ScrapeService:
    def __init__(self) -> None:
        self._scrapers = {
            Marketplace.TOKOPEDIA: TokopediaScraper(),
            Marketplace.SHOPEE: ShopeeScraper(),
            Marketplace.LAZADA: LazadaScraper(),
            Marketplace.BLIBLI: BlibliScraper(),
            Marketplace.AMAZON: AmazonScraper(),
            Marketplace.ALIBABA: AlibabaScraper(),
        }

    def scrape_url(
        self,
        url: str,
        *,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> Product:
        marketplace = detect_marketplace(url)
        scraper = self._scrapers[marketplace]
        return scraper.scrape(
            url,
            headed=headed,
            timeout_ms=timeout_ms,
            cdp_url=cdp_url,
            active_tab=active_tab,
        )

    def scrape_many(
        self,
        urls: list[str],
        *,
        headed: bool = False,
        timeout_ms: int = 60_000,
        delay_sec: float = 1.0,
        cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> ScrapeResult:
        result = ScrapeResult()
        for i, url in enumerate(urls):
            url = url.strip()
            if not url or url.startswith("#"):
                continue
            url = canonicalize_product_url(url)
            try:
                if not is_product_url(url):
                    raise RuntimeError(
                        "Bukan URL halaman produk (PDP). Lewati listing/rekomendasi/media."
                    )
                product = self.scrape_url(
                    url,
                    headed=headed,
                    timeout_ms=timeout_ms,
                    cdp_url=cdp_url,
                    active_tab=active_tab,
                )
                result.products.append(product)
            except Exception as exc:
                result.errors.append({"url": url, "error": str(exc)})
            if i < len(urls) - 1 and delay_sec > 0:
                time.sleep(delay_sec)

        result.rows = flatten_products(result.products)
        return result

    def scrape_and_export(
        self,
        urls: list[str],
        *,
        out_dir: str | Path = "output",
        fmt: FormatName = "none",
        headed: bool = False,
        timeout_ms: int = 60_000,
        delay_sec: float = 1.0,
        basename: str | None = None,
        cdp_url: str | None = None,
        active_tab: bool = False,
        to_db: bool = True,
    ) -> ScrapeResult:
        result = self.scrape_many(
            urls,
            headed=headed,
            timeout_ms=timeout_ms,
            delay_sec=delay_sec,
            cdp_url=cdp_url,
            active_tab=active_tab,
        )
        stamp = basename or datetime.now().strftime("scraped_product_%Y%m%d%H%M%S%f")[:-3]

        if to_db and result.rows:
            from scrape_engine.db import insert_rows

            batch_id, count = insert_rows(result.rows, scrape_batch_id=stamp)
            result.db_batch_id = batch_id
            result.db_inserted = count

        if fmt != "none" and result.rows:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            if fmt in ("xlsx", "both"):
                result.xlsx_path = export_xlsx(result.rows, out / f"{stamp}.xlsx")
            if fmt in ("json", "both"):
                result.json_path = export_json(result.rows, out / f"{stamp}.json")

        return result

    @staticmethod
    def rows_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows_as_ordered(rows)
