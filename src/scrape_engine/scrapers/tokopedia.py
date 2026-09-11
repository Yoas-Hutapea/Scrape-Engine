from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from scrape_engine.detect import canonicalize_product_url, is_product_url
from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import goto_resilient, launch_page
from scrape_engine.scrapers.common import product_from_meta_and_ld

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}


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


def resolve_refs(cache: dict[str, Any], node: Any, depth: int = 0) -> Any:
    if depth > 30 or node is None:
        return node
    if isinstance(node, dict):
        if node.get("type") == "id" and isinstance(node.get("id"), str):
            return resolve_refs(cache, cache.get(node["id"]), depth + 1)
        return {k: resolve_refs(cache, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(cache, x, depth + 1) for x in node]
    return node


def _parse_rp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    return float(digits)


def _clean_image(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.split(")")[0].strip()
    if url.endswith(".webp") and ".jpeg.webp" in url:
        url = url.replace(".jpeg.webp", ".jpeg")
    elif url.endswith(".webp") and ".jpg.webp" in url:
        url = url.replace(".jpg.webp", ".jpg")
    if url.startswith("http"):
        return url
    return None


def _json_field(node: Any) -> Any:
    if isinstance(node, dict) and node.get("type") == "json":
        return node.get("json")
    return node


def _entities_by_type(cache: dict[str, Any], typename: str) -> list[dict[str, Any]]:
    return [
        v
        for v in cache.values()
        if isinstance(v, dict) and v.get("__typename") == typename
    ]


def _base_product_name(product_name: str, option_values: list[str]) -> str:
    name = product_name.strip()
    for opt in option_values:
        suffix = f" - {opt}"
        if name.endswith(suffix):
            name = name[: -len(suffix)].rstrip()
    return name


def product_from_tokopedia_cache(cache: dict[str, Any], source_url: str, html: str = "") -> Product:
    cache = cache or {}
    basics = _entities_by_type(cache, "pdpBasicInfo")
    basic = resolve_refs(cache, basics[0]) if basics else {}

    variant_data_list = _entities_by_type(cache, "pdpDataProductVariant")
    variant_data = resolve_refs(cache, variant_data_list[0]) if variant_data_list else {}
    dim_names: list[str] = []
    option_image_map: dict[str, str] = {}
    for dim in variant_data.get("variants") or []:
        if not isinstance(dim, dict):
            continue
        dim_name = str(dim.get("name") or "Variant")
        # BigSeller sample uses title-case-ish "Ukuran"
        dim_names.append(dim_name[:1].upper() + dim_name[1:] if dim_name else "Variant")
        for opt in dim.get("option") or []:
            if not isinstance(opt, dict):
                continue
            val = str(opt.get("value") or "")
            pic = opt.get("picture") or {}
            img = _clean_image(pic.get("url") if isinstance(pic, dict) else None)
            if val and img:
                option_image_map[val] = img

    children = [
        resolve_refs(cache, c) for c in _entities_by_type(cache, "pdpProductVariantChildren")
    ]

    product_images: list[str] = []
    for media in _entities_by_type(cache, "pdpContentSnapshotMedia"):
        if product_images:
            break
        media_r = resolve_refs(cache, media)
        if isinstance(media_r, dict):
            img = _clean_image(media_r.get("URLOriginal") or media_r.get("url") or media_r.get("URL"))
            if img:
                product_images.append(img)
    default_media = _clean_image(basic.get("defaultMediaURL") if isinstance(basic, dict) else None)
    if default_media:
        product_images = [default_media]

    # dedupe keep first only (thumbnail)
    images: list[str] = []
    for u in product_images:
        if u and u not in images:
            images.append(u)
            break

    description = ""
    if isinstance(basic, dict):
        description = str(basic.get("description") or "")
    if not description and html:
        m = re.search(
            r'<meta\s+property="og:description"\s+content="([^"]*)"',
            html,
            flags=re.I,
        )
        if m:
            description = m.group(1)

    weight = None
    if isinstance(basic, dict) and basic.get("weight") is not None:
        weight = str(basic.get("weight"))

    variants: list[Variant] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        option_names = _json_field(child.get("optionName")) or []
        if isinstance(option_names, str):
            option_names = [option_names]
        if not isinstance(option_names, list):
            option_names = []
        option_names = [str(x) for x in option_names]

        opt_pairs: list[tuple[str, str]] = []
        for i, opt_val in enumerate(option_names):
            dim = dim_names[i] if i < len(dim_names) else f"Option {i + 1}"
            opt_pairs.append((dim, opt_val))

        campaign = child.get("campaignInfo") if isinstance(child.get("campaignInfo"), dict) else {}
        original = _parse_rp(
            campaign.get("originalPrice") if campaign else None
        ) or _parse_rp(child.get("slashPriceFmt"))
        selling = _parse_rp(campaign.get("discountPrice") if campaign else None) or _parse_rp(
            child.get("price")
        )
        # BigSeller: price=list/original, Discount=selling
        if original is None and selling is not None:
            original = selling
            selling = None
        elif original is not None and selling is not None and original <= selling:
            # no real discount
            original, selling = selling, None

        stock_node = child.get("stock")
        stock_val = None
        if isinstance(stock_node, dict):
            stock_val = _parse_rp(stock_node.get("stock"))
        elif stock_node is not None:
            stock_val = _parse_rp(stock_node)

        pic = child.get("picture") if isinstance(child.get("picture"), dict) else {}
        var_img = _clean_image(pic.get("url"))
        if not var_img and option_names:
            var_img = option_image_map.get(option_names[0])

        variants.append(
            Variant(
                options=opt_pairs[:3],
                price=original,
                discount=selling,
                currency="IDR",
                stock=stock_val,
                sku=str(child.get("ttsSKUID") or "") or None,
                weight=weight,
                images=[var_img] if var_img else [],
            )
        )

    name = ""
    if children:
        first_name = str(children[0].get("productName") or "")
        opts0 = _json_field(children[0].get("optionName")) or []
        if isinstance(opts0, str):
            opts0 = [opts0]
        name = _base_product_name(first_name, [str(x) for x in opts0])
    if not name and html:
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html, flags=re.I)
        if m:
            name = m.group(1).split("|")[0].strip()
    if not name:
        name = "Unknown Product"

    final_url = source_url
    if isinstance(basic, dict) and basic.get("url"):
        final_url = str(basic["url"])

    if not variants:
        variants = [Variant(currency="IDR", weight=weight)]

    long_desc = description
    if long_desc and "<" not in long_desc:
        long_desc = "<p>" + long_desc.replace("\n", "<br>") + "</p>"

    return Product(
        name=name,
        source_link=final_url,
        long_description=long_desc,
        short_description=re.sub(r"<[^>]+>", "", description)[:500] if description else "",
        images=images[:1],
        weight=weight,
        currency="IDR",
        variants=variants,
    )


def _fetch_html(url: str, timeout_s: float = 45.0) -> tuple[str, str]:
    with httpx.Client(
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=timeout_s,
        http2=False,
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return str(resp.url), resp.text


def _extract_tokopedia_cache(html: str) -> dict[str, Any] | None:
    for marker in ("window.__cache=", "window.__cache =", "self.__cache=", 'window["__cache"]='):
        cache = extract_js_object(html, marker)
        if cache:
            return cache
    return None


def _product_has_price(product: Product) -> bool:
    if product.price is not None:
        return True
    return any(v.price is not None for v in product.variants)


def _product_usable(product: Product | None) -> bool:
    if product is None:
        return False
    name = (product.name or "").strip().lower()
    if not name or name in {"unknown product", "tokopedia", "tokopedia - jual beli online"}:
        return False
    return True


class TokopediaScraper(BaseScraper):
    def scrape(
        self,
        url: str,
        *,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> Product:
        url = canonicalize_product_url(url)
        if not is_product_url(url):
            raise RuntimeError(f"Not a Tokopedia product-detail URL: {url}")
        html = ""
        final_url = url
        cache: dict[str, Any] | None = None

        # Primary: HTTP fetch of SSR page (more reliable than Chromium HTTP/2 on Tokopedia)
        try:
            final_url, html = _fetch_html(url, timeout_s=timeout_ms / 1000)
            final_url = canonicalize_product_url(final_url or url)
            cache = _extract_tokopedia_cache(html)
        except Exception:
            cache = None

        if cache and _entities_by_type(cache, "pdpBasicInfo"):
            product = product_from_tokopedia_cache(cache, final_url or url, html=html)
            if _product_usable(product) and _product_has_price(product):
                return product

        # Fallback: Playwright (BigSeller-style wait for PDP cache)
        try:
            with launch_page(
                headed=headed,
                cdp_url=cdp_url,
                reuse_existing_page=active_tab,
                url_hint=url,
            ) as (_p, _browser, page, _context, _owns_page):
                goto_resilient(page, url, timeout_ms=timeout_ms)
                try:
                    page.wait_for_function(
                        """() => {
                          const c = window.__cache;
                          if (!c || typeof c !== 'object') return false;
                          return Object.values(c).some(
                            (v) => v && typeof v === 'object' && v.__typename === 'pdpBasicInfo'
                          );
                        }""",
                        timeout=min(max(timeout_ms - 5000, 8000), 40000),
                    )
                except Exception:
                    page.wait_for_timeout(4000)
                final_url = canonicalize_product_url(page.url or url)
                html = page.content()
                cache = _extract_tokopedia_cache(html)
                if not cache:
                    embedded = page.evaluate(
                        """() => {
                          if (window.__cache && typeof window.__cache === 'object') return window.__cache;
                          return null;
                        }"""
                    )
                    if isinstance(embedded, dict):
                        cache = embedded
        except Exception:
            cache = cache or None

        if cache and _entities_by_type(cache, "pdpBasicInfo"):
            product = product_from_tokopedia_cache(cache, final_url or url, html=html)
            if _product_usable(product):
                return product

        meta_product = product_from_meta_and_ld(html or "", final_url or url, default_currency="IDR")
        if _product_usable(meta_product) and meta_product is not None:
            return meta_product

        host = urlparse(final_url or url).netloc
        if "tokopedia" not in host.lower():
            raise RuntimeError(f"Not a Tokopedia product page: {final_url or url}")
        raise RuntimeError(
            "Tokopedia PDP tidak ter-parse (bukan halaman produk, atau diblokir anti-bot). "
            f"URL: {final_url or url}"
        )
