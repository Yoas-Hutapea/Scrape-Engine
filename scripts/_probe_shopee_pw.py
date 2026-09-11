from playwright.sync_api import sync_playwright
import json
from pathlib import Path

url = "https://shopee.co.id/ASUS-Mouse-Wireless-Fragrance-MD101-Original-i.110101298.41410763816"
captured = []

with sync_playwright() as p:
    browser = p.firefox.launch(headless=True)
    context = browser.new_context(
        locale="id-ID",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        viewport={"width": 1366, "height": 900},
    )
    page = context.new_page()

    def on_response(response):
        u = response.url
        if "/api/v4/pdp/" in u or "/api/v4/item/" in u:
            try:
                captured.append({"url": u, "status": response.status, "body": response.json()})
            except Exception:
                captured.append({"url": u, "status": response.status, "body": None})

    page.on("response", on_response)
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(8000)
    print("final", page.url)
    print("title", page.title())
    print("captured", len(captured))
    for c in captured[:3]:
        print(c["status"], c["url"][:100], type(c["body"]))
    Path("output/_shopee_pw.json").write_text(
        json.dumps({"url": page.url, "title": page.title(), "n": len(captured)}, ensure_ascii=False),
        encoding="utf-8",
    )
    if captured:
        Path("output/_shopee_cap0.json").write_text(
            json.dumps(captured[0], ensure_ascii=False)[:20000], encoding="utf-8"
        )
    browser.close()
