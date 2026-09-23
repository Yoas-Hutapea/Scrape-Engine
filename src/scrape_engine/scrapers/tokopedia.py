from __future__ import annotations

import json
import logging
import re
import time
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx

from scrape_engine.detect import canonicalize_product_url, is_listing_url, is_product_url
from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import goto_resilient, launch_page
from scrape_engine.scrapers.common import product_from_meta_and_ld
from scrape_engine.scrapers.humanize import human_delay, simulate_human_activity

log = logging.getLogger(__name__)

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
    if (not name or name == "Unknown Product") and isinstance(basic, dict) and basic.get("alias"):
        slug = re.sub(r"-\d+$", "", str(basic["alias"]))
        name = re.sub(r"[-_]+", " ", slug).strip().title()
    if not name:
        name = "Unknown Product"

    final_url = source_url
    if isinstance(basic, dict) and basic.get("url"):
        final_url = str(basic["url"])

    if not variants or all(v.price is None for v in variants):
        snap_nodes = _entities_by_type(cache, "pdpContentSnapshotPrice")
        snap = resolve_refs(cache, snap_nodes[0]) if snap_nodes else {}
        if not isinstance(snap, dict):
            snap = {}
        selling = _parse_rp(snap.get("value") or snap.get("priceFmt"))
        original = _parse_rp(snap.get("slashPriceFmt"))
        if original is None and selling is not None:
            original, selling = selling, None
        elif original is not None and selling is not None and original <= selling:
            original, selling = selling, None
        stock_nodes = _entities_by_type(cache, "pdpContentSnapshotStock")
        stock_snap = resolve_refs(cache, stock_nodes[0]) if stock_nodes else {}
        stock_val = _parse_rp(stock_snap.get("value") if isinstance(stock_snap, dict) else None)
        sku = None
        if isinstance(basic, dict):
            sku = str(basic.get("ttsSKUID") or "") or None
        if not variants:
            variants = [
                Variant(
                    price=original,
                    discount=selling,
                    currency="IDR",
                    stock=stock_val,
                    sku=sku,
                    weight=weight,
                )
            ]
        else:
            variants[0].price = original
            variants[0].discount = selling
            if variants[0].stock is None:
                variants[0].stock = stock_val
            if not variants[0].sku:
                variants[0].sku = sku

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


def listing_items_from_cache(cache: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    """Parse Tokopedia search/find ``searchProductV5Product`` nodes (BigSeller listing)."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in cache.values():
        if not isinstance(raw, dict) or raw.get("__typename") != "searchProductV5Product":
            continue
        node = resolve_refs(cache, raw)
        if not isinstance(node, dict):
            continue
        url = canonicalize_product_url(unescape(str(node.get("url") or "")))
        if not is_product_url(url) or url in seen:
            continue
        seen.add(url)
        price_node = node.get("price") if isinstance(node.get("price"), dict) else {}
        media = node.get("mediaURL") if isinstance(node.get("mediaURL"), dict) else {}
        items.append(
            {
                "name": str(node.get("name") or "").strip(),
                "url": url,
                "price": _parse_rp(price_node.get("number") or price_node.get("text")),
                "image": _clean_image(str(media.get("image") or media.get("image300") or "") or None),
            }
        )
        if len(items) >= limit:
            break
    return items


def listing_urls_from_html(html: str, *, limit: int = 10) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"https://(?:www\.)?tokopedia\.com/[^\s\"'<>]+", html or ""):
        url = canonicalize_product_url(unescape(raw))
        if not is_product_url(url) or url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= limit:
            break
    return found


def collect_listing_product_urls_from_html(html: str, *, limit: int = 10) -> list[str]:
    cache = _extract_tokopedia_cache(html) or {}
    items = listing_items_from_cache(cache, limit=limit)
    urls = [row["url"] for row in items if row.get("url")]
    if len(urls) >= min(3, limit) or urls:
        extra = listing_urls_from_html(html, limit=limit)
        for url in extra:
            if url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls[:limit]
    return listing_urls_from_html(html, limit=limit)


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


PDP_CACHE_READY = """() => {
  const c = window.__cache;
  if (!c || typeof c !== 'object') return false;
  return Object.values(c).some(
    (v) => v && typeof v === 'object' && v.__typename === 'pdpBasicInfo'
  );
}"""

LISTING_CACHE_READY = """() => {
  const c = window.__cache;
  if (!c || typeof c !== 'object') return false;
  return Object.values(c).some(
    (v) => v && typeof v === 'object' && v.__typename === 'searchProductV5Product'
  );
}"""


def _read_page_cache(page: Any) -> tuple[dict[str, Any] | None, str, str]:
    html = page.content()
    cache: dict[str, Any] | None = None
    try:
        embedded = page.evaluate(
            """() => {
              const c = window.__cache;
              if (!c || typeof c !== 'object') return null;
              const out = {};
              for (const [k, v] of Object.entries(c)) {
                if (!v || typeof v !== 'object') continue;
                const t = v.__typename || '';
                if (
                  t.startsWith('pdp') ||
                  t.startsWith('searchProduct') ||
                  t.startsWith('SearchProduct')
                ) {
                  out[k] = v;
                }
              }
              return Object.keys(out).length ? out : null;
            }"""
        )
        if isinstance(embedded, dict) and embedded:
            cache = embedded
    except Exception as exc:
        log.warning("Tokopedia window.__cache evaluate failed: %s", exc)
        cache = None
    if not cache:
        cache = _extract_tokopedia_cache(html)
    return cache, html, str(page.url or "")
    html = page.content()
    cache: dict[str, Any] | None = None
    try:
        embedded = page.evaluate(
            """() => (window.__cache && typeof window.__cache === 'object') ? window.__cache : null"""
        )
        if isinstance(embedded, dict) and embedded:
            cache = embedded
    except Exception:
        cache = None
    if not cache:
        cache = _extract_tokopedia_cache(html)
    return cache, html, str(page.url or "")


def _cache_ready(cache: dict[str, Any] | None, wait_js: str) -> bool:
    if not cache:
        return False
    if "pdpBasicInfo" in wait_js:
        return bool(_entities_by_type(cache, "pdpBasicInfo"))
    if "searchProductV5Product" in wait_js:
        return bool(_entities_by_type(cache, "searchProductV5Product"))
    return False


def _navigate_tokopedia_page(page: Any, url: str, timeout_ms: int, wait_js: str) -> tuple[dict[str, Any] | None, str, str]:
    budget_ms = max(8_000, int(timeout_ms))
    deadline = time.monotonic() + budget_ms / 1000
    last: tuple[dict[str, Any] | None, str, str] = (None, "", url)
    page.goto(url, wait_until="domcontentloaded", timeout=budget_ms)
    try:
        settle_ms = min(2000, max(0, int((deadline - time.monotonic()) * 1000)))
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        last = _read_page_cache(page)
        if _cache_ready(last[0], wait_js):
            return last
        simulate_human_activity(page, rounds=1)
        last = _read_page_cache(page)
        if _cache_ready(last[0], wait_js):
            return last
        remain_ms = int((deadline - time.monotonic()) * 1000)
        if remain_ms > 500:
            try:
                page.wait_for_function(wait_js, timeout=remain_ms)
            except Exception:
                pass
        last = _read_page_cache(page)
    except Exception as exc:
        log.warning("Tokopedia Camoufox navigation interrupted: %s", exc)
    return last


def _open_tokopedia_camoufox(
    url: str,
    *,
    headed: bool | None,
    timeout_ms: int,
    wait_js: str,
    isolated: bool = False,
) -> tuple[dict[str, Any] | None, str, str]:
    from scrape_engine.scrapers.camoufox_manager import camoufox_manager, camoufox_os, shopee_headless

    if not isolated:
        try:
            with camoufox_manager.open_page(headed=headed) as (page, _context):
                return _navigate_tokopedia_page(page, url, timeout_ms, wait_js)
        except Exception as exc:
            log.warning("Persistent Camoufox unavailable for Tokopedia (%s); using ephemeral browser.", exc)

    from camoufox.sync_api import Camoufox

    with Camoufox(
        headless=shopee_headless(headed),
        humanize=True,
        os=camoufox_os(),
        locale="id-ID",
    ) as browser:
        page = browser.new_page()
        try:
            return _navigate_tokopedia_page(page, url, timeout_ms, wait_js)
        finally:
            try:
                page.close()
            except Exception:
                pass


def _product_has_price(product: Product) -> bool:
    if product.price is not None:
        return True
    return any(v.price is not None for v in product.variants)


def _product_usable(product: Product | None) -> bool:
    if product is None:
        return False
    name = (product.name or "").strip().lower()
    good_name = bool(name) and name not in {"unknown product", "tokopedia", "tokopedia - jual beli online"}
    return good_name or _product_has_price(product)


class TokopediaScraper(BaseScraper):
    def collect_listing_urls(
        self,
        url: str,
        *,
        limit: int = 10,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
        isolated: bool = False,
    ) -> list[str]:
        url = canonicalize_product_url(url)
        if not is_listing_url(url):
            raise RuntimeError(f"Not a Tokopedia listing URL: {url}")

        html = ""
        if cdp_url:
            html = self._html_via_cdp(url, headed=headed, timeout_ms=timeout_ms, cdp_url=cdp_url, active_tab=active_tab)
        else:
            try:
                _cache, html, _final = _open_tokopedia_camoufox(
                    url,
                    headed=headed or None,
                    timeout_ms=timeout_ms,
                    wait_js=LISTING_CACHE_READY,
                    isolated=isolated,
                )
            except Exception:
                html = ""

        urls = collect_listing_product_urls_from_html(html, limit=limit)
        if urls:
            return urls[:limit]

        try:
            _final, html = _fetch_html(url, timeout_s=timeout_ms / 1000)
            urls = collect_listing_product_urls_from_html(html, limit=limit)
        except Exception:
            urls = []
        return urls[:limit]

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
        camoufox_error: str | None = None
        deadline = time.monotonic() + max(timeout_ms, 1_000) / 1000

        def left_ms() -> int:
            return max(0, int((deadline - time.monotonic()) * 1000))

        if cdp_url and left_ms() > 500:
            cache, html, final_url = self._cache_via_cdp(
                url,
                headed=headed,
                timeout_ms=left_ms(),
                cdp_url=cdp_url,
                active_tab=active_tab,
            )
        elif left_ms() > 500:
            try:
                cache, html, final_url = _open_tokopedia_camoufox(
                    url,
                    headed=headed or None,
                    timeout_ms=left_ms(),
                    wait_js=PDP_CACHE_READY,
                )
            except Exception as exc:
                camoufox_error = str(exc)
                log.warning("Tokopedia Camoufox scrape failed: %s", exc)
                cache, html, final_url = None, "", url

        final_url = canonicalize_product_url(final_url or url)
        priced: Product | None = None
        if cache and _entities_by_type(cache, "pdpBasicInfo"):
            candidate = product_from_tokopedia_cache(cache, final_url, html=html)
            if _product_usable(candidate):
                if _product_has_price(candidate):
                    return candidate
                priced = candidate

        try:
            if left_ms() <= 500:
                raise RuntimeError("batas waktu")
            http_url, http_html = _fetch_html(url, timeout_s=left_ms() / 1000)
            http_url = canonicalize_product_url(http_url or url)
            http_cache = _extract_tokopedia_cache(http_html)
            if http_cache and _entities_by_type(http_cache, "pdpBasicInfo"):
                product = product_from_tokopedia_cache(http_cache, http_url, html=http_html)
                if _product_usable(product) and _product_has_price(product):
                    return product
                if _product_usable(product) and priced is None:
                    priced = product
                    html = http_html
                    final_url = http_url
        except Exception:
            pass

        if priced is not None:
            return priced

        meta_product = product_from_meta_and_ld(html or "", final_url or url, default_currency="IDR")
        if _product_usable(meta_product) and meta_product is not None:
            return meta_product

        host = urlparse(final_url or url).netloc
        if "tokopedia" not in host.lower():
            raise RuntimeError(f"Not a Tokopedia product page: {final_url or url}")
        extra = f" Camoufox: {camoufox_error}" if camoufox_error else ""
        raise RuntimeError(
            "Tokopedia PDP tidak ter-parse (bukan halaman produk, atau diblokir anti-bot). "
            f"URL: {final_url or url}{extra}"
        )

    def _html_via_cdp(
        self,
        url: str,
        *,
        headed: bool,
        timeout_ms: int,
        cdp_url: str,
        active_tab: bool,
    ) -> str:
        try:
            with launch_page(
                headed=headed or True,
                cdp_url=cdp_url,
                reuse_existing_page=active_tab,
                url_hint=url,
            ) as (_p, _browser, page, _context, _owns_page):
                goto_resilient(page, url, timeout_ms=timeout_ms)
                page.wait_for_timeout(4000)
                return page.content()
        except Exception:
            return ""

    def _cache_via_cdp(
        self,
        url: str,
        *,
        headed: bool,
        timeout_ms: int,
        cdp_url: str,
        active_tab: bool,
    ) -> tuple[dict[str, Any] | None, str, str]:
        try:
            with launch_page(
                headed=headed or True,
                cdp_url=cdp_url,
                reuse_existing_page=active_tab,
                url_hint=url,
            ) as (_p, _browser, page, _context, _owns_page):
                goto_resilient(page, url, timeout_ms=timeout_ms)
                try:
                    page.wait_for_function(
                        PDP_CACHE_READY,
                        timeout=min(max(timeout_ms - 5000, 8000), 40000),
                    )
                except Exception:
                    page.wait_for_timeout(4000)
                return _read_page_cache(page)
        except Exception:
            return None, "", url
