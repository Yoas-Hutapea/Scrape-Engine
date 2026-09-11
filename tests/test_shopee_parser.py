from scrape_engine.scrapers.shopee import parse_shop_item_ids, product_from_crawler_html


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
