from __future__ import annotations

import re
from typing import Any

from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import goto_resilient, launch_page
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
        try:
            final_url, html = fetch_html(url, timeout_s=timeout_ms / 1000)
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
                    return product
            except Exception:
                pass

        if base and base.name != "Unknown Product":
            return base

        with launch_page(headed=headed, cdp_url=cdp_url, reuse_existing_page=active_tab, url_hint=url) as (
            _p,
            _b,
            page,
            _c,
            owns,
        ):
            if not (active_tab and not owns):
                goto_resilient(page, url, timeout_ms=timeout_ms)
            page.wait_for_timeout(4000)
            final_url = page.url
            html = page.content()

        base = product_from_meta_and_ld(html, final_url or url, default_currency=default_currency)
        if base:
            return base
        raise RuntimeError(f"Failed to extract Alibaba product data from: {url}")
