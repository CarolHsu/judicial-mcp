"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path


# Ingestion steps (e.g. OCR and a re-extract) may write concurrently; wait for locks instead of failing.
BUSY_TIMEOUT_S = 60.0


class DatabaseMissingError(FileNotFoundError):
    """Raised when the server is started before any data has been crawled."""


def connect(db_path: Path, *, create: bool = True, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        if not db_path.exists():
            raise DatabaseMissingError(
                f"database not found at {db_path}; run `judicial-mcp crawl` first or set JUDICIAL_MCP_DATA"
            )
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False, timeout=BUSY_TIMEOUT_S)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=BUSY_TIMEOUT_S)
        if create:
            conn.executescript(files("judicial_mcp.db").joinpath("schema.sql").read_text(encoding="utf-8"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
