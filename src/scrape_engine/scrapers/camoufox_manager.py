from __future__ import annotations

import atexit
import json
import os
import platform
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FINGERPRINT_FILE = "fingerprint.json"
HeadlessMode = bool | Literal["virtual"]


def camoufox_os() -> Literal["windows", "macos", "linux"]:
    raw = os.getenv("SHOPEE_OS", "").strip().lower()
    if raw in {"windows", "macos", "linux"}:
        return raw  # type: ignore[return-value]
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def has_display() -> bool:
    if camoufox_os() in {"windows", "macos"}:
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


def shopee_headless(headed: bool | None = None) -> HeadlessMode:
    """Resolve Camoufox headless mode.

    Linux servers without a desktop use ``virtual`` (Xvfb). Windows/macOS keep a
    real window unless ``SHOPEE_HEADLESS=true``.
    """
    if headed is True:
        return False

    raw = os.getenv("SHOPEE_HEADLESS", "auto").strip().lower()
    if raw in {"0", "false", "no", "headed"}:
        return False
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"virtual", "xvfb"}:
        return "virtual"
    if camoufox_os() == "linux" and not has_display():
        return "virtual"
    return False


def profile_dir() -> Path:
    raw = os.getenv("SHOPEE_PROFILE_DIR", "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else (Path.cwd() / path).resolve()
    return (PROJECT_ROOT / "output" / "shopee-profile").resolve()


def profile_exists() -> bool:
    path = profile_dir()
    if not path.is_dir():
        return False
    return any(path.iterdir())


class CamoufoxManager:
    """Shared persistent Camoufox context (same idea as scrapper-shopee BrowserManager)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cm: Any = None
        self._context: Any = None

    def get_context(self, *, headed: bool | None = None) -> Any:
        with self._lock:
            if self._context is not None:
                return self._context

            try:
                from camoufox.sync_api import Camoufox
            except ImportError as exc:
                raise RuntimeError(
                    "Camoufox belum terpasang. Jalankan: pip install camoufox && python -m camoufox fetch"
                ) from exc

            dest = profile_dir()
            dest.mkdir(parents=True, exist_ok=True)
            fingerprint_path = dest / FINGERPRINT_FILE
            target_os = camoufox_os()
            launch_kwargs: dict[str, Any] = {
                "headless": shopee_headless(headed),
                "persistent_context": True,
                "user_data_dir": str(dest),
                "humanize": True,
                "os": target_os,
                "locale": "id-ID",
                "enable_cache": True,
            }
            if fingerprint_path.is_file():
                try:
                    saved = json.loads(fingerprint_path.read_text(encoding="utf-8"))
                    if isinstance(saved, dict) and saved:
                        launch_kwargs["from_options"] = saved
                except Exception:
                    pass

            self._cm = Camoufox(**launch_kwargs)
            self._context = self._cm.__enter__()
            if not fingerprint_path.is_file():
                self._try_save_fingerprint(fingerprint_path, dest)
            return self._context

    def _try_save_fingerprint(self, path: Path, dest: Path) -> None:
        try:
            from camoufox.utils import launch_options

            opts = launch_options(user_data_dir=str(dest), os=camoufox_os(), locale="id-ID")
            path.write_text(json.dumps(opts, default=str), encoding="utf-8")
        except Exception:
            return

    @contextmanager
    def open_page(self, *, headed: bool | None = None) -> Iterator[tuple[Any, Any]]:
        """Yield ``(page, context)`` and always close the worker page."""
        with self._lock:
            context = self.get_context(headed=headed)
            page = context.new_page()
            try:
                yield page, context
            finally:
                try:
                    page.close()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._cm is not None:
                try:
                    self._cm.__exit__(None, None, None)
                except Exception:
                    pass
            self._cm = None
            self._context = None

    @property
    def is_open(self) -> bool:
        return self._context is not None


camoufox_manager = CamoufoxManager()
atexit.register(camoufox_manager.close)
