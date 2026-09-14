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
