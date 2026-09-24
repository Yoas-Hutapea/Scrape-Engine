import pytest

from scrape_engine.detect import Marketplace
from scrape_engine.models import Product
from scrape_engine.scrapers import listing
from scrape_engine.scrapers.antibot import (
    CAPTCHA_REQUIRED,
    CaptchaRequiredError,
    detect_block,
    error_entry,
)
from scrape_engine.service import ScrapeService

ALIBABA_PUNISH = """
<html><head><title>Verification</title></head><body>
<div id="nc_1_wrapper"><span id="nc_1_n1z" class="nc_iconfont btn_slide"></span></div>
<div>Please slide to verify</div>
<script src="https://g.alicdn.com/sd/punish/punish.js"></script>
</body></html>
"""

BLIBLI_GEETEST = """
<html><body><div class="geetest_holder geetest_wind"><div class="geetest_slider_button"></div></div></body></html>
"""

BLIBLI_CLOUDFLARE = """
<html><head><title>Online Mall Blibli, Belanja Online Aman, Nyaman &amp; Terpercaya!</title>
<style>.cf-challenge { margin-bottom: 8px; display: flex; }</style></head><body>
<div class="title">Tunggu dulu, verifikasi sedang berjalan.</div>
<div class="subtitle">Check below to verify if you're human. Enable JavaScript and cookies to continue</div>
<div>Ray ID: a3fe7fe6aa4bca88</div></body></html>
"""

AKAMAI_DENIED = """
<html><head><title>Access Denied</title></head><body>
<h1>Access Denied</h1>You don't have permission to access this server.<p>Reference #18.abcd.1234</p>
</body></html>
"""

NORMAL_PDP = (
    "<html><head><title>Baterai Alkaline AA | Blibli</title>"
    '<meta property="og:title" content="Baterai Alkaline AA">'
    '<script src="https://www.google.com/recaptcha/api.js"></script></head><body>'
    + ("<p>Deskripsi produk baterai alkaline tahan lama untuk remote dan jam dinding.</p>" * 40)
    + "</body></html>"
)


@pytest.mark.parametrize(
    ("html", "url"),
    [
        (ALIBABA_PUNISH, "https://www.alibaba.com/trade/search?SearchText=aa"),
        ("", "https://www.alibaba.com//_____tmd_____/punish?x5secdata=abc"),
        (BLIBLI_GEETEST, "https://www.blibli.com/cari/baterai"),
        (BLIBLI_CLOUDFLARE, "https://www.blibli.com/cari/baterai-alkaline-aa"),
        (AKAMAI_DENIED, "https://www.blibli.com/p/baterai/is--ABC-1"),
        ("<html><body>loading</body></html>", "https://shopee.co.id/verify/traffic?is_initial=true"),
        ("<html><body><div>Captcha</div>Please verify</body></html>", "https://www.blibli.com/cari/x"),
    ],
)
def test_detect_block_recognises_challenge_pages(html, url):
    assert detect_block(html, url)


def test_detect_block_ignores_normal_page_that_loads_recaptcha():
    assert detect_block(NORMAL_PDP, "https://www.blibli.com/p/baterai/is--ABC-1") is None
    assert detect_block("", "https://www.tokopedia.com/shop/baterai-aa") is None


def test_error_entry_marks_captcha_code():
    exc = CaptchaRequiredError("blibli", "https://www.blibli.com/cari/x", "geetest_")
    entry = error_entry(exc, url="https://www.blibli.com/cari/x")
    assert entry["code"] == CAPTCHA_REQUIRED
    assert entry["marketplace"] == "blibli"
    assert "diblokir captcha" in entry["error"]

    plain = error_entry(RuntimeError("boom"), url="u", marketplace="tokopedia")
    assert "code" not in plain and plain["marketplace"] == "tokopedia"


def test_collect_listing_urls_raises_on_captcha_without_http_fallback(monkeypatch):
    monkeypatch.setattr(
        listing,
        "open_listing_html",
        lambda url, **_: ("https://www.alibaba.com//_____tmd_____/punish?x5secdata=1", ALIBABA_PUNISH),
    )

    def fail_fetch(*_a, **_k):
        raise AssertionError("HTTP fallback must be skipped on a captcha wall")

    monkeypatch.setattr(listing, "fetch_html", fail_fetch)
    with pytest.raises(CaptchaRequiredError) as info:
        listing.collect_listing_urls("https://www.alibaba.com/trade/search?SearchText=aa", limit=5)
    assert info.value.marketplace == "alibaba"


class _BlockedScraper:
    def __init__(self):
        self.calls = 0

    def scrape(self, url, **_):
        self.calls += 1
        raise CaptchaRequiredError("blibli", url, "geetest_")


class _OkScraper:
    def scrape(self, url, **_):
        return Product(name="Baterai AA", source_link=url)


def test_scrape_many_skips_rest_of_blocked_marketplace():
    service = ScrapeService()
    blocked = _BlockedScraper()
    service._scrapers[Marketplace.BLIBLI] = blocked
    service._scrapers[Marketplace.TOKOPEDIA] = _OkScraper()

    result = service.scrape_many(
        [
            "https://www.blibli.com/p/baterai-a/is--AAA-1",
            "https://www.tokopedia.com/shop-a/baterai-aa-1",
            "https://www.blibli.com/p/baterai-b/is--BBB-2",
            "https://www.blibli.com/p/baterai-c/is--CCC-3",
        ],
        delay_sec=0,
    )

    assert blocked.calls == 1
    assert [p.name for p in result.products] == ["Baterai AA"]
    captcha = [e for e in result.errors if e.get("code") == CAPTCHA_REQUIRED]
    assert len(captcha) == 3
    assert all(e["marketplace"] == "blibli" for e in captcha)
    assert sum(e["error"].startswith("Dilewati") for e in captcha) == 2


def test_search_marketplaces_reports_captcha_code(monkeypatch):
    service = ScrapeService()

    def fake_expand(url, **_):
        if "blibli" in url:
            raise CaptchaRequiredError("blibli", url, "geetest_")
        return ["https://www.tokopedia.com/shop-a/baterai-aa-1"]

    monkeypatch.setattr(service, "expand_listing", fake_expand)
    found = service.search_marketplaces(
        "baterai aa",
        limit=1,
        marketplaces=[Marketplace.TOKOPEDIA, Marketplace.BLIBLI],
    )

    assert [i["marketplace"] for i in found["items"]] == ["tokopedia"]
    assert found["errors"] == [
        {
            "url": found["errors"][0]["url"],
            "error": found["errors"][0]["error"],
            "code": CAPTCHA_REQUIRED,
            "marketplace": "blibli",
        }
    ]
