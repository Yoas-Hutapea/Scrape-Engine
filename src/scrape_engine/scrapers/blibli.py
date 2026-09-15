from __future__ import annotations

import re
from typing import Any

from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import fetch_rendered_html
from scrape_engine.scrapers.common import (
    extract_next_data,
    fetch_html,
    parse_money,
    product_from_meta_and_ld,
)


def _walk(obj: Any, pred, depth: int = 0):
    if depth > 14 or obj is None:
        return
    if pred(obj):
        yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v, pred, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:300]:
            yield from _walk(item, pred, depth + 1)


def _product_from_blibli_next(next_data: dict[str, Any], source_url: str, fallback: Product | None) -> Product:
    name = fallback.name if fallback else "Unknown Product"
    desc = fallback.long_description if fallback else ""
    image = fallback.images[0] if fallback and fallback.images else None
    currency = "IDR"

    page_props = (
        next_data.get("props", {}).get("pageProps")
        if isinstance(next_data.get("props"), dict)
        else next_data
    )
    if not isinstance(page_props, dict):
        page_props = {}

    # Heuristic: find product-like dicts with name + price
    candidates = list(
        _walk(
            page_props,
            lambda o: isinstance(o, dict)
            and ("productName" in o or "name" in o)
            and ("price" in o or "finalPrice" in o or "offerPrice" in o),
        )
    )

    variants: list[Variant] = []
    for item in candidates[:80]:
        pname = str(item.get("productName") or item.get("name") or "")
        if pname and len(pname) > len(name):
            name = pname
        if item.get("description"):
            desc = str(item.get("description"))
        price = parse_money(
            item.get("finalPrice")
            or item.get("offerPrice")
            or item.get("price")
            or item.get("listedPrice")
        )
        original = parse_money(item.get("price") or item.get("listedPrice") or item.get("basePrice"))
        if original and price and original > price:
            listed, discount = original, price
        else:
            listed, discount = price, None
        opt = item.get("optionName") or item.get("variantName") or item.get("attributes")
        options = [("Variant", str(opt))] if opt else []
        stock = parse_money(item.get("stock") or item.get("quantity") or item.get("availableStock"))
        sku = item.get("sku") or item.get("itemSku") or item.get("id")
        img = item.get("image") or item.get("imageUrl") or item.get("imgUrl")
        if isinstance(img, list) and img:
            img = img[0]
        if isinstance(img, str) and not image:
            image = img
        if listed is None and not options:
            continue
        variants.append(
            Variant(
                options=options[:3],
                price=listed,
                discount=discount,
                currency=currency,
                stock=stock,
                sku=str(sku) if sku not in (None, "") else None,
                images=[img] if isinstance(img, str) else [],
            )
        )

    if not variants and fallback:
        return fallback
    if not variants:
        variants = [Variant(currency=currency)]

    return Product(
        name=name,
        source_link=source_url,
        long_description=desc if "<" in str(desc) else f"<p>{desc}</p>" if desc else "",
        short_description=re.sub(r"<[^>]+>", "", str(desc))[:500] if desc else "",
        images=[image] if image else [],
        currency=currency,
        variants=variants,
    )


class BlibliScraper(BaseScraper):
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
        next_data = extract_next_data(html) if html else None
        if next_data:
            try:
                product = _product_from_blibli_next(next_data, final_url or url, base)
                if product.name and product.name != "Unknown Product":
                    return product
            except Exception:
                pass

        if base and base.name != "Unknown Product":
            return base

        final_url, html = fetch_rendered_html(
            url,
            headed=headed,
            timeout_ms=timeout_ms,
            wait_ms=3500,
            cdp_url=cdp_url,
            active_tab=active_tab,
        )
        next_data = extract_next_data(html)
        base = product_from_meta_and_ld(html, final_url or url, default_currency="IDR")
        if next_data:
            try:
                return _product_from_blibli_next(next_data, final_url or url, base)
            except Exception:
                pass
        if base:
            return base

        raise RuntimeError(f"Failed to extract Blibli product data from: {url}")
