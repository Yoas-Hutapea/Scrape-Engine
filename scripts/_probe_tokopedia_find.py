from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import httpx

url = "https://www.tokopedia.com/find/baterai-alkaline-aa"
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}

out = Path("output")
out.mkdir(parents=True, exist_ok=True)

with httpx.Client(headers=headers, follow_redirects=True, timeout=45, http2=False) as client:
    resp = client.get(url)

html = resp.text
(out / "_tokopedia_find.html").write_text(html, encoding="utf-8")
print("status", resp.status_code, "final", resp.url, "len", len(html))

for pat in ("__NEXT_DATA__", "window.__cache", "pdpBasicInfo", "productUrl", "AceSearchProduct"):
    print(pat, html.find(pat))

m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, flags=re.I | re.S)
print("next_data", bool(m), "len", len(m.group(1)) if m else 0)
if m:
    data = json.loads(m.group(1))
    (out / "_tokopedia_find_next.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2)[:20000],
        encoding="utf-8",
    )
    print("next keys", list(data.keys())[:20])

hrefs = re.findall(r'https://www\.tokopedia\.com/[^\s"\'<>]+', html)
print("raw hrefs", len(hrefs), "unique", len(set(hrefs)))
for u in list(dict.fromkeys(hrefs))[:30]:
    print(" ", u[:160])

# relative product-looking paths
rel = re.findall(r'href="(/[^"]+)"', html)
interesting = [h for h in rel if h.count("/") >= 2 and "find" not in h and "search" not in h]
print("rel samples", len(interesting))
for h in interesting[:20]:
    print(" ", h[:160])
