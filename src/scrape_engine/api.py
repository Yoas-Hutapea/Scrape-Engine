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
    listing_limit: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Max product PDPs to scrape from a /find or /search listing URL",
    )


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


@app.on_event("shutdown")
def _shutdown() -> None:
    try:
        from scrape_engine.scrapers.camoufox_manager import camoufox_manager

        camoufox_manager.close()
    except Exception:
        pass


@app.get("/health")
def health() -> dict[str, Any]:
    db_ok = False
    try:
        from scrape_engine.db import ping

        db_ok = ping()
    except Exception:
        db_ok = False
    shopee = {}
    try:
        from scrape_engine.scrapers.shopee_session import session_status

        shopee = session_status()
    except Exception:
        shopee = {"ready": False}
    return {"status": "ok", "database": db_ok, "shopee_session": shopee}


class ShopeeSearchResponse(BaseModel):
    keyword: str
    reason: str
    items: list[dict[str, Any]]
    error: str | None = None


@app.get("/shopee/search", response_model=ShopeeSearchResponse)
def shopee_search(q: str, limit: int = 3, timeout_ms: int = 60_000) -> Any:
    if not q.strip():
        raise HTTPException(status_code=400, detail='Query parameter "q" is required.')
    result = _service.search_shopee(q, limit=max(1, min(limit, 20)), timeout_ms=timeout_ms)
    items = result.get("items") or []
    reason = str(result.get("reason") or "SCRAPE_ERROR")
    if reason == "EMPTY_RESULTS":
        raise HTTPException(status_code=404, detail=f'Tidak ada produk Shopee untuk "{q}".')
    if reason in {"ANTIBOT", "SCRAPE_ERROR"} and not items:
        raise HTTPException(
            status_code=503,
            detail=result.get("error")
            or "Shopee memblokir pencarian. Jalankan: py -m scrape_engine.cli setup-session",
        )
    return ShopeeSearchResponse(keyword=q.strip(), reason=reason, items=items, error=result.get("error"))


@app.get("/shopee/session")
def shopee_session() -> dict[str, Any]:
    from scrape_engine.scrapers.shopee_session import session_status

    return session_status()


@app.post("/shopee/session/setup")
def shopee_session_setup() -> dict[str, Any]:
    from scrape_engine.scrapers.shopee_session import setup_session

    result = setup_session()
    if not result.get("success"):
        raise HTTPException(status_code=408, detail=result.get("error") or "Setup sesi Shopee gagal.")
    return result


@app.post("/shopee/session/warm")
def shopee_session_warm() -> dict[str, Any]:
    from scrape_engine.scrapers.shopee_session import warm_session

    result = warm_session(keep_open=True)
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error") or "Warm sesi Shopee gagal.")
    return result


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
        listing_limit=body.listing_limit,
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
            "endpoints": {
                "health": "GET /health",
                "scrape": "POST /scrape",
                "shopee_search": "GET /shopee/search?q=",
                "shopee_session": "GET /shopee/session",
            },
        }
    )
