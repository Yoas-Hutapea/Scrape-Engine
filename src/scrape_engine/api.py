from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from scrape_engine.service import ScrapeService

app = FastAPI(title="Scrape Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_service = ScrapeService()


class ExportFormat(str, Enum):
    none = "none"
    json = "json"
    xlsx = "xlsx"
    both = "both"


class ScrapeRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, description="Product URLs")
    format: ExportFormat = ExportFormat.none
    to_db: bool = True
    headed: bool = False
    cdp_url: str | None = Field(
        default=None,
        description="Attach to open Chrome, e.g. http://127.0.0.1:9222",
    )
    active_tab: bool = Field(
        default=False,
        description="With cdp_url: scrape manually opened product tab (no automated goto)",
    )
    timeout_ms: int = 60_000
    delay_sec: float = 1.0
    out_dir: str = "output"


class ScrapeResponse(BaseModel):
    products: int
    rows: list[dict[str, Any]]
    errors: list[dict[str, str]]
    xlsx_path: str | None = None
    json_path: str | None = None
    db_batch_id: str | None = None
    db_inserted: int = 0


@app.on_event("startup")
def _startup() -> None:
    try:
        from scrape_engine.db import init_db

        init_db()
    except Exception:
        # DB may be offline at boot; scrape with to_db will surface the error
        pass


@app.get("/health")
def health() -> dict[str, Any]:
    db_ok = False
    try:
        from scrape_engine.db import ping

        db_ok = ping()
    except Exception:
        db_ok = False
    return {"status": "ok", "database": db_ok}


@app.post("/scrape", response_model=ScrapeResponse)
def scrape(body: ScrapeRequest) -> Any:
    if body.to_db:
        try:
            from scrape_engine.db import init_db

            init_db()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    result = _service.scrape_and_export(
        body.urls,
        out_dir=body.out_dir,
        fmt=body.format.value,  # type: ignore[arg-type]
        headed=body.headed,
        timeout_ms=body.timeout_ms,
        delay_sec=body.delay_sec,
        cdp_url=body.cdp_url,
        active_tab=body.active_tab,
        to_db=body.to_db,
    )

    if body.format == ExportFormat.xlsx and result.xlsx_path and not result.errors:
        return FileResponse(
            path=str(result.xlsx_path),
            filename=result.xlsx_path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if not result.rows and result.errors:
        raise HTTPException(status_code=502, detail=result.errors)

    return ScrapeResponse(
        products=len(result.products),
        rows=_service.rows_payload(result.rows),
        errors=result.errors,
        xlsx_path=str(result.xlsx_path) if result.xlsx_path else None,
        json_path=str(result.json_path) if result.json_path else None,
        db_batch_id=result.db_batch_id,
        db_inserted=result.db_inserted,
    )


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": "Scrape Engine",
            "endpoints": {"health": "GET /health", "scrape": "POST /scrape"},
        }
    )
