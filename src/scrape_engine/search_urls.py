from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

from scrape_engine.detect import Marketplace

# Amazon intentionally excluded from keyword BigSeller-style search (anti-bot / thin ID catalog).
SEARCHABLE_MARKETPLACES: tuple[Marketplace, ...] = (
    Marketplace.TOKOPEDIA,
    Marketplace.SHOPEE,
    Marketplace.BLIBLI,
    Marketplace.ALIBABA,
)


def keyword_slug(keyword: str) -> str:
    slug = " ".join(keyword.strip().split()).lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^a-z0-9\-]+", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "search"


def keyword_listing_url(keyword: str, marketplace: Marketplace) -> str:
    """Build the marketplace search/listing URL for a keyword (BigSeller-style)."""
    query = " ".join(keyword.strip().split())
    if not query:
        raise ValueError("Keyword kosong.")
    slug = keyword_slug(query)
    encoded = quote_plus(query)

    if marketplace is Marketplace.TOKOPEDIA:
        return f"https://www.tokopedia.com/find/{quote(slug)}"
    if marketplace is Marketplace.SHOPEE:
        return f"https://shopee.co.id/search?keyword={encoded}"
    if marketplace is Marketplace.BLIBLI:
        return f"https://www.blibli.com/cari/{quote(slug)}?s={encoded}"
    if marketplace is Marketplace.AMAZON:
        return f"https://www.amazon.co.id/s?k={encoded}"
    if marketplace is Marketplace.ALIBABA:
        return (
            "https://www.alibaba.com/trade/search"
            f"?fsb=y&IndexArea=product_en&SearchText={encoded}"
        )
    raise ValueError(f"Marketplace tidak didukung: {marketplace}")


def all_listing_urls(keyword: str) -> dict[Marketplace, str]:
    return {mp: keyword_listing_url(keyword, mp) for mp in SEARCHABLE_MARKETPLACES}
