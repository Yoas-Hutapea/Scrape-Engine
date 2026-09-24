from __future__ import annotations

import json
import re
import time
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.antibot import CaptchaRequiredError
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import goto_resilient, launch_page
from scrape_engine.scrapers.common import meta_content, parse_money, product_from_meta_and_ld
from scrape_engine.scrapers.humanize import human_delay, simulate_human_activity

CRAWLER_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
STORAGE_STATE_PATH = Path("output/.shopee_storage_state.json")


def parse_shop_item_ids(url: str) -> tuple[str | None, str | None]:
    """Extract shopid and itemid from common Shopee URL patterns."""
    m = re.search(r"-i\.(\d+)\.(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"/product/(\d+)/(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_from_shopee(raw: Any) -> float | None:
    """Shopee prices are often stored as integer * 100000."""
    if raw is None:
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if abs(n) >= 100_000:
        return n / 100_000
    return n


def _first_non_null(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _meta(html: str, prop: str) -> str | None:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']{re.escape(prop)}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.I)
        if m:
            return unescape(m.group(1))
    return None


def _breadcrumb_product_name(html: str) -> str | None:
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    ):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "BreadcrumbList":
            elements = data.get("itemListElement") or []
            if elements:
                last = elements[-1]
                item = last.get("item") if isinstance(last, dict) else None
                if isinstance(item, dict) and item.get("name"):
                    return str(item["name"])
    return None


def product_from_crawler_html(html: str, source_url: str) -> Product:
    title = _meta(html, "og:title") or ""
    name = _breadcrumb_product_name(html) or title.split("|")[0].strip()
    name = re.sub(r"^Jual\s+", "", name, flags=re.I).strip() or "Unknown Product"
    desc = _meta(html, "og:description") or ""
    image = _meta(html, "og:image")
    canonical = _meta(html, "og:url") or source_url
    price = parse_money(meta_content(html, "product:price:amount") or meta_content(html, "og:price:amount"))
    currency = meta_content(html, "product:price:currency") or "IDR"
    meta_product = product_from_meta_and_ld(html, source_url, default_currency="IDR")
    if meta_product:
        if meta_product.name and name in {"Unknown Product", "Shopee Indonesia"}:
            name = meta_product.name
        if meta_product.images and not image:
            image = meta_product.images[0]
        if price is None and meta_product.variants and meta_product.variants[0].price is not None:
            price = meta_product.variants[0].price
            currency = meta_product.variants[0].currency or currency
    return Product(
        name=name,
        source_link=canonical,
        long_description=f"<p>{desc}</p>" if desc else "",
        short_description=desc[:500],
        images=[image] if image else [],
        currency=currency or "IDR",
        price=price,
        variants=[Variant(price=price, currency=currency or "IDR")],
    )


def _tier_option_name(tier_variations: list[dict[str, Any]], idx: int) -> str:
    if idx < len(tier_variations):
        name = tier_variations[idx].get("name")
        if name:
            return str(name)
    return f"Option {idx + 1}"


def _parse_shopee_item(item: dict[str, Any], source_url: str) -> Product:
    name = str(item.get("title") or item.get("name") or "Unknown Product")
    desc = str(item.get("description") or "")
    desc_html = "<p>" + desc.replace("\n", "<br>") + "</p>" if desc else ""

    images: list[str] = []
    raw_images = item.get("images") or item.get("image") or []
    if isinstance(raw_images, list):
        for img in raw_images:
            if isinstance(img, str):
                images.append(
                    img if img.startswith("http") else f"https://down-id.img.susercontent.com/file/{img}"
                )
    elif isinstance(raw_images, str):
        images.append(
            raw_images
            if raw_images.startswith("http")
            else f"https://down-id.img.susercontent.com/file/{raw_images}"
        )

    weight = item.get("weight")
    weight_str = str(weight) if weight is not None else None
    dims = item.get("dimension") or item.get("package_dimension") or {}
    length = str(dims.get("package_length") or dims.get("length") or "") or None
    width = str(dims.get("package_width") or dims.get("width") or "") or None
    height = str(dims.get("package_height") or dims.get("height") or "") or None

    tier_variations = item.get("tier_variations") or item.get("tier_variation") or []
    if not isinstance(tier_variations, list):
        tier_variations = []

    models = item.get("models") or item.get("model_list") or []
    if not isinstance(models, list):
        models = []

    variants: list[Variant] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        tier_idx = None
        if isinstance(model.get("extinfo"), dict):
            tier_idx = model["extinfo"].get("tier_index")
        if tier_idx is None:
            tier_idx = model.get("tier_index") or []
        if not isinstance(tier_idx, list):
            tier_idx = []

        opt_pairs: list[tuple[str, str]] = []
        for dim_i, opt_i in enumerate(tier_idx):
            dim_name = _tier_option_name(tier_variations, dim_i)
            options: list[Any] = []
            if dim_i < len(tier_variations):
                options = (
                    tier_variations[dim_i].get("options")
                    or tier_variations[dim_i].get("option_list")
                    or []
                )
            opt_val = ""
            if isinstance(options, list) and isinstance(opt_i, int) and opt_i < len(options):
                entry = options[opt_i]
                if isinstance(entry, str):
                    opt_val = entry
                elif isinstance(entry, dict):
                    opt_val = str(entry.get("option") or entry.get("name") or "")
            if opt_val:
                opt_pairs.append((dim_name, opt_val))

        price = _price_from_shopee(
            _first_non_null(model.get("price"), model.get("price_before_discount"), item.get("price"))
        )
        price_before = _price_from_shopee(model.get("price_before_discount"))
        if price_before is not None and price is not None and price_before > price:
            listed_price, discount_price = price_before, price
        else:
            listed_price, discount_price = price, None

        stock = _as_float(model.get("stock") or model.get("normal_stock") or model.get("current_stock"))
        sku = model.get("model_sku") or model.get("sku")
        sku_str = str(sku) if sku not in (None, "") else None

        var_images: list[str] = []
        if tier_idx and tier_variations:
            dim0 = tier_variations[0]
            images_map = dim0.get("images") or []
            if isinstance(images_map, list) and tier_idx:
                idx0 = tier_idx[0]
                if isinstance(idx0, int) and idx0 < len(images_map) and images_map[idx0]:
                    img = images_map[idx0]
                    if isinstance(img, str):
                        var_images.append(
                            img
                            if img.startswith("http")
                            else f"https://down-id.img.susercontent.com/file/{img}"
                        )

        variants.append(
            Variant(
                options=opt_pairs[:3],
                price=listed_price,
                discount=discount_price,
                currency="IDR",
                stock=stock,
                sku=sku_str,
                weight=weight_str,
                length=length,
                width=width,
                height=height,
                images=var_images[:1],
            )
        )

    if not variants:
        price = _price_from_shopee(item.get("price"))
        price_before = _price_from_shopee(item.get("price_before_discount"))
        if price_before is not None and price is not None and price_before > price:
            listed_price, discount_price = price_before, price
        else:
            listed_price, discount_price = price, None
        variants = [
            Variant(
                price=listed_price,
                discount=discount_price,
                currency="IDR",
                stock=_as_float(item.get("stock") or item.get("normal_stock")),
                sku=str(item.get("item_sku") or item.get("sku") or "") or None,
                weight=weight_str,
                length=length,
                width=width,
                height=height,
            )
        ]

    return Product(
        name=name,
        source_link=source_url,
        long_description=desc_html,
        short_description=desc[:500] if desc else "",
        images=images[:1],
        weight=weight_str,
        length=length,
        width=width,
        height=height,
        currency="IDR",
        variants=variants,
    )


def _extract_item_from_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    d = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("item"), dict):
        return d["item"]
    if "title" in d or "models" in d or "tier_variations" in d:
        return d
    return None


REASON_SUCCESS = "SUCCESS"
REASON_ANTIBOT = "ANTIBOT"
REASON_EMPTY = "EMPTY_RESULTS"
REASON_ERROR = "SCRAPE_ERROR"

PDP_API_KEYS = (
    "/api/v4/pdp/get_pc",
    "/api/v4/pdp/get",
    "/api/v4/item/get",
    "/api/v2/item/get",
)

SEARCH_API_KEY = "/api/v4/search/search_items"

DOM_PDP_SCRIPT = """() => {
  const text = document.body?.innerText || '';
  const lower = text.toLowerCase();
  const blocked = lower.includes('captcha') || lower.includes('security check')
    || lower.includes('robot') || location.href.includes('verify');
  const h1 = document.querySelector('h1')?.innerText?.trim() || '';
  const ogTitle = document.querySelector('meta[property="og:title"]')?.content || '';
  let name = h1 || ogTitle.split('|')[0].trim();
  name = name.replace(/^Jual\\s+/i, '').trim();
  const priceMatch = text.match(/Rp\\s*[\\d.]+/);
  const image = document.querySelector('meta[property="og:image"]')?.content
    || document.querySelector('img[src*="susercontent"]')?.src || '';
  const description = document.querySelector('meta[property="og:description"]')?.content || '';
  return {
    name,
    price_text: priceMatch ? priceMatch[0] : '',
    image,
    description,
    url: location.href,
    blocked,
  };
}"""

DOM_SEARCH_SCRIPT = """() => {
  const cards = Array.from(document.querySelectorAll('a[data-sqe="link"], a[href*="-i."]'));
  const items = [];
  for (const el of cards) {
    const candidateDivs = Array.from(el.querySelectorAll('div, span'));
    let name = '';
    for (const node of candidateDivs) {
      const text = node.innerText?.trim() || '';
      if (text.length > 15 && !text.includes('Rp') && !text.toLowerCase().includes('terjual') && !text.includes('KAB.')) {
        name = text.split('\\n')[0];
        break;
      }
    }
    if (!name) {
      const img = el.querySelector('img');
      if (img && img.alt && img.alt.length > 10) name = img.alt;
    }
    const priceMatch = el.innerText.match(/Rp\\s*([\\d.]+)/);
    const priceStr = priceMatch ? priceMatch[0] : '';
    const priceNum = priceStr ? parseInt(priceStr.replace(/[^\\d]/g, ''), 10) : 0;
    if (name && priceNum > 0) {
      items.push({ name, price: priceNum, price_str: priceStr, link: el.href || '' });
    }
  }
  return items;
}"""


def map_search_items(
    items: list[Any],
    *,
    limit: int = 3,
    sort_by_price: bool = True,
) -> list[dict[str, Any]]:
    """Map Shopee search_items payload to name/price/link rows.

    Default is cheapest-first (CLI ``search-shopee``). Listing expansion keeps
    appearance order when ``sort_by_price=False``.
    """
    products: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        info = item.get("item_basic") if isinstance(item.get("item_basic"), dict) else item
        if not isinstance(info, dict):
            continue
        prices = [
            p
            for p in (_price_from_shopee(info.get("price")), _price_from_shopee(info.get("price_min")))
            if p is not None and p > 0
        ]
        price = min(prices) if prices else None
        name = str(info.get("name") or "").strip()
        shopid = info.get("shopid") or info.get("shop_id")
        itemid = info.get("itemid") or info.get("item_id")
        if not name or price is None or price <= 0 or not shopid or not itemid:
            continue
        products.append(
            {
                "name": name,
                "price": price,
                "price_str": f"Rp{int(round(price)):,}".replace(",", "."),
                "link": f"https://shopee.co.id/product/{shopid}/{itemid}",
            }
        )
    if sort_by_price:
        products.sort(key=lambda row: row["price"])
    return products[:limit]


def product_from_dom_snapshot(data: dict[str, Any], source_url: str) -> Product | None:
    name = str(data.get("name") or "").strip()
    name = re.sub(r"^Jual\s+", "", name, flags=re.I).strip()
    if not name or name in {"Unknown Product", "Shopee Indonesia", "Shopee"}:
        return None
    price = parse_money(data.get("price") or data.get("price_text"))
    image = str(data.get("image") or "").strip()
    desc = str(data.get("description") or "")
    canonical = str(data.get("url") or source_url)
    return Product(
        name=name,
        source_link=canonical,
        long_description=f"<p>{desc}</p>" if desc else "",
        short_description=desc[:500],
        images=[image] if image else [],
        currency="IDR",
        price=price,
        variants=[Variant(price=price, currency="IDR")],
    )


def _best_item(captured_items: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        captured_items,
        key=lambda it: len(it.get("models") or [])
        + len(it.get("images") or [])
        + (1 if it.get("title") or it.get("name") else 0),
    )


def _attach_pdp_interceptor(page: Any, captured_items: list[dict[str, Any]]) -> None:
    def on_response(response: Any) -> None:
        try:
            url = response.url
            if not any(key in url for key in PDP_API_KEYS):
                return
            data = response.json()
            if isinstance(data, dict):
                item = _extract_item_from_payload(data)
                if item:
                    captured_items.append(item)
        except Exception:
            return

    page.on("response", on_response)


def _attach_search_interceptor(page: Any, state: dict[str, Any]) -> None:
    def on_response(response: Any) -> None:
        try:
            url = response.url
            if SEARCH_API_KEY not in url:
                return
            status = response.status
            if status in {403, 429}:
                state["reason"] = REASON_ANTIBOT
                return
            if status != 200:
                return
            data = response.json()
            if not isinstance(data, dict):
                return
            if data.get("error") not in (0, None, "0"):
                state["reason"] = REASON_ANTIBOT
                return
            items = data.get("items") or []
            if items:
                state["items"] = items
                state["reason"] = REASON_SUCCESS
            else:
                state["reason"] = REASON_EMPTY
        except Exception:
            return

    page.on("response", on_response)


def _in_page_fetch_item(page: Any, shop_id: str, item_id: str) -> dict[str, Any] | None:
    api_urls = [
        f"https://shopee.co.id/api/v4/pdp/get_pc?shop_id={shop_id}&item_id={item_id}",
        f"https://shopee.co.id/api/v4/item/get?shopid={shop_id}&itemid={item_id}",
    ]
    for api_url in api_urls:
        try:
            result = page.evaluate(
                """async (apiUrl) => {
                  const r = await fetch(apiUrl, { credentials: 'include' });
                  if (!r.ok) return null;
                  return await r.json();
                }""",
                api_url,
            )
            if isinstance(result, dict):
                item = _extract_item_from_payload(result)
                if item:
                    return item
        except Exception:
            continue
    return None


def _httpx_item(url: str, shop_id: str, item_id: str, timeout_ms: int) -> dict[str, Any] | None:
    from scrape_engine.scrapers.shopee_session import session_headers

    api_urls = [
        f"https://shopee.co.id/api/v4/item/get?itemid={item_id}&shopid={shop_id}",
        f"https://shopee.co.id/api/v4/pdp/get_pc?shop_id={shop_id}&item_id={item_id}",
    ]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": url,
        "X-API-SOURCE": "pc",
    }
    headers.update(session_headers())
    try:
        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=timeout_ms / 1000,
            http2=False,
        ) as client:
            for api_url in api_urls:
                try:
                    resp = client.get(api_url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    if isinstance(data, dict):
                        item = _extract_item_from_payload(data)
                        if item and (item.get("title") or item.get("models") or item.get("name")):
                            return item
                except Exception:
                    continue
    except Exception:
        return None
    return None


def _crawler_product(url: str, timeout_ms: int) -> Product | None:
    try:
        with httpx.Client(
            headers={"User-Agent": CRAWLER_UA, "Accept": "text/html"},
            follow_redirects=True,
            timeout=timeout_ms / 1000,
            http2=False,
        ) as client:
            resp = client.get(url)
            if resp.status_code == 200 and "og:title" in resp.text:
                return product_from_crawler_html(resp.text, str(resp.url))
    except Exception:
        return None
    return None


class ShopeeScraper(BaseScraper):
    def scrape(
        self,
        url: str,
        *,
        headed: bool = False,
        timeout_ms: int = 60_000,
        cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> Product:
        deadline = time.monotonic() + max(timeout_ms, 1_000) / 1000

        def left_ms() -> int:
            return max(0, int((deadline - time.monotonic()) * 1000))

        shop_id, item_id = parse_shop_item_ids(url)
        crawler = _crawler_product(url, left_ms()) if left_ms() > 500 else None
        if shop_id and item_id and left_ms() > 500:
            item = _httpx_item(url, shop_id, item_id, left_ms())
            if item:
                return _parse_shopee_item(item, url)

        if left_ms() > 500 and cdp_url:
            product = self._scrape_via_cdp(
                url,
                headed=headed,
                timeout_ms=left_ms(),
                cdp_url=cdp_url,
                active_tab=active_tab,
            )
            if product:
                return product
        elif left_ms() > 500:
            product = self._scrape_via_camoufox(url, headed=headed or None, timeout_ms=left_ms())
            if product:
                return product

        if crawler and crawler.name not in {"Unknown Product", "Shopee Indonesia"}:
            return crawler

        hint = (
            "Untuk Shopee: 1) py -m scrape_engine.cli setup-session  "
            "2) login + selesaikan captcha  "
            "3) py -m scrape_engine.cli scrape URL"
        )
        raise CaptchaRequiredError("shopee", url, f"verify/challenge. {hint}")

    def search(
        self,
        keyword: str,
        *,
        limit: int = 3,
        headed: bool | None = None,
        timeout_ms: int = 60_000,
        sort_by_price: bool = True,
    ) -> dict[str, Any]:
        """Search Shopee by keyword and return matching products."""
        from scrape_engine.scrapers.camoufox_manager import camoufox_manager, profile_exists
        from scrape_engine.scrapers.shopee_session import ensure_warm_session

        keyword = keyword.strip()
        if not keyword:
            return {"items": [], "reason": REASON_ERROR, "error": "Keyword kosong."}

        if not profile_exists():
            try:
                from scrape_engine.scrapers.shopee_session import warm_session

                warm_session(keep_open=True)
            except Exception:
                pass
        else:
            ensure_warm_session()

        state: dict[str, Any] = {"items": None, "reason": None}
        try:
            with camoufox_manager.open_page(headed=headed) as (page, _context):
                _attach_search_interceptor(page, state)
                search_url = f"https://shopee.co.id/search?keyword={keyword}"
                started = time.monotonic()
                page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
                simulate_human_activity(page, rounds=1)
                human_delay(2000, 4000, page)

                remain = timeout_ms / 1000 - (time.monotonic() - started)
                deadline = time.monotonic() + max(0.0, min(12.0, remain))
                while time.monotonic() < deadline:
                    if state.get("items") or state.get("reason") == REASON_EMPTY:
                        break
                    try:
                        if page.query_selector("li.col-xs-2-4, div[data-sqe='item'], a[data-sqe='link']"):
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)

                api_items = state.get("items") or []
                mapped = map_search_items(api_items, limit=limit, sort_by_price=sort_by_price)
                if mapped:
                    return {"items": mapped, "reason": REASON_SUCCESS}

                try:
                    dom_items = page.evaluate(DOM_SEARCH_SCRIPT) or []
                except Exception:
                    dom_items = []
                if isinstance(dom_items, list) and dom_items:
                    cleaned: list[dict[str, Any]] = []
                    for row in dom_items:
                        if not isinstance(row, dict):
                            continue
                        price = parse_money(row.get("price") or row.get("price_str"))
                        name = str(row.get("name") or "").strip()
                        link = str(row.get("link") or "")
                        if name and price and price > 0:
                            cleaned.append(
                                {
                                    "name": name,
                                    "price": price,
                                    "price_str": str(row.get("price_str") or f"Rp{int(price):,}".replace(",", ".")),
                                    "link": link,
                                }
                            )
                    if sort_by_price:
                        cleaned.sort(key=lambda row: row["price"])
                    cleaned = cleaned[:limit]
                    if cleaned:
                        return {"items": cleaned, "reason": REASON_SUCCESS}

                blocked = False
                try:
                    blocked = bool(
                        page.evaluate(
                            """() => {
                              const t = (document.body?.innerText || '').toLowerCase();
                              return t.includes('captcha') || t.includes('security check')
                                || t.includes('robot') || location.href.includes('verify');
                            }"""
                        )
                    )
                except Exception:
                    blocked = False
                reason = REASON_ANTIBOT if blocked else (state.get("reason") or REASON_EMPTY)
                return {"items": [], "reason": reason}
        except Exception as exc:
            return {"items": [], "reason": REASON_ERROR, "error": str(exc)}

    def _scrape_via_camoufox(
        self,
        url: str,
        *,
        headed: bool | None,
        timeout_ms: int,
    ) -> Product | None:
        from scrape_engine.scrapers.camoufox_manager import camoufox_manager, profile_exists
        from scrape_engine.scrapers.shopee_session import ensure_warm_session

        if profile_exists():
            ensure_warm_session()

        captured_items: list[dict[str, Any]] = []
        try:
            with camoufox_manager.open_page(headed=headed) as (page, _context):
                _attach_pdp_interceptor(page, captured_items)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                simulate_human_activity(page, rounds=1)
                human_delay(2000, 4000, page)

                deadline = time.time() + min(30, timeout_ms / 1000)
                while time.time() < deadline:
                    if captured_items and "verify" not in (page.url or ""):
                        break
                    try:
                        if page.query_selector("h1"):
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)

                final_url = page.url or url
                shop_id, item_id = parse_shop_item_ids(final_url)
                if not shop_id or not item_id:
                    shop_id, item_id = parse_shop_item_ids(url)
                if shop_id and item_id and not captured_items and "verify" not in final_url:
                    item = _in_page_fetch_item(page, shop_id, item_id)
                    if item:
                        captured_items.append(item)

                if captured_items:
                    return _parse_shopee_item(_best_item(captured_items), final_url)

                try:
                    snapshot = page.evaluate(DOM_PDP_SCRIPT) or {}
                except Exception:
                    snapshot = {}
                if isinstance(snapshot, dict):
                    if snapshot.get("blocked"):
                        return None
                    product = product_from_dom_snapshot(snapshot, final_url)
                    if product:
                        return product
        except Exception:
            return None
        return None

    def _scrape_via_cdp(
        self,
        url: str,
        *,
        headed: bool,
        timeout_ms: int,
        cdp_url: str,
        active_tab: bool,
    ) -> Product | None:
        captured_items: list[dict[str, Any]] = []
        final_url = url
        storage = str(STORAGE_STATE_PATH) if STORAGE_STATE_PATH.exists() else None
        use_active = bool(active_tab)
        try:
            with launch_page(
                headed=headed or True,
                storage_state=storage,
                engine="chromium",
                cdp_url=cdp_url,
                reuse_existing_page=use_active,
                url_hint=url,
            ) as (_p, _browser, page, context, owns_page):
                _attach_pdp_interceptor(page, captured_items)
                if use_active and not owns_page:
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                    except Exception:
                        pass
                elif use_active and owns_page:
                    raise RuntimeError(
                        "Tidak ada tab Shopee produk yang terbuka. "
                        "Buka URL produk manual di Chrome debug, lalu jalankan lagi "
                        "dengan --use-open-chrome --active-tab."
                    )
                else:
                    goto_resilient(page, url, timeout_ms=timeout_ms)

                deadline_slices = max(1, int(timeout_ms / 2000))
                for _ in range(deadline_slices):
                    final_url = page.url
                    if captured_items and "verify" not in final_url:
                        break
                    page.wait_for_timeout(2000)

                final_url = page.url
                shop_id, item_id = parse_shop_item_ids(final_url)
                if not shop_id or not item_id:
                    shop_id, item_id = parse_shop_item_ids(url)
                if shop_id and item_id and not captured_items and "verify" not in final_url:
                    item = _in_page_fetch_item(page, shop_id, item_id)
                    if item:
                        captured_items.append(item)

                if captured_items and headed:
                    try:
                        STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(STORAGE_STATE_PATH))
                    except Exception:
                        pass
        except Exception:
            return None

        if captured_items:
            return _parse_shopee_item(_best_item(captured_items), final_url or url)
        return None
