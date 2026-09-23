from __future__ import annotations

import logging
import re
import time
from html import unescape
from urllib.parse import urljoin

from scrape_engine.detect import (
    UnsupportedMarketplaceError,
    canonicalize_product_url,
    detect_marketplace,
    is_product_url,
)
from scrape_engine.scrapers.common import fetch_html

log = logging.getLogger(__name__)

_HREF_RE = re.compile(r"""(?:href|data-url|data-href)=["']([^"']+)["']""", re.I)
_ABS_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)


def listing_product_urls_from_html(html: str, *, base_url: str, limit: int = 10) -> list[str]:
    """Collect PDP URLs in appearance order from a marketplace search/listing page."""
    if not html:
        return []
    try:
        expected = detect_marketplace(base_url)
    except UnsupportedMarketplaceError:
        expected = None

    candidates: list[str] = []
    for raw in _HREF_RE.findall(html):
        candidates.append(unescape(raw))
    for raw in _ABS_URL_RE.findall(html):
        candidates.append(unescape(raw).rstrip(".,);"))

    seen: set[str] = set()
    found: list[str] = []
    for raw in candidates:
        token = (raw or "").strip()
        if not token or token.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, token.split("#", 1)[0])
        if not url.startswith("http"):
            continue
        url = canonicalize_product_url(url)
        if not is_product_url(url):
            continue
        if expected is not None:
            try:
                if detect_marketplace(url) is not expected:
                    continue
            except UnsupportedMarketplaceError:
                continue
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= max(1, limit):
            break
    return found


def _run_listing_page(page: object, url: str, timeout_ms: int) -> tuple[str, str]:
    from scrape_engine.scrapers.humanize import human_delay, simulate_human_activity

    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)  # type: ignore[attr-defined]
    human_delay(1200, 2500, page)
    try:
        simulate_human_activity(page, rounds=1)
    except Exception:
        pass

    last_html = ""
    deadline = time.time() + min(18.0, max(6.0, timeout_ms / 1000 * 0.4))
    while time.time() < deadline:
        try:
            last_html = page.content()  # type: ignore[attr-defined]
        except Exception:
            last_html = ""
        current = getattr(page, "url", None) or url
        if listing_product_urls_from_html(last_html, base_url=str(current), limit=1):
            break
        try:
            page.wait_for_timeout(800)  # type: ignore[attr-defined]
        except Exception:
            break
    try:
        last_html = page.content() or last_html  # type: ignore[attr-defined]
    except Exception:
        pass
    return str(getattr(page, "url", None) or url), last_html


def open_listing_html(
    url: str,
    *,
    headed: bool | None,
    timeout_ms: int,
    isolated: bool = False,
) -> tuple[str, str]:
    """Open a listing page in Camoufox and return ``(final_url, html)``."""
    from scrape_engine.scrapers.camoufox_manager import camoufox_manager, camoufox_os, shopee_headless

    if not isolated:
        try:
            with camoufox_manager.open_page(headed=headed) as (page, _context):
                return _run_listing_page(page, url, timeout_ms)
        except Exception as exc:
            log.warning("Persistent Camoufox unavailable for listing (%s); using ephemeral browser.", exc)

    from camoufox.sync_api import Camoufox

    with Camoufox(
        headless=shopee_headless(headed),
        humanize=True,
        os=camoufox_os(),
        locale="id-ID",
    ) as browser:
        page = browser.new_page()
        try:
            return _run_listing_page(page, url, timeout_ms)
        finally:
            try:
                page.close()
            except Exception:
                pass


def collect_listing_urls(
    url: str,
    *,
    limit: int = 10,
    headed: bool = False,
    timeout_ms: int = 90_000,
    isolated: bool = False,
) -> list[str]:
    """Collect top product URLs from any supported marketplace listing page."""
    limit = max(1, min(int(limit), 30))
    html = ""
    final = url
    try:
        final, html = open_listing_html(
            url,
            headed=headed or None,
            timeout_ms=timeout_ms,
            isolated=isolated,
        )
    except Exception as exc:
        log.warning("Camoufox listing navigation failed for %s: %s", url, exc)

    urls = listing_product_urls_from_html(html, base_url=final or url, limit=limit)
    if len(urls) >= limit:
        return urls[:limit]

    try:
        fetched_url, fetched_html = fetch_html(url, timeout_s=max(15.0, timeout_ms / 1000))
        extra = listing_product_urls_from_html(
            fetched_html,
            base_url=fetched_url or url,
            limit=limit,
        )
        for item in extra:
            if item not in urls:
                urls.append(item)
            if len(urls) >= limit:
                break
    except Exception:
        pass
    return urls[:limit]
