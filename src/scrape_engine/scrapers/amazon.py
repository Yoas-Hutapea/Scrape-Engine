from __future__ import annotations

import re

from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import fetch_rendered_html
from scrape_engine.scrapers.common import (
    fetch_html,
    meta_content,
    parse_money,
    product_from_meta_and_ld,
)


def _enrich_amazon_html(html: str, product: Product) -> Product:
    """Fill price/ASIN from common Amazon HTML markers when JSON-LD is thin."""
    asin = None
    m = re.search(r'"asin"\s*:\s*"([A-Z0-9]{8,12})"', html, flags=re.I)
    if m:
        asin = m.group(1)
    if not asin:
        m = re.search(r"/dp/([A-Z0-9]{8,12})", product.source_link or "", flags=re.I)
        if m:
            asin = m.group(1)

    price = product.price
    for pat in (
        r'id="priceblock_ourprice"[^>]*>\s*([^<]+)',
        r'id="priceblock_dealprice"[^>]*>\s*([^<]+)',
        r'class="a-price-whole">([^<]+)',
        r'"priceAmount"\s*:\s*([0-9.]+)',
        r'data-a-color="price"[^>]*>.*?([Rp$€£]?[\d.,]+)',
    ):
        m = re.search(pat, html, flags=re.I | re.S)
        if m:
            price = parse_money(m.group(1)) or price
            if price is not None:
                break

    currency = product.currency or "USD"
    if "amazon.co.id" in (product.source_link or "").lower():
        currency = "IDR"
    elif "amazon.co.uk" in (product.source_link or "").lower():
        currency = "GBP"
    elif "amazon.de" in (product.source_link or "").lower():
        currency = "EUR"
    elif "amazon." in (product.source_link or "").lower():
        currency = currency if currency != "IDR" else "USD"

    # Prefer og:image already set; ensure single thumbnail
    image = product.images[0] if product.images else meta_content(html, "og:image")

    if product.variants:
        v0 = product.variants[0]
        product.variants[0] = Variant(
            options=v0.options,
            price=price if price is not None else v0.price,
            discount=v0.discount,
            currency=currency,
            stock=v0.stock,
            sku=asin or v0.sku,
            images=v0.images,
        )
    else:
        product.variants = [Variant(price=price, currency=currency, sku=asin)]
    product.price = price
    product.currency = currency
    product.sku = asin or product.sku
    product.images = [image] if image else product.images[:1]
    return product


class AmazonScraper(BaseScraper):
    def scrape(
        self,
        url: str,
        *,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> Product:
        default_currency = "IDR" if "amazon.co.id" in url.lower() else "USD"
        html = ""
        final_url = url
        try:
            final_url, html = fetch_html(
                url,
                timeout_s=timeout_ms / 1000,
                headers={"Accept-Language": "en-US,en;q=0.9,id;q=0.8"},
            )
        except Exception:
            html = ""

        base = product_from_meta_and_ld(html, final_url or url, default_currency=default_currency) if html else None
        if base:
            return _enrich_amazon_html(html, base)

        final_url, html = fetch_rendered_html(
            url,
            headed=headed,
            timeout_ms=timeout_ms,
            wait_ms=4000,
            cdp_url=cdp_url,
            active_tab=active_tab,
        )
        base = product_from_meta_and_ld(html, final_url or url, default_currency=default_currency)
        if base:
            return _enrich_amazon_html(html, base)
        raise RuntimeError(f"Failed to extract Amazon product data from: {url}")
