from pathlib import Path

from scrape_engine.scrapers.tokopedia import collect_listing_product_urls_from_html

html = Path("output/_tokopedia_find.html").read_text(encoding="utf-8")
urls = collect_listing_product_urls_from_html(html, limit=10)
print("count", len(urls))
for u in urls:
    print(u)
