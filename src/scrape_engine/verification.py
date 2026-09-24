"""Human-in-the-loop captcha verification.

When a marketplace answers with a captcha / verify wall, a person solves it once
in a headed Camoufox window that runs on the server display (Xvfb, viewed through
noVNC). The window uses the marketplace's persistent profile, so the resulting
cookies (cf_clearance, x5sec, ...) stay on disk and later scrapes reuse them with
the same fingerprint and IP. The engine never interacts with the captcha itself.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from scrape_engine.scrapers.antibot import detect_block
from scrape_engine.scrapers.camoufox_manager import (
    PROFILED_MARKETPLACES,
    camoufox_os,
    has_display,
    manager_for,
)

VERIFIABLE_MARKETPLACES: tuple[str, ...] = ("shopee", *PROFILED_MARKETPLACES)
VERIFICATION_FILE = "verification.json"

DEFAULT_URLS: dict[str, str] = {
    "shopee": "https://shopee.co.id/",
    "blibli": "https://www.blibli.com/",
    "alibaba": "https://www.alibaba.com/",
}

# Consecutive clear checks (2 s apart) before a page counts as solved; managed
# challenges briefly flash a normal page while redirecting.
CLEAR_CHECKS = 2
POLL_SEC = 2.0

Status = str  # starting | waiting | solved | expired | error | cancelled


class VerificationUnavailable(RuntimeError):
    """No display for a headed browser (Ubuntu without Xvfb/noVNC)."""


def viewer_url() -> str | None:
    """Public noVNC URL shown to the person who solves the captcha (VERIFY_VIEWER_URL)."""
    raw = os.getenv("VERIFY_VIEWER_URL", "").strip()
    return raw or None


def display_available() -> bool:
    return camoufox_os() != "linux" or has_display()


def default_timeout_sec() -> int:
    try:
        return max(60, min(int(os.getenv("VERIFY_TIMEOUT_SEC", "600")), 3600))
    except ValueError:
        return 600


def safe_target_url(marketplace: str, url: str | None) -> str:
    """Only open pages of the marketplace being verified (never an arbitrary site)."""
    from scrape_engine.detect import UnsupportedMarketplaceError, detect_marketplace

    candidate = (url or "").strip()
    if candidate.startswith(("http://", "https://")):
        try:
            if detect_marketplace(candidate).value == marketplace:
                return candidate
        except UnsupportedMarketplaceError:
            pass
    return DEFAULT_URLS[marketplace]


def read_verification(marketplace: str) -> dict[str, Any] | None:
    path = manager_for(marketplace).profile_path / VERIFICATION_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_verification(marketplace: str, url: str) -> str:
    stamp = datetime.now(timezone.utc).isoformat()
    path = manager_for(marketplace).profile_path / VERIFICATION_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"verified_at": stamp, "url": url}), encoding="utf-8")
    except Exception:
        pass
    return stamp


PageRunner = Callable[[dict[str, Any], threading.Event], Status]


class VerificationStore:
    """At most one open verification window per marketplace."""

    def __init__(self, *, runner: PageRunner | None = None, max_sessions: int = 40) -> None:
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._active: dict[str, str] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._runner = runner or self._run_browser
        self._max_sessions = max_sessions

    # ---- public API -------------------------------------------------------

    def start(self, marketplace: str, url: str | None = None, *, timeout_sec: int | None = None) -> dict[str, Any]:
        marketplace = (marketplace or "").strip().lower()
        if marketplace not in VERIFIABLE_MARKETPLACES:
            raise ValueError(
                f"Verifikasi captcha tidak didukung untuk '{marketplace}'. "
                f"Pilihan: {', '.join(VERIFIABLE_MARKETPLACES)}."
            )
        if not display_available():
            raise VerificationUnavailable(
                "Server tidak punya layar untuk jendela verifikasi. Jalankan Scrape Engine dengan "
                "DISPLAY dari Xvfb + noVNC (lihat deploy/ubuntu/README.md)."
            )

        with self._lock:
            active_id = self._active.get(marketplace)
            if active_id and self._sessions.get(active_id, {}).get("status") in {"starting", "waiting"}:
                return self._public(active_id)

            now = datetime.now(timezone.utc)
            timeout = timeout_sec or default_timeout_sec()
            session_id = uuid.uuid4().hex
            self._sessions[session_id] = {
                "session_id": session_id,
                "marketplace": marketplace,
                "url": safe_target_url(marketplace, url),
                "status": "starting",
                "message": None,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=timeout)).isoformat(),
                "timeout_sec": timeout,
                "verified_at": None,
            }
            self._active[marketplace] = session_id
            cancel = threading.Event()
            self._cancel[session_id] = cancel
            self._trim()

        threading.Thread(
            target=self._run,
            args=(session_id, cancel),
            name=f"verify-{marketplace}-{session_id[:6]}",
            daemon=True,
        ).start()
        return self._public(session_id)

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            if session_id not in self._sessions:
                return None
            return self._public(session_id)

    def cancel(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            event = self._cancel.get(session_id)
            if session_id not in self._sessions:
                return None
        if event:
            event.set()
        return self.get(session_id)

    def is_verifying(self, marketplace: str) -> bool:
        with self._lock:
            active_id = self._active.get(marketplace)
            return bool(active_id and self._sessions.get(active_id, {}).get("status") in {"starting", "waiting"})

    def status(self) -> dict[str, Any]:
        marketplaces: dict[str, Any] = {}
        for marketplace in VERIFIABLE_MARKETPLACES:
            saved = read_verification(marketplace) or {}
            with self._lock:
                active_id = self._active.get(marketplace)
                active = self._sessions.get(active_id) if active_id else None
                live = active_id if active and active.get("status") in {"starting", "waiting"} else None
            marketplaces[marketplace] = {
                "verified_at": saved.get("verified_at"),
                "active_session_id": live,
            }
        return {
            "display": display_available(),
            "viewer_url": viewer_url(),
            "marketplaces": marketplaces,
        }

    # ---- internals --------------------------------------------------------

    def _public(self, session_id: str) -> dict[str, Any]:
        data = dict(self._sessions[session_id])
        data["viewer_url"] = viewer_url()
        return data

    def _update(self, session_id: str, **fields: Any) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].update(fields)

    def _snapshot(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._sessions[session_id])

    def _run(self, session_id: str, cancel: threading.Event) -> None:
        session = self._snapshot(session_id)
        try:
            status = self._runner({**session, "_update": lambda **f: self._update(session_id, **f)}, cancel)
        except Exception as exc:
            self._update(session_id, status="error", message=str(exc))
            status = "error"
        if status == "solved":
            stamp = _write_verification(session["marketplace"], session["url"])
            self._update(session_id, status="solved", verified_at=stamp, message=None)
        elif status in {"expired", "cancelled"}:
            self._update(session_id, status=status)
        with self._lock:
            if self._active.get(session["marketplace"]) == session_id:
                self._active.pop(session["marketplace"], None)
            self._cancel.pop(session_id, None)

    @staticmethod
    def _run_browser(session: dict[str, Any], cancel: threading.Event) -> Status:
        """Open the marketplace page headed and wait until the person clears the wall."""
        update = session["_update"]
        manager = manager_for(session["marketplace"])
        manager.close()  # release the profile lock held by an idle scrape browser
        manager.pin()
        try:
            with manager.open_page(headed=True) as (page, _context):
                page.goto(session["url"], wait_until="domcontentloaded", timeout=90_000)
                update(status="waiting")
                deadline = time.monotonic() + int(session["timeout_sec"])
                clear = 0
                while time.monotonic() < deadline:
                    if cancel.is_set():
                        return "cancelled"
                    try:
                        html = page.content() or ""
                        current = page.url or ""
                    except Exception:
                        html, current = "", ""
                    if html and not detect_block(html, current):
                        clear += 1
                        if clear >= CLEAR_CHECKS:
                            # Let the site finish setting cookies before the profile is flushed.
                            page.wait_for_timeout(1500)
                            return "solved"
                    else:
                        clear = 0
                    page.wait_for_timeout(int(POLL_SEC * 1000))
                return "expired"
        finally:
            manager.unpin()
            manager.close()  # flush cookies to disk and free the profile for scrapes

    def _trim(self) -> None:
        while len(self._sessions) > self._max_sessions:
            oldest, data = next(iter(self._sessions.items()))
            if data.get("status") in {"starting", "waiting"}:
                break
            self._sessions.pop(oldest, None)


verification_store = VerificationStore()
