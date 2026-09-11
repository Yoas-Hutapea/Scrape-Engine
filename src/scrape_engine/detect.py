from __future__ import annotations

import re
from enum import Enum
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class Marketplace(str, Enum):
    TOKOPEDIA = "tokopedia"
    SHOPEE = "shopee"
    LAZADA = "lazada"
    BLIBLI = "blibli"
    AMAZON = "amazon"
    ALIBABA = "alibaba"


class UnsupportedMarketplaceError(ValueError):
    pass


TOKOPEDIA_NON_PRODUCT_ROOTS = frozenset(
    {
        "search",
        "find",
        "rekomendasi",
        "discovery",
        "cart",
        "wishlist",
        "official",
        "help",
        "promo",
        "campaign",
        "p",
        "directory",
        "brand",
        "kategori",
        "category",
        "hot",
        "deals",
        "google",
        "att",
        "explore",
        "nearby",
    }
)


def detect_marketplace(url: str) -> Marketplace:
    """Detect marketplace from a product URL."""
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").lower()

    if (
        "tokopedia.com" in host
        or host.endswith("tokopedia.link")
        or host == "tokopedia.link"
        or "tokopedia.app.link" in host
        or "tokopedia" in host
    ):
        return Marketplace.TOKOPEDIA

    if "shopee." in host or host.startswith("s.shopee") or "shopee" in host:
        return Marketplace.SHOPEE

    if "lazada." in host or "lazada" in host:
        return Marketplace.LAZADA

    if "blibli.com" in host or host.endswith("blibli.id") or "blibli" in host:
        return Marketplace.BLIBLI

    if (
        host.startswith("amazon.")
        or ".amazon." in host
        or host.endswith("amzn.to")
        or host == "amzn.to"
        or "amazon" in host
    ):
        return Marketplace.AMAZON

    if (
        "alibaba.com" in host
        or "alibaba." in host
        or "1688.com" in host
        or "aliexpress." in host
    ):
        return Marketplace.ALIBABA

    # path fallbacks
    if "tokopedia" in path:
        return Marketplace.TOKOPEDIA
    if "shopee" in path:
        return Marketplace.SHOPEE
    if "lazada" in path:
        return Marketplace.LAZADA
    if "blibli" in path:
        return Marketplace.BLIBLI
    if "amazon" in path or "/dp/" in path or "/gp/product/" in path:
        return Marketplace.AMAZON
    if "alibaba" in path or "1688" in path:
        return Marketplace.ALIBABA

    raise UnsupportedMarketplaceError(
        "Unsupported marketplace URL (supported: Tokopedia, Shopee, Lazada, Blibli, Amazon, Alibaba): "
        f"{url}"
    )


def canonicalize_product_url(url: str) -> str:
    """Strip tracking params and Tokopedia /media/product/N tails."""
    url = url.strip()
    parsed = urlparse(url)
    path = re.sub(r"/media/product/\d+/?$", "", parsed.path or "", flags=re.I)
    path = path.rstrip("/") or "/"
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower() not in {"gclid", "fbclid", "srsltid", "spm"}
    ]
    return urlunparse((parsed.scheme, parsed.netloc, path, "", urlencode(query), ""))


def is_product_url(url: str) -> bool:
    """True when the URL looks like a marketplace product-detail page (PDP)."""
    try:
        marketplace = detect_marketplace(url)
    except UnsupportedMarketplaceError:
        return False

    parsed = urlparse(canonicalize_product_url(url))
    path = (parsed.path or "").lower().strip("/")
    joined = "/" + path
    segments = [s for s in path.split("/") if s]

    if marketplace is Marketplace.TOKOPEDIA:
        if len(segments) != 2:
            return False
        if segments[0] in TOKOPEDIA_NON_PRODUCT_ROOTS:
            return False
        if segments[1] in {"media", "review", "reviews", "talk", "info"}:
            return False
        return True

    if marketplace is Marketplace.SHOPEE:
        return bool(re.search(r"-i\.\d+\.\d+", joined) or "/product/" in joined)

    if marketplace is Marketplace.LAZADA:
        return "/products/" in joined or bool(re.search(r"-i\d+-s\d+", joined)) or "/pdp-" in joined

    if marketplace is Marketplace.BLIBLI:
        return "/p/" in joined or "/is--" in joined

    if marketplace is Marketplace.AMAZON:
        return "/dp/" in joined or "/gp/product/" in joined

    if marketplace is Marketplace.ALIBABA:
        return "/product-detail/" in joined or "/offer/" in joined or bool(re.search(r"/\d+\.html$", joined))

    return False
