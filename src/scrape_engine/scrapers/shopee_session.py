from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scrape_engine.scrapers.camoufox_manager import camoufox_manager, profile_dir, profile_exists
from scrape_engine.scrapers.humanize import human_delay, simulate_human_activity

SESSION_FILE = "session.json"
DEFAULT_WARM_INTERVAL_MIN = 15
DUMMY_KEYWORDS = ("baju", "sepatu", "tas", "kaos")


def session_path() -> Path:
    return profile_dir() / SESSION_FILE


class TokenStore:
    """Persist Shopee cookies / anti-bot headers harvested during warming."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or session_path()

    def get(self) -> dict[str, Any] | None:
        try:
            if self.path.is_file():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else None
        except Exception:
            return None
        return None

    def save(self, data: dict[str, Any]) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            current = self.get() or {}
            updated = {**current, **data, "updated_at": datetime.now(timezone.utc).isoformat()}
            self.path.write_text(json.dumps(updated, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    def is_valid(self, max_age_minutes: int = 120) -> bool:
        data = self.get()
        if not data or not data.get("cookie") or not data.get("af-ac-enc-dat"):
            return False
        raw = data.get("updated_at")
        if not raw:
            return False
        try:
            updated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return False
        age_min = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds() / 60
        return age_min < max_age_minutes


def session_headers() -> dict[str, str]:
    data = TokenStore().get() or {}
    headers: dict[str, str] = {}
    cookie = data.get("cookie")
    if cookie:
        headers["Cookie"] = str(cookie)
    enc = data.get("af-ac-enc-dat")
    if enc:
        headers["af-ac-enc-dat"] = str(enc)
    csrf = data.get("x-csrftoken") or data.get("x-csrf-token")
    if csrf:
        headers["x-csrftoken"] = str(csrf)
    ua = data.get("user_agent") or data.get("userAgent")
    if ua:
        headers["User-Agent"] = str(ua)
    return headers


def session_status() -> dict[str, Any]:
    store = TokenStore()
    data = store.get() or {}
    return {
        "profile": profile_exists(),
        "ready": store.is_valid(),
        "browser_open": camoufox_manager.is_open,
        "updated_at": data.get("updated_at"),
        "profile_dir": str(profile_dir()),
    }


def _cookie_header(context: Any) -> str:
    try:
        cookies = context.cookies()
    except Exception:
        return ""
    return "; ".join(f"{c.get('name')}={c.get('value')}" for c in cookies if c.get("name"))


def _has_login_cookie(context: Any) -> bool:
    try:
        cookies = context.cookies()
    except Exception:
        return False
    return any(c.get("name") == "SPC_U" and c.get("value") for c in cookies)


def setup_session(*, timeout_ms: int = 10 * 60 * 1000) -> dict[str, Any]:
    """Open a headed Camoufox window so the user can log in once (persistent profile)."""
    camoufox_manager.close()
    captured: dict[str, Any] = {"success": False}
    with camoufox_manager.open_page(headed=True) as (page, context):
        page.goto("https://shopee.co.id/buyer/login", wait_until="domcontentloaded", timeout=90_000)
        deadline = time.time() + (timeout_ms / 1000)
        logged_in = False
        while time.time() < deadline:
            url = page.url or ""
            on_login = "/buyer/login" in url or "/buyer/signup" in url
            if _has_login_cookie(context) and not on_login:
                logged_in = True
                break
            time.sleep(2)

        if not logged_in:
            captured["error"] = "Login tidak terdeteksi (timeout). Jalankan ulang setup-session."
            camoufox_manager.close()
            return captured

        simulate_human_activity(page, rounds=3)
        TokenStore().save(
            {
                "cookie": _cookie_header(context),
                "user_agent": page.evaluate("() => navigator.userAgent"),
            }
        )
        captured["success"] = True

    camoufox_manager.close()
    return captured


def warm_session(*, keep_open: bool = True, timeout_ms: int = 60_000) -> dict[str, Any]:
    """Visit Shopee and harvest fresh cookies / af-ac-enc-dat headers."""
    import random

    captured = {
        "cookie": "",
        "af-ac-enc-dat": "",
        "x-csrftoken": "",
        "user_agent": "",
    }

    def on_request(request: Any) -> None:
        url = request.url
        headers = request.headers
        if "/api/v4/search/search_items" in url and headers.get("af-ac-enc-dat"):
            captured["af-ac-enc-dat"] = headers.get("af-ac-enc-dat") or ""
            captured["x-csrftoken"] = headers.get("x-csrftoken") or headers.get("x-csrf-token") or ""

    try:
        with camoufox_manager.open_page(headed=None) as (page, context):
            page.on("request", on_request)
            page.goto("https://shopee.co.id/", wait_until="domcontentloaded", timeout=timeout_ms)
            simulate_human_activity(page, rounds=1)
            human_delay(1000, 2000, page)

            keyword = random.choice(DUMMY_KEYWORDS)
            page.goto(
                f"https://shopee.co.id/search?keyword={keyword}",
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            human_delay(3000, 5000, page)
            captured["cookie"] = _cookie_header(context)
            captured["user_agent"] = page.evaluate("() => navigator.userAgent")
    except Exception as exc:
        if not keep_open:
            camoufox_manager.close()
        return {"success": False, "error": str(exc)}

    if captured["af-ac-enc-dat"] or captured["cookie"]:
        TokenStore().save(captured)
        if not keep_open:
            camoufox_manager.close()
        return {"success": True, "data": {k: v for k, v in captured.items() if k != "cookie"}}

    if not keep_open:
        camoufox_manager.close()
    return {"success": False, "error": "Tidak bisa menangkap token Shopee (af-ac-enc-dat)."}


def ensure_warm_session() -> None:
    if not profile_exists():
        return
    interval = int(os.getenv("SHOPEE_WARM_INTERVAL_MIN", str(DEFAULT_WARM_INTERVAL_MIN)))
    if TokenStore().is_valid(max_age_minutes=interval):
        return
    try:
        warm_session(keep_open=True)
    except Exception:
        return
