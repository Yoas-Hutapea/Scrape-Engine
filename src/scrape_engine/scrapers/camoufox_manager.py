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


def load_fingerprint_config(path: Path) -> dict[str, Any] | None:
    """Read the saved Camoufox fingerprint config (``CAMOU_CONFIG_*``).

    Older fingerprint.json files hold the full ``launch_options()`` output, which is
    machine-specific (executable_path, headless, the whole host env). Only the
    fingerprint config is portable, so that is all we take from them.
    """
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(saved, dict) or not saved:
        return None
    if isinstance(saved.get("config"), dict):
        return saved["config"]
    return _config_from_env(saved.get("env") or {})


def _config_from_env(env: dict[str, Any]) -> dict[str, Any] | None:
    keys = sorted(
        (k for k in env if k.startswith("CAMOU_CONFIG_") and k.rsplit("_", 1)[1].isdigit()),
        key=lambda k: int(k.rsplit("_", 1)[1]),
    )
    if not keys:
        return None
    try:
        config = json.loads("".join(str(env[k]) for k in keys))
    except Exception:
        return None
    return config if isinstance(config, dict) and config else None


def fingerprint_os(config: dict[str, Any]) -> Literal["windows", "macos", "linux"] | None:
    platform_name = str(config.get("navigator.platform") or "").lower()
    if platform_name.startswith("win"):
        return "windows"
    if platform_name.startswith("mac"):
        return "macos"
    if platform_name.startswith("linux"):
        return "linux"
    return None


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
        self._owner: int | None = None

    def get_context(self, *, headed: bool | None = None) -> Any:
        with self._lock:
            owner = threading.get_ident()
            if self._context is not None and self._owner != owner:
                self._shutdown_locked()
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
            # Reuse the fingerprint the Shopee session was created with; the executable,
            # headless mode and display are always resolved fresh for this machine.
            config = load_fingerprint_config(fingerprint_path) if fingerprint_path.is_file() else None
            if not config:
                config = self._new_fingerprint_config(target_os)
                if config:
                    fingerprint_path.write_text(json.dumps({"config": config}), encoding="utf-8")
            if config:
                launch_kwargs["config"] = config
                launch_kwargs["os"] = fingerprint_os(config) or target_os
                launch_kwargs["i_know_what_im_doing"] = True

            self._cm = Camoufox(**launch_kwargs)
            self._context = self._cm.__enter__()
            self._owner = owner
            return self._context

    @staticmethod
    def _new_fingerprint_config(target_os: str) -> dict[str, Any] | None:
        try:
            from camoufox.utils import launch_options

            opts = launch_options(os=target_os, locale="id-ID")
            return _config_from_env(opts.get("env") or {})
        except Exception:
            return None

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
            self._shutdown_locked()

    def _shutdown_locked(self) -> None:
        if self._cm is not None:
            try:
                self._cm.__exit__(None, None, None)
            except Exception:
                pass
        self._cm = None
        self._context = None
        self._owner = None

    @property
    def is_open(self) -> bool:
        return self._context is not None


camoufox_manager = CamoufoxManager()
atexit.register(camoufox_manager.close)
