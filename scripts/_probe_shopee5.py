import httpx
import re
import json
from pathlib import Path

shop_id, item_id = "110101298", "41410763816"
product_url = f"https://shopee.co.id/ASUS-Mouse-Wireless-Fragrance-MD101-Original-i.{shop_id}.{item_id}"
headers = {
    "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
with httpx.Client(headers=headers, follow_redirects=True, timeout=30) as client:
    r = client.get(product_url)
    html = r.text
    Path("output/_shopee_fb.html").write_text(html, encoding="utf-8")
    print("status", r.status_code, "len", len(html), "cookies", dict(client.cookies))
    ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    print("ld count", len(ld))
    for i, block in enumerate(ld):
        try:
            data = json.loads(block)
            Path(f"output/_shopee_ld_{i}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("ld", i, type(data).__name__, str(data)[:300])
        except Exception as e:
            print("ld fail", i, e)

    api_headers = {
        "User-Agent": headers["User-Agent"],
        "Accept": "application/json",
        "Referer": product_url,
        "X-Shopee-Language": "id",
        "X-API-SOURCE": "pc",
    }
    for u in [
        f"https://shopee.co.id/api/v4/pdp/get_pc?shop_id={shop_id}&item_id={item_id}",
        f"https://shopee.co.id/api/v4/item/get?itemid={item_id}&shopid={shop_id}",
    ]:
        ar = client.get(u, headers=api_headers)
        print("api", ar.status_code, ar.text[:180])
