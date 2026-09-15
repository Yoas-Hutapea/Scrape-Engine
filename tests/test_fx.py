from scrape_engine.fx import convert_amount_to_idr, product_prices_to_idr
from scrape_engine.models import Product, Variant


def test_convert_usd_and_cny_to_idr():
    rates = {"IDR": 16000.0, "CNY": 7.2}
    assert convert_amount_to_idr(2.5, "USD", usd_rates=rates) == 40000
    assert convert_amount_to_idr(72.0, "CNY", usd_rates=rates) == 160000
    assert convert_amount_to_idr(50000, "IDR", usd_rates=rates) == 50000
    assert convert_amount_to_idr(None, "USD", usd_rates=rates) is None


def test_product_prices_to_idr_converts_variants(monkeypatch):
    monkeypatch.setattr(
        "scrape_engine.fx.fetch_usd_rates",
        lambda **_kwargs: {"IDR": 16000.0, "CNY": 8.0},
    )
    product = Product(
        name="Alibaba Cable",
        source_link="https://www.alibaba.com/product-detail/foo_123.html",
        currency="USD",
        price=1.25,
        variants=[
            Variant(options=[("MOQ", "10")], price=1.25, currency="USD"),
            Variant(options=[("MOQ", "100")], price=0.8, currency="USD"),
        ],
    )
    converted = product_prices_to_idr(product)
    assert converted.currency == "IDR"
    assert converted.price == 20000
    assert [v.price for v in converted.variants] == [20000, 12800]
    assert all(v.currency == "IDR" for v in converted.variants)
