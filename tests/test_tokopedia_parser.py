from scrape_engine.scrapers.tokopedia import product_from_tokopedia_cache


def test_product_from_minimal_tokopedia_cache():
    cache = {
        "pdpBasicInfo1": {
            "__typename": "pdpBasicInfo",
            "url": "https://www.tokopedia.com/shop/item",
            "weight": 0.2,
            "description": "Deskripsi produk",
            "defaultMediaURL": "https://images.tokopedia.net/img/a.jpg",
        },
        "variantData": {
            "__typename": "pdpDataProductVariant",
            "variants": [
                {
                    "name": "ukuran",
                    "option": [
                        {
                            "value": "M",
                            "picture": {"url": "https://images.tokopedia.net/img/v.jpg"},
                        }
                    ],
                }
            ],
        },
        "child1": {
            "__typename": "pdpProductVariantChildren",
            "productName": "Kaos Polos - M",
            "optionName": {"type": "json", "json": ["M"]},
            "price": 15000,
            "slashPriceFmt": "Rp20.000",
            "stock": {"stock": "9"},
            "campaignInfo": {"originalPrice": 20000, "discountPrice": 15000},
            "picture": {"url": "https://images.tokopedia.net/img/v.jpg"},
        },
    }
    product = product_from_tokopedia_cache(cache, "https://www.tokopedia.com/shop/item")
    assert product.name == "Kaos Polos"
    assert len(product.variants) == 1
    assert product.variants[0].options == [("Ukuran", "M")]
    assert product.variants[0].price == 20000
    assert product.variants[0].discount == 15000
    assert product.variants[0].stock == 9


def test_product_from_snapshot_price_when_no_variant_children():
    cache = {
        "pdpBasicInfo1": {
            "__typename": "pdpBasicInfo",
            "url": "https://www.tokopedia.com/shop/item",
            "weight": 0.25,
            "ttsSKUID": "sku-1",
            "alias": "baterai-aa-kecil-123",
        },
        "price1": {
            "__typename": "pdpContentSnapshotPrice",
            "value": 2500,
            "priceFmt": "Rp2.500",
            "slashPriceFmt": "Rp42.500",
        },
        "stock1": {"__typename": "pdpContentSnapshotStock", "value": "7"},
    }
    html = '<meta property="og:title" content="Baterai AA | Tokopedia">'
    product = product_from_tokopedia_cache(cache, "https://www.tokopedia.com/shop/item", html=html)
    assert product.name == "Baterai AA"
    assert product.variants[0].price == 42500
    assert product.variants[0].discount == 2500
    assert product.variants[0].stock == 7
    assert product.variants[0].sku == "sku-1"
