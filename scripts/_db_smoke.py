from scrape_engine.db import connect, insert_rows

row = {
    "Product Name": "DB Smoke Test",
    "Long Description": None,
    "short description": None,
    "Product Source Link": "https://www.tokopedia.com/smoke/test",
    "Variation Name 1": "Ukuran",
    "Variation Option 1": "M",
    "Variation Name 2": None,
    "Variation Option 2": None,
    "Variation Name 3": None,
    "Variation Option 3": None,
    "price": 1000,
    "Discount": 900,
    "Currency": "IDR",
    "Stock": 5,
    "SKU": "SMOKE-1",
    "Package Weight": "0.1",
    "Package Length": None,
    "Package Width": None,
    "Package Height": None,
    "Product Image 1": None,
}
batch, n = insert_rows([row], scrape_batch_id="smoke_test")
print("inserted", batch, n)
with connect() as c:
    with c.cursor() as cur:
        cur.execute(
            "SELECT product_name, sku, marketplace FROM scraped_products WHERE scrape_batch_id=%s",
            (batch,),
        )
        print(cur.fetchone())
