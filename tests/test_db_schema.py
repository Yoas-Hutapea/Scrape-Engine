from scrape_engine.db.schema import HEADER_TO_COLUMN, row_to_db_values
from scrape_engine.models import EXCEL_HEADERS


def test_header_mapping_covers_all_excel_headers():
    assert set(HEADER_TO_COLUMN) == set(EXCEL_HEADERS)


def test_row_to_db_values():
    row = {h: None for h in EXCEL_HEADERS}
    row["Product Name"] = "Test"
    row["price"] = 1000
    mapped = row_to_db_values(row)
    assert mapped["product_name"] == "Test"
    assert mapped["price"] == 1000
    assert "product_image_1" in mapped
