from __future__ import annotations

from abc import ABC, abstractmethod

from scrape_engine.models import Product


class BaseScraper(ABC):
    """Marketplace product scraper."""

    @abstractmethod
    def scrape(
        self, url: str, *, headed: bool = False, timeout_ms: int = 60_000, cdp_url: str | None = None,
        active_tab: bool = False,
    ) -> Product:
        raise NotImplementedError
