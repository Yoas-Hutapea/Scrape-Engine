from scrape_engine.scrapers.tokopedia import listing_items_from_cache, listing_urls_from_html


def test_listing_items_from_cache():
    cache = {
        "p1": {
            "__typename": "searchProductV5Product",
            "name": "Baterai Alkaline AA",
            "url": "https://www.tokopedia.com/cenglistore/baterai-alkaline-aa-123?extParam=ivf%3Dfalse",
            "price": {"number": 42500, "text": "Rp42.500"},
            "mediaURL": {"image": "https://images.tokopedia.net/file/a.jpg"},
        },
        "skip": {"__typename": "SearchProductV5Shop", "url": "https://www.tokopedia.com/cenglistore"},
    }
    items = listing_items_from_cache(cache, limit=10)
    assert len(items) == 1
    assert items[0]["name"] == "Baterai Alkaline AA"
    assert items[0]["url"] == "https://www.tokopedia.com/cenglistore/baterai-alkaline-aa-123"
    assert items[0]["price"] == 42500.0


def test_listing_urls_from_html_filters_shop_and_find():
    html = """
    <a href="https://www.tokopedia.com/find/baterai-alkaline-aa">find</a>
    <a href="https://www.tokopedia.com/cenglistore">shop</a>
    <a href="https://www.tokopedia.com/cenglistore/baterai-alkaline-abc-aa-kecil-1734900531264718327?extParam=ivf%3Dfalse">pdp</a>
    """
    urls = listing_urls_from_html(html, limit=10)
    assert urls == ["https://www.tokopedia.com/cenglistore/baterai-alkaline-abc-aa-kecil-1734900531264718327"]
