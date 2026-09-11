from __future__ import annotations

import json
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


def _walk_find_prices(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 14 or obj is None:
        return
    if isinstance(obj, dict):
        keys = set(obj.keys())
        if {"price", "skuId"} <= keys or {"price", "skuId", "stock"} <= keys or (
            "price" in obj and ("sku" in obj or "skuId" in obj or "name" in obj)
        ):
            out.append(obj)
        for v in obj.values():
            _walk_find_prices(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:200]:
            _walk_find_prices(item, out, depth + 1)


def _product_from_lazada_payload(payload: dict[str, Any], source_url: str, fallback: Product | None) -> Product:
    name = fallback.name if fallback else "Unknown Product"
    desc = fallback.long_description if fallback else ""
    image = fallback.images[0] if fallback and fallback.images else None
    currency = "IDR"

    # Common Lazada PDP shapes
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    root = data.get("root") if isinstance(data.get("root"), dict) else data
    fields = root.get("fields") if isinstance(root.get("fields"), dict) else root

    product = fields.get("product") if isinstance(fields, dict) else None
    if isinstance(product, dict):
        name = str(product.get("title") or product.get("name") or name)
        if product.get("desc"):
            desc = str(product.get("desc"))

    sku_infos = None
    for key in ("skuInfos", "skus", "skuInfoMap"):
        cand = fields.get(key) if isinstance(fields, dict) else None
        if cand:
            sku_infos = cand
            break

    variants: list[Variant] = []
    if isinstance(sku_infos, dict):
        items = list(sku_infos.values())
    elif isinstance(sku_infos, list):
        items = sku_infos
    else:
        items = []
        found: list[dict[str, Any]] = []
        _walk_find_prices(payload, found)
        items = found[:50]

    for item in items:
        if not isinstance(item, dict):
            continue
        price = None
        original = None
        raw_price = item.get("price")
        if isinstance(raw_price, dict):
            price = parse_money(raw_price.get("salePrice") or raw_price.get("price"))
            original = parse_money(raw_price.get("originalPrice") or raw_price.get("price"))
        else:
            price = parse_money(raw_price)

        opt_name = None
        for k in ("propPath", "name", "skuName", "attributes"):
            if item.get(k):
                opt_name = str(item.get(k))
                break
        options = [("Variant", opt_name)] if opt_name else []
        stock = None
        try:
            stock_raw = item.get("stock") or item.get("quantity") or item.get("stockQty")
            stock = float(stock_raw) if stock_raw is not None else None
        except (TypeError, ValueError):
            stock = None
        sku = item.get("skuId") or item.get("sku") or item.get("sellerSku")
        img = None
        if isinstance(item.get("image"), str):
            img = item["image"]
        elif isinstance(item.get("images"), list) and item["images"]:
            img = item["images"][0] if isinstance(item["images"][0], str) else None

        listed, discount = (original, price) if original and price and original > price else (price, None)
        variants.append(
            Variant(
                options=options[:3],
                price=listed,
                discount=discount,
                currency=currency,
                stock=stock,
                sku=str(sku) if sku not in (None, "") else None,
                images=[img] if img else [],
            )
        )

    if not variants and fallback:
        return fallback
    if not variants:
        variants = [Variant(currency=currency)]

    return Product(
        name=name,
        source_link=source_url,
        long_description=desc if "<" in desc else f"<p>{desc}</p>" if desc else "",
        short_description=re.sub(r"<[^>]+>", "", desc)[:500] if desc else "",
        images=[image] if image else [],
        currency=currency,
        variants=variants,
    )


class LazadaScraper(BaseScraper):
    def scrape(
        self,
        url: str,
        *,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> Product:
        html = ""
        final_url = url
        try:
            final_url, html = fetch_html(url, timeout_s=timeout_ms / 1000)
        except Exception:
            html = ""

        base = product_from_meta_and_ld(html, final_url or url, default_currency="IDR") if html else None

        payload = None
        for marker in ("window.__moduleData__=", "window.pageData=", "__moduleData__="):
            payload = extract_js_object(html, marker) if html else None
            if payload:
                break
        # app.run / script JSON blobs
        if not payload and html:
            m = re.search(r"app\.run\((\{.*?\})\);", html, flags=re.S)
            if m:
                try:
                    payload = json.loads(m.group(1))
                except json.JSONDecodeError:
                    payload = None

        if payload:
            try:
                product = _product_from_lazada_payload(payload, final_url or url, base)
                if product.name and product.name != "Unknown Product":
                    return product
            except Exception:
                pass

        if base and base.name != "Unknown Product":
            return base

        # Playwright fallback
        with launch_page(headed=headed, cdp_url=cdp_url, reuse_existing_page=active_tab, url_hint=url) as (
            _p,
            _b,
            page,
            _c,
            owns,
        ):
            if not (active_tab and not owns):
                goto_resilient(page, url, timeout_ms=timeout_ms)
            page.wait_for_timeout(3500)
            final_url = page.url
            html = page.content()

        base = product_from_meta_and_ld(html, final_url or url, default_currency="IDR")
        if base:
            return base
        raise RuntimeError(f"Failed to extract Lazada product data from: {url}")
