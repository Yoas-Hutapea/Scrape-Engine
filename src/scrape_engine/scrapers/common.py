from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

import httpx

from scrape_engine.models import Product, Variant

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_html(url: str, *, timeout_s: float = 45.0, headers: dict[str, str] | None = None) -> tuple[str, str]:
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    with httpx.Client(headers=hdrs, follow_redirects=True, timeout=timeout_s, http2=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return str(resp.url), resp.text


def meta_content(html: str, prop: str) -> str | None:
    patterns = [
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.I)
        if m:
            return unescape(m.group(1)).strip() or None
    return None


def parse_ld_json_blocks(html: str) -> list[Any]:
    blocks: list[Any] = []
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


def find_ld_products(nodes: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(x).lower() == "product" for x in types if x):
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(nodes)
    return found


def parse_money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    # keep digits and dot/comma — prefer last-dot as decimal for US, strip thousand separators
    cleaned = re.sub(r"[^\d.,]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # ID style 12.345 or EU 12,34 — if >2 digits after comma treat as thousand
        parts = cleaned.split(",")
        if len(parts[-1]) == 3 and len(parts) > 1:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    else:
        # 12.345.678 ID style OR single thousand-separator like 53.900
        if cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "")
        elif cleaned.count(".") == 1:
            whole, frac = cleaned.split(".")
            if len(frac) == 3 and whole.isdigit():
                # ID thousand separator (53.900 → 53900), not decimal
                cleaned = whole + frac
    try:
        return float(cleaned)
    except ValueError:
        digits = re.sub(r"[^\d]", "", text)
        return float(digits) if digits else None


def currency_from_text(*values: Any, default: str = "IDR") -> str:
    blob = " ".join(str(v) for v in values if v)
    upper = blob.upper()
    for code in ("IDR", "USD", "SGD", "MYR", "PHP", "THB", "VND", "CNY", "EUR", "GBP", "JPY"):
        if code in upper:
            return code
    if "RP" in upper or "RUPIAH" in upper:
        return "IDR"
    if "$" in blob:
        return "USD"
    return default


def product_from_meta_and_ld(
    html: str,
    source_url: str,
    *,
    default_currency: str = "IDR",
) -> Product | None:
    """Build a Product from Open Graph + JSON-LD Product when available."""
    ld_products: list[dict[str, Any]] = []
    for block in parse_ld_json_blocks(html):
        ld_products.extend(find_ld_products(block))

    name = meta_content(html, "og:title") or meta_content(html, "twitter:title")
    desc = meta_content(html, "og:description") or meta_content(html, "description") or ""
    image = meta_content(html, "og:image") or meta_content(html, "twitter:image")
    canonical = meta_content(html, "og:url") or source_url

    price = None
    currency = default_currency
    sku = None
    brand = None

    if ld_products:
        p0 = ld_products[0]
        name = str(p0.get("name") or name or "Unknown Product")
        if p0.get("description"):
            desc = str(p0.get("description"))
        sku = p0.get("sku") or p0.get("mpn") or p0.get("productID")
        if isinstance(p0.get("brand"), dict):
            brand = p0["brand"].get("name")
        elif isinstance(p0.get("brand"), str):
            brand = p0.get("brand")

        offers = p0.get("offers")
        offer_list = offers if isinstance(offers, list) else ([offers] if isinstance(offers, dict) else [])
        for offer in offer_list:
            if not isinstance(offer, dict):
                continue
            price = parse_money(offer.get("price") or offer.get("lowPrice"))
            currency = str(offer.get("priceCurrency") or currency)
            if price is not None:
                break

        imgs = p0.get("image")
        if isinstance(imgs, str) and imgs:
            image = image or imgs
        elif isinstance(imgs, list) and imgs:
            first = imgs[0]
            if isinstance(first, str):
                image = image or first
            elif isinstance(first, dict) and first.get("url"):
                image = image or str(first["url"])

    if not name:
        return None

    # Strip marketplace suffix from titles like "Product | Lazada"
    name = re.split(r"\s+[|\-–—]\s+(Lazada|Blibli|Amazon|Alibaba|Shopee|Tokopedia).*$", name, flags=re.I)[
        0
    ].strip()
    name = re.sub(r"^Jual\s+", "", name, flags=re.I).strip() or name

    long_desc = f"<p>{desc}</p>" if desc and "<" not in desc else (desc or "")
    currency = currency_from_text(currency, desc, default=default_currency)

    return Product(
        name=name,
        source_link=canonical,
        long_description=long_desc,
        short_description=(desc or "")[:500],
        images=[image] if image else [],
        currency=currency,
        variants=[
            Variant(
                price=price,
                currency=currency,
                sku=str(sku) if sku not in (None, "") else None,
            )
        ],
        price=price,
        sku=str(sku) if sku not in (None, "") else (str(brand) if brand else None),
    )


def extract_js_object(source: str, marker: str) -> dict[str, Any] | None:
    idx = source.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    while start < len(source) and source[start] in " \n\r\t":
        start += 1
    if start >= len(source) or source[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(source)):
        ch = source[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(source[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_next_data(html: str) -> dict[str, Any] | None:
    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, flags=re.I | re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
