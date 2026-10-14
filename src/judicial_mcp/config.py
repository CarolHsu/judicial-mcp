"""Paths and crawl settings, overridable via environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://cons.judicial.gov.tw"
JUDGMENT_FID = 38
LISTING_PATH = "/judcurrentNew1.aspx"
DETAIL_PATH = "/docdata.aspx"
DOWNLOAD_PATH = "/download/download.aspx"
USER_AGENT = "judicial-mcp/0.1 (+research; polite crawler)"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    request_delay_s: float
    max_retries: int
    timeout_s: float

    @property
    def db_path(self) -> Path:
        return self.data_dir / "judicial.db"

    @property
    def raw_html_dir(self) -> Path:
        return self.data_dir / "raw" / "html"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "raw" / "files"


def _default_data_dir() -> Path:
    env = os.environ.get("JUDICIAL_MCP_DATA")
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "data").resolve()


def load_settings() -> Settings:
    return Settings(
        data_dir=_default_data_dir(),
        request_delay_s=float(os.environ.get("JUDICIAL_MCP_DELAY", "1.0")),
        max_retries=int(os.environ.get("JUDICIAL_MCP_RETRIES", "3")),
        timeout_s=float(os.environ.get("JUDICIAL_MCP_TIMEOUT", "120")),
    )


def detail_url(judgment_id: int) -> str:
    return f"{BASE_URL}{DETAIL_PATH}?fid={JUDGMENT_FID}&id={judgment_id}"


def listing_url(page: int) -> str:
    return f"{BASE_URL}{LISTING_PATH}?fid={JUDGMENT_FID}&page={page}&tab=1"


def download_url(doc_id: int) -> str:
    return f"{BASE_URL}{DOWNLOAD_PATH}?id={doc_id}"
