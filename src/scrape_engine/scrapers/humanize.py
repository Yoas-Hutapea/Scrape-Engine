from __future__ import annotations

import random
import time
from typing import Any


def human_delay(min_ms: int = 1000, max_ms: int = 3000, page: Any | None = None) -> None:
    """Wait a random interval so navigation looks less scripted."""
    delay = random.randint(min_ms, max_ms)
    if page is not None:
        page.wait_for_timeout(delay)
        return
    time.sleep(delay / 1000)


def simulate_human_mouse(page: Any) -> None:
    """Move the cursor along a few random paths."""
    moves = random.randint(3, 7)
    for _ in range(moves):
        x = random.randint(40, 1000)
        y = random.randint(40, 800)
        page.mouse.move(x, y, steps=10)
        human_delay(200, 700, page)


def simulate_human_scroll(page: Any) -> None:
    """Scroll the page in short bursts, then ease back up."""
    scrolls = random.randint(2, 5)
    for _ in range(scrolls):
        amount = random.randint(200, 600)
        page.mouse.wheel(0, amount)
        human_delay(500, 1500, page)
    page.mouse.wheel(0, -200)


def simulate_human_activity(page: Any, *, rounds: int = 1) -> None:
    for _ in range(max(1, rounds)):
        simulate_human_mouse(page)
        simulate_human_scroll(page)
        human_delay(1000, 2500, page)
