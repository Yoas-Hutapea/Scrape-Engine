from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from scrape_engine.models import Product

log = logging.getLogger(__name__)

# Used only if live FX APIs are unreachable. Override with USD_IDR_RATE in .env.
DEFAULT_USD_IDR = 16250.0
CACHE_TTL_SEC = 60 * 60
_IDR_CODES = frozenset({"IDR", "RP", "RUPIAH"})

_rates_cache: tuple[float, dict[str, float]] | None = None


def _load_dotenv() -> None:
    from scrape_engine.db.settings import _load_dotenv as load_env

    load_env()


def fallback_usd_idr() -> float:
    _load_dotenv()
    raw = (os.getenv("USD_IDR_RATE") or "").strip()
    if raw:
        try:
            value = float(raw.replace(",", "."))
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_USD_IDR


def _parse_usd_rates(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("rates")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        code = str(key or "").upper().strip()
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if code and amount > 0:
            out[code] = amount
    return out


def fetch_usd_rates(*, force: bool = False) -> dict[str, float]:
    """Return FX rates quoted as 1 USD = X <currency>, cached for an hour."""
    global _rates_cache
    now = time.time()
    if not force and _rates_cache and now - _rates_cache[0] < CACHE_TTL_SEC:
        return _rates_cache[1]

    endpoints = (
        "https://open.er-api.com/v6/latest/USD",
        "https://api.frankfurter.app/latest?from=USD&to=IDR,CNY",
    )
    rates: dict[str, float] = {}
    for url in endpoints:
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                rates = _parse_usd_rates(resp.json())
            if rates.get("IDR"):
                _rates_cache = (now, rates)
                return rates
        except Exception as exc:
            log.warning("FX fetch failed (%s): %s", url, exc)

    rates = {"IDR": fallback_usd_idr()}
    _rates_cache = (now, rates)
    return rates


def rate_to_idr(currency: str, usd_rates: dict[str, float] | None = None) -> float | None:
    code = (currency or "").upper().strip()
    if not code or code in _IDR_CODES:
        return 1.0
    rates = usd_rates if usd_rates is not None else fetch_usd_rates()
    idr = float(rates.get("IDR") or fallback_usd_idr())
    if code == "USD":
        return idr
    other = rates.get(code)
    if other and other > 0:
        return idr / other
    return None


def convert_amount_to_idr(
    amount: float | None,
    currency: str,
    *,
    usd_rates: dict[str, float] | None = None,
) -> float | None:
    if amount is None:
        return None
    rate = rate_to_idr(currency, usd_rates)
    if rate is None:
        return amount
    return round(float(amount) * rate)


def product_prices_to_idr(product: Product) -> Product:
    """Convert product + variant prices in-place to IDR."""
    rates = fetch_usd_rates()
    product_ccy = product.currency or "USD"
    product.price = convert_amount_to_idr(product.price, product_ccy, usd_rates=rates)
    product.discount = convert_amount_to_idr(product.discount, product_ccy, usd_rates=rates)
    product.currency = "IDR"
    for variant in product.variants:
        variant_ccy = variant.currency or product_ccy
        variant.price = convert_amount_to_idr(variant.price, variant_ccy, usd_rates=rates)
        variant.discount = convert_amount_to_idr(variant.discount, variant_ccy, usd_rates=rates)
        variant.currency = "IDR"
    return product
