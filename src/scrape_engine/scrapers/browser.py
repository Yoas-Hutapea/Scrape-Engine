from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator, Literal

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-http2",
]

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


def _same_shopee_item(a: str, b: str) -> bool:
    def ids(u: str) -> tuple[str, str] | None:
        m = re.search(r"-i\.(\d+)\.(\d+)", u)
        if m:
            return m.group(1), m.group(2)
        m = re.search(r"/product/(\d+)/(\d+)", u)
        if m:
            return m.group(1), m.group(2)
        return None

    ia, ib = ids(a), ids(b)
    return bool(ia and ib and ia == ib)


@contextmanager
def launch_page(
    *,
    headed: bool = False,
    storage_state: str | None = None,
    engine: Literal["chromium", "firefox"] = "chromium",
    cdp_url: str | None = None,
    reuse_existing_page: bool = False,
    url_hint: str | None = None,
) -> Iterator[tuple[Playwright, Browser, Page, BrowserContext, bool]]:
    """Open a page in a new browser, or attach to an already-running Chrome via CDP.

    Yields ``(playwright, browser, page, context, owns_page)``.
    When ``owns_page`` is False the page was an existing user tab — do not close it.
    """
    with sync_playwright() as p:
        attached = False
        owns_page = True
        browser: Browser
        context: BrowserContext
        page: Page

        if cdp_url:
            browser = p.chromium.connect_over_cdp(cdp_url)
            attached = True
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = browser.new_context()

            chosen: Page | None = None
            if reuse_existing_page and context.pages:
                hint = (url_hint or "").lower()
                ranked: list[Page] = []
                for candidate in context.pages:
                    u = (candidate.url or "").lower()
                    if "chrome://" in u or u in {"about:blank", ""}:
                        continue
                    if hint and (hint in u or _same_shopee_item(hint, u)):
                        ranked.insert(0, candidate)
                    elif "shopee." in u or "tokopedia." in u:
                        ranked.append(candidate)
                if ranked:
                    chosen = ranked[0]
                    owns_page = False

            if chosen is None:
                page = context.new_page()
                owns_page = True
            else:
                page = chosen
        else:
            browser_obj: Browser | None = None
            if engine == "firefox":
                browser_obj = p.firefox.launch(headless=not headed)
            else:
                for kwargs in (
                    {"channel": "chrome", "headless": not headed, "args": LAUNCH_ARGS},
                    {"headless": not headed, "args": LAUNCH_ARGS},
                    {"headless": not headed},
                ):
                    try:
                        browser_obj = p.chromium.launch(**kwargs)
                        break
                    except Exception:
                        continue
                if browser_obj is None:
                    browser_obj = p.chromium.launch(headless=not headed)

            browser = browser_obj
            context_kwargs: dict = {
                "user_agent": DEFAULT_UA,
                "locale": "id-ID",
                "viewport": {"width": 1366, "height": 900},
                "ignore_https_errors": True,
                "extra_http_headers": {
                    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            }
            if storage_state:
                context_kwargs["storage_state"] = storage_state

            context = browser.new_context(**context_kwargs)
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
            page = context.new_page()

        try:
            yield p, browser, page, context, owns_page
        finally:
            if owns_page:
                try:
                    page.close()
                except Exception:
                    pass
            if not attached:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
            else:
                try:
                    browser.close()
                except Exception:
                    pass


def goto_resilient(page: Page, url: str, timeout_ms: int = 60_000) -> None:
    """Navigate with fallbacks for flaky marketplace stacks."""
    last_err: Exception | None = None
    for wait_until in ("commit", "domcontentloaded", "load"):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return
        except Exception as exc:
            last_err = exc
            continue
    if last_err:
        raise last_err
