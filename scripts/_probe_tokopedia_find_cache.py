from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scrape_engine.detect import canonicalize_product_url, is_product_url
from scrape_engine.scrapers.tokopedia import _extract_tokopedia_cache, extract_js_object

html = Path("output/_tokopedia_find.html").read_text(encoding="utf-8")
cache = _extract_tokopedia_cache(html)
print("cache", type(cache), "keys" if isinstance(cache, dict) else None, len(cache) if isinstance(cache, dict) else None)
if isinstance(cache, dict):
    types = Counter()
    for v in cache.values():
        if isinstance(v, dict):
            types[v.get("__typename") or v.get("type") or "dict"] += 1
        else:
            types[type(v).__name__] += 1
    print("typenames", types.most_common(30))
    # dump a few product-like nodes
    samples = []
    for v in cache.values():
        if isinstance(v, dict) and v.get("__typename"):
            name = str(v.get("__typename"))
            if "product" in name.lower() or "search" in name.lower() or "item" in name.lower():
                samples.append(v)
        if len(samples) >= 3:
            break
    Path("output/_tokopedia_find_cache_sample.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=2, default=str)[:15000],
        encoding="utf-8",
    )
    print("wrote sample", len(samples))
