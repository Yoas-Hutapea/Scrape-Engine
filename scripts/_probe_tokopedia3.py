import re
from pathlib import Path

html = Path("output/_tokopedia_full.html").read_text(encoding="utf-8")
s = Path("output/_script_3.js").read_text(encoding="utf-8")

# Find apollo state assignment
for pat in [
    r"window\.__APOLLO_STATE__\s*=\s*(\{)",
    r"__APOLLO_STATE__\s*=\s*(\{)",
    r"apolloState\s*[:=]\s*(\{)",
    r"ROOT_QUERY",
]:
    m = re.search(pat, s)
    print(pat, "->", bool(m), m.start() if m else None)

# Extract variant blocks more completely
blocks = list(
    re.finditer(
        r'"productID":"(\d+)","price":(\d+),"priceFmt":"([^"]*)","slashPriceFmt":"([^"]*)","discPercentage":"([^"]*)","optionID":\{"type":"json","json":(\[[^\]]*\]),"optionName":\{"type":"json","json":(\[[^\]]*\])\}',
        html,
    )
)
print("blocks", len(blocks))
if blocks:
    print(blocks[0].groups())

# SKU
skus = re.findall(r'"sku":"([^"]+)"', html)
print("skus", skus[:20], "count", len(skus))

# variant option names (dimension)
dims = re.findall(r'"variant":\{"inputType":"[^"]*","option":\{"type":"json","json":(\[[^\]]*\])\}', html)
print("dims", dims[:5])
dims2 = re.findall(r'"name":"(Ukuran|Warna|Color|Size|Variant)","[^\{]*\{"type":"json","json":\[', html)
print("dims2", dims2[:10])
# look for selection types
for m in re.finditer(r'"typename":"pdpProductVariantOption"[^\}]{0,200}', html):
    print(m.group(0)[:200])
    break

idx = html.find('"typename":"pdpProductVariantOption"')
print("around option", html[idx : idx + 500] if idx > 0 else None)

idx = html.find('"sku"')
print("around sku", html[idx - 100 : idx + 200] if idx > 0 else None)

# images
imgs = re.findall(r'https://images\.tokopedia\.net/img/cache/700/[^"\\]+', html)
print("imgs", len(set(imgs)), list(dict.fromkeys(imgs))[:5])

# description snippet
idx = html.find('"description"')
print("desc", html[idx : idx + 300] if idx > 0 else None)

# weight
idx = html.find('"weight"')
print("weight", html[idx : idx + 120] if idx > 0 else None)

# stock object values
for m in re.finditer(r'pdpProductVariantStock[^"]*"value":(\d+)', html):
    print("stockval", m.group(1))
    if m.start() > 500000:
        break
print("stock value count", len(re.findall(r'pdpProductVariantStock', html)))
