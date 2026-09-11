import httpx
import json
from pathlib import Path

shop_id, item_id = "110101298", "41410763816"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": f"https://shopee.co.id/product/{shop_id}/{item_id}",
    "X-Shopee-Language": "id",
    "X-Requested-With": "XMLHttpRequest",
    "X-API-SOURCE": "pc",
}
urls = [
    f"https://shopee.co.id/api/v4/pdp/get_pc?shop_id={shop_id}&item_id={item_id}",
    f"https://shopee.co.id/api/v4/pdp/get?shopid={shop_id}&itemid={item_id}",
    f"https://shopee.co.id/api/v4/item/get?shopid={shop_id}&itemid={item_id}",
    f"https://shopee.co.id/api/v2/item/get?itemid={item_id}&shopid={shop_id}",
]
for u in urls:
    try:
        r = httpx.get(u, headers=headers, timeout=30, follow_redirects=True)
        print(u, r.status_code, r.headers.get("content-type"), len(r.text))
        Path("output/_shopee_api.json").write_text(r.text[:5000], encoding="utf-8")
        print(r.text[:200].replace("\n", " "))
    except Exception as e:
        print(u, "ERR", e)
