import httpx
import re
import json

url = (
    "https://www.tokopedia.com/isku-tools-official-store/"
    "isku-mata-bor-hole-saw-lubang-tembok-beton-hollow-core-saw-beton-pelubang-beton-tembok-pipa-drill-bit-perkakas-alat-pertukangan-30-40-50-60-65-80-90-mm-set-30mm-88c7f"
)
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
r = httpx.get(url, follow_redirects=True, timeout=30, headers=headers)
html = r.text
print("len", len(html))
for pat in ["__NEXT_DATA__", "pdpGetLayout", "basicInfo", "productName", "application/ld+json"]:
    print(pat, html.find(pat))

m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
print("next_data", bool(m), "len", len(m.group(1)) if m else 0)

for m2 in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
    print("ldjson", m2.group(1)[:400])
    print("---")

# save snippet around productName
idx = html.find("productName")
if idx > 0:
    Path = __import__("pathlib").Path
    Path("output/_tokopedia_snip.txt").write_text(html[max(0, idx - 200) : idx + 2000], encoding="utf-8")
    print("wrote snip")
