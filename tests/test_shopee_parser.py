from scrape_engine.scrapers.shopee import (
    map_search_items,
    parse_shop_item_ids,
    product_from_crawler_html,
    product_from_dom_snapshot,
)


def test_product_from_crawler_html():
    html = """
    <meta property="og:title" content="Jual Sample Product | Shopee Indonesia"/>
    <meta property="og:description" content="Deskripsi singkat"/>
    <meta property="og:image" content="https://down-id.img.susercontent.com/file/abc"/>
    <meta property="og:url" content="https://shopee.co.id/sample-i.1.2"/>
    <meta property="product:price:amount" content="1250000"/>
    <meta property="product:price:currency" content="IDR"/>
    <script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[{"item":{"name":"Home"}},{"item":{"name":"Sample Product"}}]}</script>
    """
    product = product_from_crawler_html(html, "https://shopee.co.id/sample-i.1.2")
    assert product.name == "Sample Product"
    assert product.images[0].endswith("/abc")
    assert "Deskripsi" in product.short_description
    assert product.variants[0].price == 1250000


def test_parse_ids_exported():
    assert parse_shop_item_ids("https://shopee.co.id/x-i.9.8") == ("9", "8")


def test_map_search_items_sorts_cheapest():
    items = [
        {"item_basic": {"name": "Mahal", "price": 50_000_000_000, "shopid": 1, "itemid": 11}},
        {"item_basic": {"name": "Murah", "price": 10_000_000_000, "shopid": 2, "itemid": 22}},
        {"name": "Sedang", "price": 20_000_000_000, "shopid": 3, "itemid": 33},
    ]
    mapped = map_search_items(items, limit=2)
    assert [row["name"] for row in mapped] == ["Murah", "Sedang"]
    assert mapped[0]["price"] == 100_000
    assert mapped[0]["link"] == "https://shopee.co.id/product/2/22"


def test_product_from_dom_snapshot():
    product = product_from_dom_snapshot(
        {
            "name": "Jual Router WiFi",
            "price_text": "Rp1.250.000",
            "image": "https://down-id.img.susercontent.com/file/abc",
            "description": "Deskripsi router",
            "url": "https://shopee.co.id/router-i.1.2",
        },
        "https://shopee.co.id/router-i.1.2",
    )
    assert product is not None
    assert product.name == "Router WiFi"
    assert product.variants[0].price == 1_250_000
    assert product.images[0].endswith("/abc")


def test_product_from_dom_snapshot_rejects_generic_title():
    assert product_from_dom_snapshot({"name": "Shopee Indonesia"}, "https://shopee.co.id/x") is None
