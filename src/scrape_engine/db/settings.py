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


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    database: str
    username: str
    password: str

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.username} password={self.password}"
        )


@lru_cache(maxsize=1)
def get_db_settings() -> DbSettings:
    _load_dotenv()
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "5432"))
    database = os.getenv("DB_DATABASE") or os.getenv("DB_NAME") or "IdeaSearch"
    username = os.getenv("DB_USERNAME") or os.getenv("DB_USER") or "postgres"
    password = os.getenv("DB_PASSWORD") or ""
    return DbSettings(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )
