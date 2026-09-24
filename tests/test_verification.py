import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from scrape_engine import verification
from scrape_engine.scrapers import camoufox_manager as cm
from scrape_engine.scrapers import listing
from scrape_engine.scrapers.antibot import CaptchaRequiredError
from scrape_engine.verification import (
    VerificationStore,
    VerificationUnavailable,
    read_verification,
    safe_target_url,
)

CAPTCHA = "<html><body><div class='geetest_holder'></div></body></html>"
NORMAL = "<html><body>" + ("<p>Produk baterai alkaline</p>" * 50) + "</body></html>"


@pytest.fixture(autouse=True)
def _isolated_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMOUFOX_PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setenv("SHOPEE_PROFILE_DIR", str(tmp_path / "shopee-profile"))
    monkeypatch.setattr(verification, "display_available", lambda: True)
    monkeypatch.setattr(verification, "POLL_SEC", 0.01)


def _wait(store, session_id, statuses, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = store.get(session_id)
        if session["status"] in statuses:
            return session
        time.sleep(0.01)
    raise AssertionError(f"status stayed {store.get(session_id)['status']}")


class _FakePage:
    """Shows the captcha until ``solve`` is set, like a person dragging the slider."""

    def __init__(self, solve: threading.Event):
        self.solve = solve
        self.url = ""
        self.contents_after_solve = 0

    def goto(self, url, **_):
        self.url = url

    def content(self):
        if not self.solve.is_set():
            return CAPTCHA
        self.contents_after_solve += 1
        return NORMAL

    def wait_for_timeout(self, _ms):
        time.sleep(0.005)


class _FakeManager:
    def __init__(self, page):
        self.page = page
        self.pinned = False
        self.closed = 0
        self.profile_path = None

    def close(self):
        self.closed += 1

    def pin(self):
        self.pinned = True

    def unpin(self):
        self.pinned = False

    @contextmanager
    def open_page(self, *, headed=None):
        assert headed is True
        yield self.page, None


def test_browser_runner_waits_for_person_then_saves(monkeypatch, tmp_path):
    solve = threading.Event()
    page = _FakePage(solve)
    fake = _FakeManager(page)
    fake.profile_path = tmp_path / "profiles" / "blibli"
    monkeypatch.setattr(verification, "manager_for", lambda mp: fake)

    store = VerificationStore()
    session = store.start("blibli", "https://www.blibli.com/cari/baterai")
    waiting = _wait(store, session["session_id"], {"waiting"})
    assert waiting["url"] == "https://www.blibli.com/cari/baterai"
    assert store.is_verifying("blibli")
    assert fake.pinned

    time.sleep(0.05)
    assert store.get(session["session_id"])["status"] == "waiting"  # captcha still there

    solve.set()
    done = _wait(store, session["session_id"], {"solved", "error", "expired"})
    assert done["status"] == "solved", done
    assert done["verified_at"]
    assert page.contents_after_solve >= verification.CLEAR_CHECKS
    assert not fake.pinned and fake.closed >= 2  # released before and flushed after
    assert not store.is_verifying("blibli")
    saved = (tmp_path / "profiles" / "blibli" / verification.VERIFICATION_FILE).read_text(encoding="utf-8")
    assert "verified_at" in saved


def test_runner_cancel_releases_profile_without_saving(monkeypatch, tmp_path):
    fake = _FakeManager(_FakePage(threading.Event()))
    fake.profile_path = tmp_path / "profiles" / "alibaba"
    monkeypatch.setattr(verification, "manager_for", lambda mp: fake)
    store = VerificationStore()
    session = store.start("alibaba", None)
    assert session["url"] == "https://www.alibaba.com/"
    _wait(store, session["session_id"], {"waiting"})

    store.cancel(session["session_id"])
    done = _wait(store, session["session_id"], {"cancelled"})
    assert done["verified_at"] is None
    assert not fake.pinned
    assert not (fake.profile_path / verification.VERIFICATION_FILE).exists()


def test_runner_expires_when_nobody_solves(monkeypatch, tmp_path):
    fake = _FakeManager(_FakePage(threading.Event()))
    fake.profile_path = tmp_path / "profiles" / "alibaba"
    monkeypatch.setattr(verification, "manager_for", lambda mp: fake)
    store = VerificationStore()
    session = store.start("alibaba", None, timeout_sec=1)
    done = _wait(store, session["session_id"], {"expired", "solved", "error"}, timeout=10)
    assert done["status"] == "expired"
    assert not fake.pinned


def test_one_window_per_marketplace_and_status():
    release = threading.Event()

    def runner(session, cancel):
        session["_update"](status="waiting")
        release.wait(5)
        return "solved"

    store = VerificationStore(runner=runner)
    first = store.start("blibli", "https://www.blibli.com/cari/aa")
    _wait(store, first["session_id"], {"waiting"})
    again = store.start("blibli", "https://www.blibli.com/cari/bb")
    assert again["session_id"] == first["session_id"]

    status = store.status()
    assert status["marketplaces"]["blibli"]["active_session_id"] == first["session_id"]
    assert status["marketplaces"]["alibaba"]["active_session_id"] is None

    release.set()
    _wait(store, first["session_id"], {"solved"})
    assert read_verification("blibli")["url"] == "https://www.blibli.com/cari/aa"
    assert store.status()["marketplaces"]["blibli"]["verified_at"]


def test_start_rejects_unknown_marketplace_and_missing_display(monkeypatch):
    store = VerificationStore(runner=lambda s, c: "solved")
    with pytest.raises(ValueError):
        store.start("tokopedia")
    monkeypatch.setattr(verification, "display_available", lambda: False)
    with pytest.raises(VerificationUnavailable):
        store.start("blibli")


def test_safe_target_url_only_allows_same_marketplace():
    assert safe_target_url("blibli", "https://www.blibli.com/p/x/is--A-1") == "https://www.blibli.com/p/x/is--A-1"
    assert safe_target_url("blibli", "https://evil.example.com/") == "https://www.blibli.com/"
    assert safe_target_url("blibli", "https://www.alibaba.com/x") == "https://www.blibli.com/"
    assert safe_target_url("alibaba", "file:///etc/passwd") == "https://www.alibaba.com/"


def test_pinned_profile_refuses_other_threads():
    manager = cm.CamoufoxManager(name="blibli")
    manager.pin()
    errors = []

    def other():
        try:
            manager.get_context()
        except cm.ProfileBusyError as exc:
            errors.append(exc)

    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    manager.unpin()
    assert errors and "verifikasi" in str(errors[0])


def test_listing_skips_marketplace_while_verification_runs(monkeypatch):
    monkeypatch.setattr(verification.verification_store, "is_verifying", lambda mp: mp == "blibli")
    with pytest.raises(CaptchaRequiredError) as info:
        listing.open_listing_html("https://www.blibli.com/cari/baterai", headed=None, timeout_ms=1000)
    assert info.value.marketplace == "blibli"
    assert "sedang berjalan" in str(info.value)


def test_marketplaces_get_separate_profiles(tmp_path):
    blibli = cm.manager_for("blibli")
    assert cm.manager_for("shopee") is cm.camoufox_manager
    assert blibli is cm.manager_for("blibli")
    assert blibli.profile_path == tmp_path / "profiles" / "blibli"
    assert cm.manager_for("alibaba").profile_path == tmp_path / "profiles" / "alibaba"


def test_verify_api(monkeypatch):
    from scrape_engine import api

    store = VerificationStore(runner=lambda s, c: (s["_update"](status="waiting"), "solved")[1])
    monkeypatch.setattr(verification, "verification_store", store)
    monkeypatch.setenv("VERIFY_VIEWER_URL", "https://scrape.example/vnc.html")
    client = TestClient(api.app)

    bad = client.post("/verify/sessions", json={"marketplace": "tokopedia"})
    assert bad.status_code == 400

    started = client.post("/verify/sessions", json={"marketplace": "blibli", "url": "https://www.blibli.com/cari/aa"})
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["viewer_url"] == "https://scrape.example/vnc.html"
    _wait(store, body["session_id"], {"solved"})

    polled = client.get(f"/verify/sessions/{body['session_id']}")
    assert polled.json()["status"] == "solved"
    assert client.get("/verify/sessions/nope").status_code == 404
    assert client.get("/verify/status").json()["marketplaces"]["blibli"]["verified_at"]

    monkeypatch.setattr(verification, "display_available", lambda: False)
    assert client.post("/verify/sessions", json={"marketplace": "alibaba"}).status_code == 503
