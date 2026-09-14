from scrape_engine.scrapers.camoufox_manager import camoufox_os, shopee_headless
from scrape_engine.scrapers.shopee_session import TokenStore, session_headers


def test_token_store_roundtrip(tmp_path):
    store = TokenStore(tmp_path / "session.json")
    assert store.get() is None
    assert not store.is_valid()
    assert store.save({"cookie": "SPC_U=abc", "af-ac-enc-dat": "token-1"})
    data = store.get()
    assert data is not None
    assert data["cookie"] == "SPC_U=abc"
    assert data["af-ac-enc-dat"] == "token-1"
    assert store.is_valid()


def test_session_headers_reads_store(tmp_path, monkeypatch):
    store = TokenStore(tmp_path / "session.json")
    store.save(
        {
            "cookie": "SPC_U=abc",
            "af-ac-enc-dat": "enc",
            "x-csrftoken": "csrf",
            "user_agent": "TestUA",
        }
    )
    monkeypatch.setattr("scrape_engine.scrapers.shopee_session.session_path", lambda: store.path)
    headers = session_headers()
    assert headers["Cookie"] == "SPC_U=abc"
    assert headers["af-ac-enc-dat"] == "enc"
    assert headers["x-csrftoken"] == "csrf"
    assert headers["User-Agent"] == "TestUA"


def test_camoufox_os_env_override(monkeypatch):
    monkeypatch.setenv("SHOPEE_OS", "linux")
    assert camoufox_os() == "linux"
    monkeypatch.setenv("SHOPEE_OS", "windows")
    assert camoufox_os() == "windows"


def test_shopee_headless_linux_virtual_without_display(monkeypatch):
    monkeypatch.setenv("SHOPEE_OS", "linux")
    monkeypatch.setenv("SHOPEE_HEADLESS", "auto")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert shopee_headless() == "virtual"
    assert shopee_headless(headed=True) is False


def test_shopee_headless_explicit_modes(monkeypatch):
    monkeypatch.setenv("SHOPEE_HEADLESS", "true")
    assert shopee_headless() is True
    monkeypatch.setenv("SHOPEE_HEADLESS", "false")
    assert shopee_headless() is False
    monkeypatch.setenv("SHOPEE_HEADLESS", "virtual")
    assert shopee_headless() == "virtual"
