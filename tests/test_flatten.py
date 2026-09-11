from scrape_engine.models import EXCEL_HEADERS, Product, Variant, flatten_product


def test_flatten_matches_header_count():
    product = Product(
        name="Test Product",
        source_link="https://www.tokopedia.com/shop/item",
        long_description="<p>Hello<br>World</p>",
        short_description="",
        images=[f"https://img/{i}.jpg" for i in range(12)],
        weight="0.5",
        variants=[
            Variant(
                options=[("Ukuran", "30mm")],
                price=99000,
                discount=53900,
                stock=10,
                sku="SKU-1",
                images=["https://img/v1.jpg"],
            ),
            Variant(
                options=[("Ukuran", "40mm")],
                price=100000,
                discount=60000,
                stock=5,
                sku="SKU-2",
            ),
        ],
    )
    rows = flatten_product(product)
    assert len(rows) == 2
    assert list(rows[0].keys()) == EXCEL_HEADERS
    assert "Product Image 2" not in rows[0]
    assert "Variation Image 1" not in rows[0]
    assert rows[0]["Product Name"] == "Test Product"
    assert rows[0]["Variation Name 1"] == "Ukuran"
    assert rows[0]["Variation Option 1"] == "30mm"
    assert rows[0]["price"] == 99000
    assert rows[0]["Discount"] == 53900
    assert rows[0]["Product Image 1"].endswith("0.jpg")
    assert rows[1]["SKU"] == "SKU-2"
    assert rows[0]["short description"]


def test_flatten_no_variants_makes_one_row():
    product = Product(
        name="Solo",
        source_link="https://shopee.co.id/x-i.1.2",
        price=1000,
        stock=3,
        sku="A",
    )
    rows = flatten_product(product)
    assert len(rows) == 1
    assert rows[0]["SKU"] == "A"
    assert rows[0]["price"] == 1000
