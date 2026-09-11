import httpx
from pathlib import Path

shop_id, item_id = "110101298", "41410763816"
product_url = f"https://shopee.co.id/ASUS-Mouse-Wireless-Fragrance-MD101-Original-i.{shop_id}.{item_id}"
uas = [
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]
for ua in uas:
    r = httpx.get(
        product_url,
        headers={"User-Agent": ua, "Accept": "text/html"},
        follow_redirects=True,
        timeout=30,
    )
    print("UA", ua[:40], "status", r.status_code, "url", str(r.url)[:80], "len", len(r.text))
    print(" title?", "og:title" in r.text, "verify" in str(r.url))
    Path("output/_shopee_html.html").write_text(r.text, encoding="utf-8")
    if "og:title" in r.text:
        break
