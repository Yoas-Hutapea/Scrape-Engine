from scrape_engine.scrapers.common import parse_money, product_from_meta_and_ld


def test_parse_money_idr_and_usd():
    assert parse_money("Rp53.900") == 53900
    assert parse_money("$12.99") == 12.99
    assert parse_money("1,234.50") == 1234.50


def test_product_from_meta_and_ld_minimal():
    html = """
    <meta property="og:title" content="Sample Cable | Blibli"/>
    <meta property="og:description" content="Fast charging cable"/>
    <meta property="og:image" content="https://img.example/a.jpg"/>
    <meta property="og:url" content="https://www.blibli.com/p/sample-cable/is--ABC-1"/>
    <script type="application/ld+json">
    {"@type":"Product","name":"Sample Cable","offers":{"@type":"Offer","price":"99000","priceCurrency":"IDR"}}
    </script>
    """
    product = product_from_meta_and_ld(html, "https://www.blibli.com/p/sample-cable/is--ABC-1")
    assert product is not None
    assert product.name == "Sample Cable"
    assert product.images[0].endswith("a.jpg")
    assert product.variants[0].price == 99000
    assert product.currency == "IDR"
