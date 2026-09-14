from __future__ import annotations

import json
from pathlib import Path

from scrape_engine.scrapers.tokopedia import _extract_tokopedia_cache, resolve_refs

html = Path("output/_tokopedia_find.html").read_text(encoding="utf-8")
cache = _extract_tokopedia_cache(html) or {}
products = [v for v in cache.values() if isinstance(v, dict) and v.get("__typename") == "searchProductV5Product"]
print("products", len(products))
resolved = resolve_refs(cache, products[0]) if products else {}
Path("output/_tokopedia_find_product.json").write_text(
    json.dumps(resolved, ensure_ascii=False, indent=2, default=str)[:20000],
    encoding="utf-8",
)
print(json.dumps({k: resolved.get(k) for k in list(resolved)[:40]}, ensure_ascii=False, indent=2, default=str)[:3000])
