from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from project root if present (no override of existing env)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    # Walk up from this file to find project .env
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        env_path = parent / ".env"
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            return
    load_dotenv(override=False)


def _parse_sqlsrv_url(url: str) -> dict[str, str]:
    """Parse a Laravel-style DSN, e.g. sqlsrv:Server=host,1433;Database=X;Encrypt=no;"""
    body = url.strip().strip('"').strip("'")
    if ":" in body.split(";", 1)[0]:
        body = body.split(":", 1)[1]
    out: dict[str, str] = {}
    for part in body.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            out[key.strip().lower()] = value.strip()
    return out


def _odbc_quote(value: str) -> str:
    if any(ch in value for ch in ";{}=") or value != value.strip():
        return "{" + value.replace("}", "}}") + "}"
    return value


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    database: str
    username: str
    password: str
    driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: str = "no"
    trust_server_certificate: str = "yes"

    @property
    def dsn(self) -> str:
        """ODBC connection string for pyodbc."""
        parts = {
            "DRIVER": "{" + self.driver + "}",
            "SERVER": f"{self.host},{self.port}",
            "DATABASE": _odbc_quote(self.database),
            "UID": _odbc_quote(self.username),
            "PWD": _odbc_quote(self.password),
            "Encrypt": self.encrypt,
            "TrustServerCertificate": self.trust_server_certificate,
        }
        return ";".join(f"{k}={v}" for k, v in parts.items())


@lru_cache(maxsize=1)
def get_db_settings() -> DbSettings:
    _load_dotenv()
    url = _parse_sqlsrv_url(os.getenv("DB_URL") or "")
    url_host, _, url_port = (url.get("server") or "").partition(",")
    host = os.getenv("DB_HOST") or url_host or "127.0.0.1"
    port = int(os.getenv("DB_PORT") or url_port or "1433")
    database = os.getenv("DB_DATABASE") or os.getenv("DB_NAME") or url.get("database") or "IdeaSearch"
    username = os.getenv("DB_USERNAME") or os.getenv("DB_USER") or url.get("uid") or "sa"
    password = os.getenv("DB_PASSWORD") or url.get("pwd") or ""
    return DbSettings(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        driver=os.getenv("DB_ODBC_DRIVER") or "ODBC Driver 18 for SQL Server",
        encrypt=url.get("encrypt") or "no",
        trust_server_certificate=url.get("trustservercertificate") or "yes",
    )
