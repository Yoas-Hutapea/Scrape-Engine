from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator

from scrape_engine.detect import Marketplace
from scrape_engine.jobs import JobStore
from scrape_engine.service import ScrapeResult, ScrapeService

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
_jobs = JobStore()


class ExportFormat(str, Enum):
    none = "none"
    json = "json"
    xlsx = "xlsx"
    both = "both"


class ScrapeRequest(BaseModel):
    urls: list[str] = Field(default_factory=list, description="Product or listing URLs")
    keyword: str | None = Field(
        default=None,
        description="If set (and urls empty): search all marketplaces then scrape top N each",
    )
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
        description="Max product PDPs per marketplace listing / keyword search",
    )
    budget_sec: float | None = Field(
        default=None,
        ge=8,
        le=1800,
        description="Wall-clock cap so Shopping List compare returns before the gateway 504s",
    )
    marketplaces: list[str] | None = Field(
        default=None,
        description="Optional marketplace filter, e.g. tokopedia,shopee",
    )

    @model_validator(mode="after")
    def require_urls_or_keyword(self) -> ScrapeRequest:
        urls = [u for u in (self.urls or []) if str(u).strip()]
        keyword = (self.keyword or "").strip()
        if not urls and not keyword:
            raise ValueError("Provide urls or keyword.")
        self.urls = urls
        self.keyword = keyword or None
        return self


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


class MarketplaceSearchRequest(BaseModel):
    q: str = Field(..., min_length=1, description="Product keyword")
    limit: int = Field(default=10, ge=1, le=30)
    timeout_ms: int = 90_000
    headed: bool = False
    marketplaces: list[str] | None = None
    # Wall-clock cap so the website gateway does not return 504 while browsers load.
    budget_sec: float = Field(default=32, ge=8, le=120)


class MarketplaceSearchResponse(BaseModel):
    query: str
    source: str
    items: list[dict[str, Any]]
    errors: list[dict[str, str]]
    listing_urls: list[dict[str, str]]


def _parse_marketplaces(names: list[str] | None) -> list[Marketplace] | None:
    if not names:
        return None
    out: list[Marketplace] = []
    seen: set[str] = set()
    for raw in names:
        key = str(raw or "").strip().lower()
        if not key or key in seen:
            continue
        try:
            out.append(Marketplace(key))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown marketplace: {raw}") from exc
        seen.add(key)
    return out or None


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


@app.post("/search", response_model=MarketplaceSearchResponse)
def search_marketplaces(body: MarketplaceSearchRequest) -> Any:
    query = body.q.strip()
    if not query:
        raise HTTPException(status_code=400, detail='Field "q" is required.')
    result = _service.search_marketplaces(
        query,
        limit=body.limit,
        marketplaces=_parse_marketplaces(body.marketplaces),
        headed=body.headed,
        timeout_ms=body.timeout_ms,
        budget_sec=body.budget_sec,
    )
    return MarketplaceSearchResponse(
        query=str(result.get("query") or query),
        source=str(result.get("source") or "marketplace_search"),
        items=list(result.get("items") or []),
        errors=list(result.get("errors") or []),
        listing_urls=list(result.get("listing_urls") or []),
    )


class ProductListResponse(BaseModel):
    total: int
    filtered: int
    items: list[dict[str, Any]]
    marketplaces: list[str]


@app.get("/products", response_model=ProductListResponse)
def list_products(
    search: str | None = None,
    marketplace: str | None = None,
    start_date: date | None = Query(default=None, description="Inclusive, filters scraped_at"),
    end_date: date | None = Query(default=None, description="Inclusive, filters scraped_at"),
    sort: Literal[
        "scraped_at", "product_name", "marketplace", "price_min", "price_max", "variant_count", "stock"
    ] = "scraped_at",
    dir: Literal["asc", "desc"] = "desc",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
) -> Any:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date.")
    try:
        from scrape_engine.db import list_products as db_list_products

        result = db_list_products(
            search=search,
            marketplace=marketplace,
            start_date=start_date,
            end_date=end_date,
            sort=sort,
            direction=dir,
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return ProductListResponse(**result)


def _execute_scrape(body: ScrapeRequest) -> ScrapeResult:
    marketplaces = _parse_marketplaces(body.marketplaces)
    if body.keyword and not body.urls:
        return _service.search_and_scrape(
            body.keyword,
            listing_limit=body.listing_limit,
            marketplaces=marketplaces,
            headed=body.headed,
            timeout_ms=body.timeout_ms,
            delay_sec=body.delay_sec,
            cdp_url=body.cdp_url,
            active_tab=body.active_tab,
            to_db=body.to_db,
            out_dir=body.out_dir,
            fmt=body.format.value,  # type: ignore[arg-type]
            budget_sec=body.budget_sec,
        )
    return _service.scrape_and_export(
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
        budget_sec=body.budget_sec,
    )


def _scrape_payload(result: ScrapeResult) -> dict[str, Any]:
    return {
        "products": len(result.products),
        "rows": _service.rows_payload(result.rows),
        "errors": result.errors,
        "xlsx_path": str(result.xlsx_path) if result.xlsx_path else None,
        "json_path": str(result.json_path) if result.json_path else None,
        "db_batch_id": result.db_batch_id,
        "db_inserted": result.db_inserted,
    }


def _ensure_db(body: ScrapeRequest) -> None:
    if not body.to_db:
        return
    try:
        from scrape_engine.db import init_db

        init_db()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@app.post("/scrape", response_model=ScrapeResponse)
def scrape(body: ScrapeRequest) -> Any:
    _ensure_db(body)
    result = _execute_scrape(body)

    if body.format == ExportFormat.xlsx and result.xlsx_path and not result.errors:
        return FileResponse(
            path=str(result.xlsx_path),
            filename=result.xlsx_path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if not result.rows and result.errors:
        raise HTTPException(status_code=502, detail=result.errors)

    return ScrapeResponse(**_scrape_payload(result))


class ScrapeJobResponse(BaseModel):
    job_id: str
    status: Literal["running", "done", "error"]
    error: str | None = None
    result: dict[str, Any] | None = None


@app.post("/scrape/jobs", response_model=ScrapeJobResponse)
def start_scrape_job(body: ScrapeRequest) -> ScrapeJobResponse:
    """Start a scrape and return immediately. Poll GET /scrape/jobs/{job_id}."""
    _ensure_db(body)
    job_id = _jobs.start(lambda: _scrape_payload(_execute_scrape(body)))
    return ScrapeJobResponse(job_id=job_id, status="running")


@app.get("/scrape/jobs/{job_id}", response_model=ScrapeJobResponse)
def scrape_job(job_id: str) -> ScrapeJobResponse:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return ScrapeJobResponse(**job)


class VerifyStartRequest(BaseModel):
    marketplace: str = Field(description="shopee | blibli | alibaba")
    url: str | None = Field(
        default=None,
        description="Page that showed the captcha; must belong to the same marketplace",
    )


class VerifySessionResponse(BaseModel):
    session_id: str
    marketplace: str
    url: str
    status: Literal["starting", "waiting", "solved", "expired", "error", "cancelled"]
    message: str | None = None
    created_at: str
    expires_at: str
    timeout_sec: int
    verified_at: str | None = None
    viewer_url: str | None = None


@app.post("/verify/sessions", response_model=VerifySessionResponse)
def start_verification(body: VerifyStartRequest) -> Any:
    """Open a headed window (server display / noVNC) so a person can solve the captcha once."""
    from scrape_engine.verification import VerificationUnavailable, verification_store

    try:
        return verification_store.start(body.marketplace, body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VerificationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/verify/sessions/{session_id}", response_model=VerifySessionResponse)
def verification_session(session_id: str) -> Any:
    from scrape_engine.verification import verification_store

    session = verification_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesi verifikasi tidak ditemukan.")
    return session


@app.post("/verify/sessions/{session_id}/cancel", response_model=VerifySessionResponse)
def cancel_verification(session_id: str) -> Any:
    from scrape_engine.verification import verification_store

    session = verification_store.cancel(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesi verifikasi tidak ditemukan.")
    return session


@app.get("/verify/status")
def verification_status() -> dict[str, Any]:
    """Display availability, noVNC URL and last verification per marketplace."""
    from scrape_engine.verification import verification_store

    return verification_store.status()


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": "Scrape Engine",
            "endpoints": {
                "health": "GET /health",
                "search": "POST /search",
                "scrape": "POST /scrape",
                "scrape_job": "POST /scrape/jobs",
                "products": "GET /products",
                "verify_start": "POST /verify/sessions",
                "verify_session": "GET /verify/sessions/{id}",
                "verify_status": "GET /verify/status",
                "shopee_search": "GET /shopee/search?q=",
                "shopee_session": "GET /shopee/session",
            },
        }
    )
