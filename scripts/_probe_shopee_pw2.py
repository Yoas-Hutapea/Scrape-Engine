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
        if "api" in u and ("item" in u or "pdp" in u):
            try:
                captured.append({"url": u, "status": response.status})
            except Exception:
                pass

    page.on("response", on_response)
    page.goto(url, wait_until="networkidle", timeout=180000)
    page.wait_for_timeout(5000)
    html = page.content()
    Path("output/_shopee_pw.html").write_text(html, encoding="utf-8")
    info = page.evaluate(
        """() => ({
          title: document.title,
          h1: document.querySelector('h1')?.innerText || '',
          og: document.querySelector('meta[property=\"og:title\"]')?.content || '',
          textLen: document.body?.innerText?.length || 0,
          hasVerify: location.href.includes('verify'),
        })"""
    )
    Path("output/_shopee_pw_info.json").write_text(
        json.dumps({"info": info, "captured": captured[:20], "html_len": len(html)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"info": info, "captured_n": len(captured), "html_len": len(html)}, ensure_ascii=False))
    browser.close()
