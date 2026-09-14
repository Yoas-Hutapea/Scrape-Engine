from scrape_engine.detect import Marketplace, canonicalize_product_url, detect_marketplace, is_listing_url, is_product_url
from scrape_engine.scrapers.shopee import parse_shop_item_ids
import pytest


def test_detect_tokopedia():
    assert detect_marketplace("https://www.tokopedia.com/shop/product-name") == Marketplace.TOKOPEDIA


def test_detect_shopee():
    assert detect_marketplace("https://shopee.co.id/abc-i.123.456") == Marketplace.SHOPEE


def test_detect_lazada():
    assert (
        detect_marketplace("https://www.lazada.co.id/products/pdp-i123-s456.html")
        == Marketplace.LAZADA
    )


def test_detect_blibli():
    assert detect_marketplace("https://www.blibli.com/p/nama-produk/is--ABC-123") == Marketplace.BLIBLI


def test_detect_amazon():
    assert detect_marketplace("https://www.amazon.com/dp/B0TESTASIN") == Marketplace.AMAZON
    assert detect_marketplace("https://www.amazon.co.id/dp/B0TESTASIN") == Marketplace.AMAZON


def test_detect_alibaba():
    assert detect_marketplace("https://www.alibaba.com/product-detail/foo_123.html") == Marketplace.ALIBABA
    assert detect_marketplace("https://detail.1688.com/offer/123.html") == Marketplace.ALIBABA


def test_detect_unsupported():
    with pytest.raises(ValueError):
        detect_marketplace("https://example.com/item/1")


def test_parse_shopee_ids():
    assert parse_shop_item_ids("https://shopee.co.id/nama-produk-i.111.222") == ("111", "222")
    assert parse_shop_item_ids("https://shopee.co.id/product/111/222") == ("111", "222")


def test_is_product_url_filters_listing_pages():
    assert is_product_url("https://www.tokopedia.com/shop/router-mikrotik")
    assert not is_product_url("https://www.tokopedia.com/rekomendasi/9341517185")
    assert not is_product_url("https://www.tokopedia.com/find/ruijie-rg-eg209gs")
    assert is_product_url(
        "https://www.tokopedia.com/cen-cctv/rg-eg209gs-router-1731587658/media/product/0"
    )
    assert is_product_url("https://shopee.co.id/Router-i.123.456")
    assert not is_product_url("https://shopee.co.id/search?keyword=router")
    assert is_listing_url("https://www.tokopedia.com/find/baterai-alkaline-aa")
    assert is_listing_url("https://www.tokopedia.com/search?q=baterai")
    assert is_listing_url("https://shopee.co.id/search?keyword=router")
    assert not is_listing_url("https://www.tokopedia.com/shop/router-mikrotik")


def test_canonicalize_strips_tokopedia_media_tail():
    raw = "https://www.tokopedia.com/shop/item-123/media/product/0?utm_source=google"
    clean = canonicalize_product_url(raw)
    assert "/media/product/" not in clean
    assert "utm_source" not in clean
    assert clean.endswith("/shop/item-123") or "/shop/item-123" in clean
