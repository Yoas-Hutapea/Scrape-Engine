from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scrape_engine.models import EXCEL_HEADERS


def rows_as_ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only Excel headers in stable order."""
    return [{h: row.get(h) for h in EXCEL_HEADERS} for row in rows]


def export_json(rows: list[dict[str, Any]], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = rows_as_ordered(rows)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
