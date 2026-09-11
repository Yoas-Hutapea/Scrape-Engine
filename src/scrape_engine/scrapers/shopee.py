from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from scrape_engine.models import Product, Variant
from scrape_engine.scrapers.base import BaseScraper
from scrape_engine.scrapers.browser import goto_resilient, launch_page
from scrape_engine.scrapers.common import meta_content, parse_money, product_from_meta_and_ld

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
        crawler_product: Product | None = None
        shop_id, item_id = parse_shop_item_ids(url)

        # 1) Public crawler HTML (name/description/image/price when exposed)
        try:
            with httpx.Client(
                headers={"User-Agent": CRAWLER_UA, "Accept": "text/html"},
                follow_redirects=True,
                timeout=timeout_ms / 1000,
                http2=False,
            ) as client:
                resp = client.get(url)
                if resp.status_code == 200 and "og:title" in resp.text:
                    crawler_product = product_from_crawler_html(resp.text, str(resp.url))
        except Exception:
            crawler_product = None

        captured_items: list[dict[str, Any]] = []
        if shop_id and item_id:
            api_urls = [
                f"https://shopee.co.id/api/v4/item/get?itemid={item_id}&shopid={shop_id}",
                f"https://shopee.co.id/api/v4/pdp/get_pc?shop_id={shop_id}&item_id={item_id}",
            ]
            try:
                with httpx.Client(
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/122.0.0.0 Safari/537.36"
                        ),
                        "Accept": "application/json",
                        "Referer": url,
                        "X-API-SOURCE": "pc",
                    },
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
                                if item and (item.get("title") or item.get("models")):
                                    captured_items.append(item)
                                    break
                        except Exception:
                            continue
            except Exception:
                pass

        if captured_items:
            best = max(
                captured_items,
                key=lambda it: len(it.get("models") or [])
                + len(it.get("images") or [])
                + (1 if it.get("title") else 0),
            )
            return _parse_shopee_item(best, url)

        # 2) Browser session — full PDP JSON when anti-bot allows
        # Prefer attaching to your already-open Chrome (cdp_url) so Shopee login is reused.
        # With active_tab=True, scrape a product page YOU opened manually (no automated goto).
        final_url = url
        storage = None if cdp_url else (str(STORAGE_STATE_PATH) if STORAGE_STATE_PATH.exists() else None)
        browser_error: str | None = None
        use_active = bool(active_tab and cdp_url)

        try:
            with launch_page(
                headed=headed or bool(cdp_url),
                storage_state=storage,
                engine="chromium",
                cdp_url=cdp_url,
                reuse_existing_page=use_active,
                url_hint=url,
            ) as (
                _p,
                _browser,
                page,
                context,
                owns_page,
            ):
                def on_response(response) -> None:
                    try:
                        u = response.url
                        if any(
                            key in u
                            for key in (
                                "/api/v4/pdp/get_pc",
                                "/api/v4/pdp/get",
                                "/api/v4/item/get",
                                "/api/v2/item/get",
                            )
                        ):
                            try:
                                data = response.json()
                            except Exception:
                                return
                            if isinstance(data, dict):
                                item = _extract_item_from_payload(data)
                                if item:
                                    captured_items.append(item)
                    except Exception:
                        pass

                page.on("response", on_response)

                if use_active and not owns_page:
                    # User already opened the product tab — just reload to re-fire APIs
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                    except Exception:
                        pass
                elif use_active and owns_page:
                    # No matching tab yet: open blank tab and wait for user to paste/open URL
                    # Avoid automated goto which Shopee often blocks even when logged in.
                    raise RuntimeError(
                        "Tidak ada tab Shopee produk yang terbuka. "
                        "Buka URL produk manual di Chrome debug, pastikan halaman produk tampil "
                        "(bukan verify), lalu jalankan lagi dengan --use-open-chrome --active-tab."
                    )
                else:
                    goto_resilient(page, url, timeout_ms=timeout_ms)

                # Poll until product API is captured or timeout (covers verify challenges)
                deadline_slices = max(1, int(timeout_ms / 2000))
                for _ in range(deadline_slices):
                    final_url = page.url
                    if captured_items and "verify" not in final_url:
                        break
                    page.wait_for_timeout(2000)

                final_url = page.url

                shop_id, item_id = parse_shop_item_ids(final_url) or parse_shop_item_ids(url)
                if shop_id and item_id and not captured_items and "verify" not in final_url:
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
                                    captured_items.append(item)
                                    break
                        except Exception:
                            continue

                if captured_items and headed and not cdp_url:
                    try:
                        STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(STORAGE_STATE_PATH))
                    except Exception:
                        pass
        except Exception as exc:
            browser_error = str(exc)

        if captured_items:
            best = max(
                captured_items,
                key=lambda it: len(it.get("models") or [])
                + len(it.get("images") or [])
                + (1 if it.get("title") else 0),
            )
            return _parse_shopee_item(best, final_url or url)

        if crawler_product and crawler_product.name not in {"Unknown Product", "Shopee Indonesia"}:
            return crawler_product

        hint = (
            "Untuk Shopee: 1) py -m scrape_engine.cli open-chrome  2) login  "
            "3) buka URL produk MANUAL di Chrome itu  "
            "4) py -m scrape_engine.cli scrape URL --use-open-chrome --active-tab"
        )
        extra = f" Browser error: {browser_error}" if browser_error else ""
        raise RuntimeError(
            "Shopee blocked automated access (verify/challenge). "
            f"{hint}{extra} URL: {url}"
        )
