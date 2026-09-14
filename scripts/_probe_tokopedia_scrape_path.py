import logging
import traceback

logging.basicConfig(level=logging.INFO)

from scrape_engine.detect import canonicalize_product_url
from scrape_engine.scrapers.tokopedia import (
    PDP_CACHE_READY,
    _entities_by_type,
    _open_tokopedia_camoufox,
    _product_has_price,
    _product_usable,
    product_from_tokopedia_cache,
)

url = "https://www.tokopedia.com/cenglistore/baterai-alkaline-abc-aa-kecil-batere-abc-batere-aa-isi-2-1734900531264718327"
try:
    cache, html, final_url = _open_tokopedia_camoufox(
        url, headed=False or None, timeout_ms=120_000, wait_js=PDP_CACHE_READY
    )
    print("opened", "cache", type(cache), "n", len(cache) if isinstance(cache, dict) else None, "html", len(html or ""))
    print("pdpBasicInfo", bool(_entities_by_type(cache or {}, "pdpBasicInfo")))
    print("snapshotPrice", bool(_entities_by_type(cache or {}, "pdpContentSnapshotPrice")))
    if cache and _entities_by_type(cache, "pdpBasicInfo"):
        p = product_from_tokopedia_cache(cache, canonicalize_product_url(final_url or url), html=html)
        print("usable", _product_usable(p), "has_price", _product_has_price(p))
        print("name", p.name)
        print("weight", p.weight)
        print("variants", p.variants)
except Exception:
    traceback.print_exc()
