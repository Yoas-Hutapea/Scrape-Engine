from scrape_engine.db.schema import HEADER_TO_COLUMN
from scrape_engine.models import EXCEL_HEADERS, Product, Variant, flatten_product


def test_row_map_covers_excel_headers():
    assert list(HEADER_TO_COLUMN.keys()) == EXCEL_HEADERS


def test_flatten_still_works_for_db_pipeline():
    product = Product(
        name="P",
        source_link="https://www.tokopedia.com/a/b",
        variants=[Variant(options=[("Ukuran", "M")], price=1, stock=2)],
    )
    rows = flatten_product(product)
    assert rows[0]["Product Name"] == "P"
    assert len(rows[0]) == len(EXCEL_HEADERS)
