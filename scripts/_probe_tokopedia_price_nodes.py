from scrape_engine.scrapers.tokopedia import (
    PDP_CACHE_READY,
    _entities_by_type,
    _open_tokopedia_camoufox,
    resolve_refs,
)

url = "https://www.tokopedia.com/cenglistore/baterai-alkaline-abc-aa-kecil-batere-abc-batere-aa-isi-2-1734900531264718327"
cache, html, final = _open_tokopedia_camoufox(url, headed=None, timeout_ms=120_000, wait_js=PDP_CACHE_READY)
print("children", len(_entities_by_type(cache or {}, "pdpProductVariantChildren")))
for t in ("pdpContentSnapshotPrice", "pdpContentSnapshotStock", "pdpBasicInfo"):
    nodes = _entities_by_type(cache or {}, t)
    print(t, len(nodes))
    if nodes:
        print(resolve_refs(cache, nodes[0]))
