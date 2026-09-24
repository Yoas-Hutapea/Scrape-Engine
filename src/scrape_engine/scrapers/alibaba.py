from __future__ import annotations

import re
import time
from typing import Any

from scrape_engine.fx import product_prices_to_idr
from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.antibot import CaptchaRequiredError, raise_if_blocked
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import fetch_rendered_html
from scrape_engine.scrapers.common import (
    extract_js_object,
    fetch_html,
    parse_money,
    product_from_meta_and_ld,
)


def _walk_moq_prices(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 12 or obj is None:
        return
    if isinstance(obj, dict):
        if any(k in obj for k in ("price", "priceRange", "minPrice", "maxPrice", "skuId")):
            if obj.get("price") or obj.get("minPrice") or obj.get("priceRange"):
                out.append(obj)
        for v in obj.values():
            _walk_moq_prices(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:200]:
            _walk_moq_prices(item, out, depth + 1)


def _product_from_alibaba_payload(
    payload: dict[str, Any],
    source_url: str,
    fallback: Product | None,
    *,
    currency: str = "USD",
) -> Product:
    name = fallback.name if fallback else "Unknown Product"
    desc = fallback.long_description if fallback else ""
    image = fallback.images[0] if fallback and fallback.images else None

    found: list[dict[str, Any]] = []
    _walk_moq_prices(payload, found)

    variants: list[Variant] = []
    for item in found[:40]:
        price = None
        raw_range = item.get("priceRange")
        if isinstance(raw_range, list) and raw_range:
            price = parse_money(raw_range[0])
        elif isinstance(raw_range, dict):
            price = parse_money(raw_range.get("min") or raw_range.get("price"))
        else:
            price = parse_money(item.get("price") or item.get("minPrice") or raw_range)

        title = item.get("name") or item.get("subject") or item.get("skuName")
        if title and isinstance(title, str) and len(title) > 3:
            name = title if name == "Unknown Product" else name
        sku = item.get("skuId") or item.get("sku") or item.get("productId")
        opt = item.get("skuName") or item.get("attrValue") or item.get("attributes")
        options = [("Variant", str(opt))] if opt else []
        if price is None and not options:
            continue
        variants.append(
            Variant(
                options=options[:3],
                price=price,
                currency=currency,
                sku=str(sku) if sku not in (None, "") else None,
            )
        )

    if not variants and fallback:
        return fallback
    if not variants:
        variants = [Variant(currency=currency, price=fallback.price if fallback else None)]

    return Product(
        name=name,
        source_link=source_url,
        long_description=desc if "<" in str(desc) else f"<p>{desc}</p>" if desc else "",
        short_description=re.sub(r"<[^>]+>", "", str(desc))[:500] if desc else "",
        images=[image] if image else [],
        currency=currency,
        variants=variants,
    )


def _finalize_alibaba_product(product: Product) -> Product:
    """Alibaba/1688 quotes USD or CNY; convert to IDR for price comparison."""
    return product_prices_to_idr(product)


class AlibabaScraper(BaseScraper):
    def scrape(
        self,
        url: str,
        *,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> Product:
        default_currency = "CNY" if "1688.com" in url.lower() else "USD"
        html = ""
        final_url = url
        deadline = time.monotonic() + max(timeout_ms, 1_000) / 1000

        def left_ms() -> int:
            return max(0, int((deadline - time.monotonic()) * 1000))

        try:
            final_url, html = fetch_html(url, timeout_s=max(left_ms(), 1) / 1000)
        except Exception:
            html = ""

        base = product_from_meta_and_ld(html, final_url or url, default_currency=default_currency) if html else None

        payload = None
        if html:
            for marker in (
                "window.__INIT_DATA=",
                "window.contextPath=",
                "window.__page_data=",
                "window.detailData=",
            ):
                payload = extract_js_object(html, marker)
                if payload:
                    break

        if payload:
            try:
                product = _product_from_alibaba_payload(
                    payload, final_url or url, base, currency=default_currency
                )
                if product.name and product.name != "Unknown Product":
                    return _finalize_alibaba_product(product)
            except Exception:
                pass

        if base and base.name != "Unknown Product":
            return _finalize_alibaba_product(base)

        # Camoufox often bypasses Alibaba bot walls better than Chromium.
        if left_ms() > 1_000:
            try:
                from scrape_engine.scrapers.listing import open_listing_html

                final_url, html = open_listing_html(url, headed=headed or None, timeout_ms=left_ms())
            except CaptchaRequiredError:
                raise
            except Exception:
                final_url, html = url, ""

        if html:
            base = product_from_meta_and_ld(html, final_url or url, default_currency=default_currency)
            payload = None
            for marker in (
                "window.__INIT_DATA=",
                "window.__page_data=",
                "window.detailData=",
                "window.contextPath=",
            ):
                payload = extract_js_object(html, marker)
                if payload:
                    break
            if payload:
                try:
                    product = _product_from_alibaba_payload(
                        payload, final_url or url, base, currency=default_currency
                    )
                    if product.name and product.name != "Unknown Product":
                        return _finalize_alibaba_product(product)
                except Exception:
                    pass
            if base and base.name != "Unknown Product":
                return _finalize_alibaba_product(base)
            # Camoufox hit the slider/punish page; plain Chromium only fares worse.
            raise_if_blocked(html, final_url, marketplace="alibaba", source_url=url)

        if left_ms() <= 1_000:
            raise RuntimeError(f"Batas waktu scrape tercapai sebelum halaman Alibaba selesai. URL: {url}")
        try:
            final_url, html = fetch_rendered_html(
                url,
                headed=headed,
                timeout_ms=left_ms(),
                wait_ms=min(4000, left_ms()),
                cdp_url=cdp_url,
                active_tab=active_tab,
            )
            base = product_from_meta_and_ld(html, final_url or url, default_currency=default_currency)
            if base and base.name != "Unknown Product":
                return _finalize_alibaba_product(base)
        except Exception:
            html = ""

        raise_if_blocked(html, final_url, marketplace="alibaba", source_url=url)
        raise RuntimeError(
            "Alibaba memblokir ekstraksi produk (anti-bot). Coba lagi nanti atau tempel URL marketplace lain."
        )
