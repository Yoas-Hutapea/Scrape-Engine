from scrape_engine.detect import Marketplace, is_listing_url, is_product_url
from scrape_engine.scrapers.listing import listing_product_urls_from_html
from scrape_engine.search_urls import all_listing_urls, keyword_listing_url, keyword_slug
from scrape_engine.scrapers.shopee import map_search_items


def test_keyword_slug_and_listing_urls():
    assert keyword_slug("Baterai Alkaline AA") == "baterai-alkaline-aa"
    urls = all_listing_urls("Baterai Alkaline AA")
    assert Marketplace.AMAZON not in urls
    assert set(urls) == {
        Marketplace.TOKOPEDIA,
        Marketplace.SHOPEE,
        Marketplace.BLIBLI,
        Marketplace.ALIBABA,
    }
    assert urls[Marketplace.TOKOPEDIA] == "https://www.tokopedia.com/find/baterai-alkaline-aa"
    assert "keyword=Baterai+Alkaline+AA" in urls[Marketplace.SHOPEE]
    assert "/cari/baterai-alkaline-aa" in urls[Marketplace.BLIBLI]
    assert "SearchText=Baterai+Alkaline+AA" in urls[Marketplace.ALIBABA]
    for marketplace, url in urls.items():
        assert is_listing_url(url), f"{marketplace}: {url}"
        assert keyword_listing_url("Baterai Alkaline AA", marketplace) == url


def test_listing_href_harvest_keeps_top_product_urls():
    html = """
    <a href="/find/baterai-alkaline-aa">listing</a>
    <a href="https://www.tokopedia.com/shop-a/baterai-aa-1">one</a>
    <a href="/shop-b/baterai-aa-2">two</a>
    <a href="https://www.lazada.co.id/products/baterai-i123-s456.html">other market</a>
    <a href="https://www.tokopedia.com/shop-c/baterai-aa-3">three</a>
    """
    urls = listing_product_urls_from_html(
        html,
        base_url="https://www.tokopedia.com/find/baterai-alkaline-aa",
        limit=10,
    )
    assert urls == [
        "https://www.tokopedia.com/shop-a/baterai-aa-1",
        "https://www.tokopedia.com/shop-b/baterai-aa-2",
        "https://www.tokopedia.com/shop-c/baterai-aa-3",
    ]


def test_listing_href_harvest_other_marketplaces():
    html = """
    <a href="https://www.lazada.co.id/products/baterai-i111-s222.html">lazada</a>
    <a href="https://www.blibli.com/p/baterai/is--ABC-1">blibli</a>
    <a href="https://www.amazon.co.id/Baterai/dp/B0TESTASIN">amazon</a>
    <a href="https://www.alibaba.com/product-detail/foo_123.html">alibaba</a>
    <a href="https://shopee.co.id/Baterai-i.11.22">shopee</a>
    """
    assert listing_product_urls_from_html(
        html, base_url="https://www.blibli.com/cari/baterai", limit=5
    ) == ["https://www.blibli.com/p/baterai/is--ABC-1"]
    assert listing_product_urls_from_html(
        html, base_url="https://www.amazon.co.id/s?k=baterai", limit=5
    ) == ["https://www.amazon.co.id/Baterai/dp/B0TESTASIN"]
    assert listing_product_urls_from_html(
        html, base_url="https://www.alibaba.com/trade/search?SearchText=baterai", limit=5
    ) == ["https://www.alibaba.com/product-detail/foo_123.html"]
    assert listing_product_urls_from_html(
        html, base_url="https://shopee.co.id/search?keyword=baterai", limit=5
    ) == ["https://shopee.co.id/Baterai-i.11.22"]


def test_map_search_items_can_keep_api_order():
    items = [
        {"item_basic": {"name": "Mahal", "price": 50_000_000_000, "shopid": 1, "itemid": 11}},
        {"item_basic": {"name": "Murah", "price": 10_000_000_000, "shopid": 2, "itemid": 22}},
    ]
    mapped = map_search_items(items, limit=2, sort_by_price=False)
    assert [row["name"] for row in mapped] == ["Mahal", "Murah"]


def test_is_product_url_still_filters_search_pages():
    assert not is_product_url("https://www.tokopedia.com/find/baterai-alkaline-aa")
    assert is_product_url("https://www.tokopedia.com/shop-a/baterai-aa-1")
