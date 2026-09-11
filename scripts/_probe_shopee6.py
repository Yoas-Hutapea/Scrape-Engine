from pathlib import Path
import re
import html as H

t = Path("output/_shopee_fb.html").read_text(encoding="utf-8")
print("ld+json pos", t.find("ld+json"))
print("Product pos", t.find('"@type":"Product"'), t.find("Product"))

for m in re.finditer(r"<meta\b[^>]*>", t, flags=re.I):
    s = m.group(0)
    if "og:" in s or "description" in s.lower():
        print(H.unescape(s)[:250])

# price patterns
for pat in [r'"price"\s*:\s*"?(\d+)"?', r"Rp\s*[\d\.]+", r"product:price:amount"]:
    found = re.findall(pat, t)
    print(pat, found[:5])
