import re
from pathlib import Path

html = Path("output/_shopee_html.html").read_text(encoding="utf-8")
print("len", len(html))
for pat in ["og:title", "og:description", "og:image", "application/ld+json", "itemid", "tier_variations", "__NEXT_DATA__", "rawData", "item"]:
    print(pat, html.find(pat))

for m in re.finditer(r'<meta[^>]+>', html, re.I):
    tag = m.group(0)
    if "og:" in tag or "description" in tag.lower() or "product" in tag.lower():
        print(tag)

# scripts with data
scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I)
print("scripts", len(scripts))
for i, s in enumerate(scripts):
    if any(k in s for k in ("itemid", "price", "tier_variations", "models", "description")):
        print("script", i, "len", len(s), s[:200].replace("\n", " "))
        Path(f"output/_shopee_script_{i}.js").write_text(s, encoding="utf-8")
