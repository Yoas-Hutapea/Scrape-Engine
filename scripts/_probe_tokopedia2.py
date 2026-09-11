import httpx
import re
from pathlib import Path

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
html = httpx.get(url, follow_redirects=True, timeout=30, headers=headers).text
Path("output/_tokopedia_full.html").write_text(html, encoding="utf-8")

# find script containing pdpMainInfo / ROOT_QUERY
scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I)
print("scripts", len(scripts))
for i, s in enumerate(scripts):
    if "pdpMainInfo" in s or "ROOT_QUERY" in s or "basicInfo" in s:
        print("hit", i, "len", len(s), "start", s[:120].replace("\n", " "))
        Path(f"output/_script_{i}.js").write_text(s, encoding="utf-8")

# try regex extract children products
children = re.findall(
    r'"productID":"(\d+)","price":(\d+),"priceFmt":"[^"]*","slashPriceFmt":"([^"]*)".*?"optionName":\{"type":"json","json":\[(.*?)\]\}',
    html,
)
print("children matches", len(children))
print(children[:3])

# stock values nearby
stocks = re.findall(r'"typename":"pdpProductVariantStock".*?"value":(\d+)', html)
print("stocks via typename", len(stocks), stocks[:5])
stocks2 = re.findall(r'"stock":(\d+)', html)
print("stock nums", stocks2[:20])

# description
for key in ["description", "Description", "longDescription", "weight"]:
    print(key, html.find(f'"{key}"'))
