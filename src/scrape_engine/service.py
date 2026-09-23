from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from scrape_engine.detect import (
    Marketplace,
    canonicalize_product_url,
    detect_marketplace,
    is_listing_url,
    is_product_url,
)
from scrape_engine.exporters.excel import export_xlsx
from scrape_engine.exporters.json_out import export_json, rows_as_ordered
from scrape_engine.models import Product, flatten_products
from scrape_engine.scrapers.alibaba import AlibabaScraper
from scrape_engine.scrapers.amazon import AmazonScraper
from scrape_engine.scrapers.blibli import BlibliScraper
from scrape_engine.scrapers.listing import collect_listing_urls
from scrape_engine.scrapers.shopee import ShopeeScraper
from scrape_engine.scrapers.tokopedia import TokopediaScraper
from scrape_engine.search_urls import SEARCHABLE_MARKETPLACES, keyword_listing_url

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
            Marketplace.BLIBLI: BlibliScraper(),
            Marketplace.AMAZON: AmazonScraper(),
            Marketplace.ALIBABA: AlibabaScraper(),
        }

    def search_shopee(
        self,
        keyword: str,
        *,
        limit: int = 3,
        headed: bool | None = None,
        timeout_ms: int = 60_000,
        sort_by_price: bool = True,
    ) -> dict[str, Any]:
        scraper = self._scrapers[Marketplace.SHOPEE]
        return scraper.search(  # type: ignore[attr-defined]
            keyword,
            limit=limit,
            headed=headed,
            timeout_ms=timeout_ms,
            sort_by_price=sort_by_price,
        )

    def expand_listing(
        self,
        url: str,
        *,
        limit: int = 10,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
        isolated: bool = False,
        fill: bool = True,
    ) -> list[str]:
        marketplace = detect_marketplace(url)
        limit = max(1, min(int(limit), 30))
        if marketplace is Marketplace.TOKOPEDIA:
            return self._scrapers[Marketplace.TOKOPEDIA].collect_listing_urls(  # type: ignore[attr-defined]
                url,
                limit=limit,
                headed=headed,
                timeout_ms=timeout_ms,
                cdp_url=cdp_url,
                active_tab=active_tab,
                isolated=isolated,
            )
        if marketplace is Marketplace.SHOPEE:
            from urllib.parse import parse_qs, urlparse, unquote

            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            keyword = (query.get("keyword") or query.get("q") or [""])[0].strip()
            if not keyword:
                parts = [s for s in (parsed.path or "").split("/") if s]
                if len(parts) >= 2 and parts[0] == "search":
                    keyword = unquote(parts[1])
            urls: list[str] = []
            if keyword:
                result = self.search_shopee(
                    keyword,
                    limit=limit,
                    headed=headed or None,
                    timeout_ms=timeout_ms,
                    sort_by_price=False,
                )
                urls = [
                    str(item.get("link") or "")
                    for item in (result.get("items") or [])
                    if item.get("link")
                ]
            if len(urls) >= limit or (urls and not fill):
                return urls[:limit]
            extra = collect_listing_urls(
                url,
                limit=limit,
                headed=headed,
                timeout_ms=timeout_ms,
                isolated=isolated,
            )
            for item in extra:
                if item not in urls:
                    urls.append(item)
                if len(urls) >= limit:
                    break
            if urls:
                return urls[:limit]
            raise RuntimeError(f"Tidak ada produk di halaman listing Shopee: {url}")
        urls = collect_listing_urls(
            url,
            limit=limit,
            headed=headed,
            timeout_ms=timeout_ms,
            isolated=isolated,
        )
        if not urls:
            raise RuntimeError(f"Tidak ada produk di halaman listing {marketplace.value}: {url}")
        return urls[:limit]

    def _collect_marketplace_items(
        self,
        query: str,
        marketplace: Marketplace,
        *,
        limit: int,
        headed: bool,
        timeout_ms: int,
        isolated: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
        listing = keyword_listing_url(query, marketplace)
        try:
            urls = self.expand_listing(
                listing,
                limit=limit,
                headed=headed,
                timeout_ms=timeout_ms,
                isolated=isolated,
                fill=False,
            )
            urls = [canonicalize_product_url(u) for u in urls if u]
            urls = [u for u in urls if is_product_url(u)]
            if not urls:
                raise RuntimeError("Tidak ada produk di halaman pencarian.")
            items = [
                {
                    "url": product_url,
                    "title": f"{marketplace.value} #{index}",
                    "snippet": listing,
                    "marketplace": marketplace.value,
                    "is_product": True,
                    "is_listing": False,
                    "listing_url": listing,
                }
                for index, product_url in enumerate(urls[:limit], start=1)
            ]
            return items, None
        except Exception as exc:
            return [], {
                "url": listing,
                "error": str(exc),
                "marketplace": marketplace.value,
            }

    def search_marketplaces(
        self,
        keyword: str,
        *,
        limit: int = 10,
        marketplaces: list[Marketplace] | None = None,
        headed: bool = False,
        timeout_ms: int = 90_000,
        budget_sec: float | None = None,
    ) -> dict[str, Any]:
        """Open each marketplace search page and collect the top product URLs.

        When ``budget_sec`` is set, marketplaces run together and the call returns
        with whatever finished. The Shopping List page sits behind a gateway that
        answers 504 if this request stays open too long.
        """
        query = " ".join(keyword.strip().split())
        if not query:
            raise ValueError("Keyword kosong.")
        limit = max(1, min(int(limit), 30))
        targets = list(marketplaces or SEARCHABLE_MARKETPLACES)
        targets = [mp for mp in targets if mp is not Marketplace.AMAZON]
        listing_urls = [
            {"marketplace": marketplace.value, "url": keyword_listing_url(query, marketplace)}
            for marketplace in targets
        ]
        per_site_ms = max(8_000, int(timeout_ms))
        if budget_sec is not None:
            per_site_ms = min(per_site_ms, max(8_000, int(float(budget_sec) * 1000)))

        found: dict[Marketplace, tuple[list[dict[str, Any]], dict[str, str] | None]] = {}
        others = [mp for mp in targets if mp is not Marketplace.SHOPEE]
        pool: ThreadPoolExecutor | None = None
        futures = {}
        started = time.monotonic()
        try:
            if others:
                pool = ThreadPoolExecutor(max_workers=len(others), thread_name_prefix="mp-search")
                futures = {
                    pool.submit(
                        self._collect_marketplace_items,
                        query,
                        marketplace,
                        limit=limit,
                        headed=headed,
                        timeout_ms=per_site_ms,
                        isolated=True,
                    ): marketplace
                    for marketplace in others
                }
            if Marketplace.SHOPEE in targets:
                found[Marketplace.SHOPEE] = self._collect_marketplace_items(
                    query,
                    Marketplace.SHOPEE,
                    limit=limit,
                    headed=headed,
                    timeout_ms=per_site_ms,
                    isolated=False,
                )
            if futures:
                if budget_sec is None:
                    done, pending = wait(futures)
                else:
                    remaining = float(budget_sec) - (time.monotonic() - started)
                    done, pending = wait(futures, timeout=max(0.0, remaining))
                for future in done:
                    marketplace = futures[future]
                    try:
                        found[marketplace] = future.result()
                    except Exception as exc:
                        listing = keyword_listing_url(query, marketplace)
                        found[marketplace] = ([], {
                            "url": listing,
                            "error": str(exc),
                            "marketplace": marketplace.value,
                        })
                for future in pending:
                    marketplace = futures[future]
                    listing = keyword_listing_url(query, marketplace)
                    found[marketplace] = ([], {
                        "url": listing,
                        "error": "Batas waktu pencarian tercapai sebelum halaman marketplace selesai dimuat.",
                        "marketplace": marketplace.value,
                    })
        finally:
            if pool is not None:
                pool.shutdown(wait=budget_sec is None, cancel_futures=True)

        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for marketplace in targets:
            rows, error = found.get(marketplace, ([], None))
            items.extend(rows)
            if error:
                errors.append(error)

        return {
            "query": query,
            "source": "marketplace_search",
            "items": items,
            "errors": errors,
            "listing_urls": listing_urls,
        }

    def search_and_scrape(
        self,
        keyword: str,
        *,
        listing_limit: int = 10,
        marketplaces: list[Marketplace] | None = None,
        headed: bool = False,
        timeout_ms: int = 90_000,
        delay_sec: float = 1.0,
        cdp_url: str | None = None,
        active_tab: bool = False,
        to_db: bool = True,
        out_dir: str | Path = "output",
        fmt: FormatName = "none",
        basename: str | None = None,
    ) -> ScrapeResult:
        found = self.search_marketplaces(
            keyword,
            limit=listing_limit,
            marketplaces=marketplaces,
            headed=headed,
            timeout_ms=timeout_ms,
        )
        urls = [str(item.get("url") or "") for item in found.get("items") or [] if item.get("url")]
        if not urls:
            result = ScrapeResult()
            result.errors = found.get("errors") or [
                {"url": keyword, "error": "Tidak ada produk dari marketplace untuk kata kunci ini."}
            ]
            return result

        result = self.scrape_and_export(
            urls,
            out_dir=out_dir,
            fmt=fmt,
            headed=headed,
            timeout_ms=timeout_ms,
            delay_sec=delay_sec,
            basename=basename,
            cdp_url=cdp_url,
            active_tab=active_tab,
            to_db=to_db,
            listing_limit=listing_limit,
        )
        result.errors = list(found.get("errors") or []) + list(result.errors)
        return result

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
        listing_limit: int = 10,
    ) -> ScrapeResult:
        result = ScrapeResult()
        expanded: list[str] = []
        for url in urls:
            url = url.strip()
            if not url or url.startswith("#"):
                continue
            url = canonicalize_product_url(url)
            try:
                if is_product_url(url):
                    expanded.append(url)
                elif is_listing_url(url):
                    kids = self.expand_listing(
                        url,
                        limit=listing_limit,
                        headed=headed,
                        timeout_ms=timeout_ms,
                        cdp_url=cdp_url,
                        active_tab=active_tab,
                    )
                    kids = [canonicalize_product_url(k) for k in kids if k]
                    kids = [k for k in kids if is_product_url(k)]
                    if not kids:
                        raise RuntimeError("Tidak ada produk di halaman listing.")
                    expanded.extend(kids)
                else:
                    raise RuntimeError(
                        "Bukan URL halaman produk (PDP) atau listing (/find, /search)."
                    )
            except Exception as exc:
                result.errors.append({"url": url, "error": str(exc)})

        seen: set[str] = set()
        unique: list[str] = []
        for url in expanded:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)

        for i, url in enumerate(unique):
            try:
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
            if i < len(unique) - 1 and delay_sec > 0:
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
        listing_limit: int = 10,
    ) -> ScrapeResult:
        result = self.scrape_many(
            urls,
            headed=headed,
            timeout_ms=timeout_ms,
            delay_sec=delay_sec,
            cdp_url=cdp_url,
            active_tab=active_tab,
            listing_limit=listing_limit,
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
