from scrape_engine.scrapers.tokopedia import TokopediaScraper, _open_tokopedia_camoufox, PDP_CACHE_READY

url = "https://www.tokopedia.com/cenglistore/baterai-alkaline-abc-aa-kecil-batere-abc-batere-aa-isi-2-1734900531264718327"
try:
    cache, html, final = _open_tokopedia_camoufox(url, headed=None, timeout_ms=120_000, wait_js=PDP_CACHE_READY)
    print("ok", "cache", bool(cache), "html", len(html or ""), "final", final)
    if cache:
        types = {v.get("__typename") for v in cache.values() if isinstance(v, dict)}
        print("typenames sample", list(sorted(x for x in types if x))[:20])
        print("pdpBasicInfo", any(isinstance(v, dict) and v.get("__typename") == "pdpBasicInfo" for v in cache.values()))
except Exception as exc:
    print("CAMOUFOX ERROR", type(exc).__name__, exc)
