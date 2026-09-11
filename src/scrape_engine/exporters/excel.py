from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook

from scrape_engine.models import EXCEL_HEADERS


def export_xlsx(rows: list[dict[str, Any]], path: str | Path) -> Path:
    """Write BigSeller-compatible scraped product XLSX."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "sheet"
    ws.append(EXCEL_HEADERS)

    for row in rows:
        ws.append([row.get(h) for h in EXCEL_HEADERS])

    wb.save(out)
    return out
