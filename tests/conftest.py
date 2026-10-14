import hashlib
import shutil
from pathlib import Path

import pytest

from judicial_mcp import pipeline
from judicial_mcp.config import Settings
from judicial_mcp.db import store
from judicial_mcp.db.connection import connect

FIXTURES = Path(__file__).parent / "fixtures"
JUDGMENT_ID = 309577
FIXTURE_PDFS = {473763: "opinion.pdf", 473788: "position_table.pdf", 473800: "oral_brief_ocr.pdf"}


@pytest.fixture(scope="session")
def built_db(tmp_path_factory) -> Settings:
    """A database built through the real pipeline from saved fixtures (no network)."""
    data_dir = tmp_path_factory.mktemp("data")
    settings = Settings(data_dir=data_dir, request_delay_s=0, max_retries=1, timeout_s=5)
    conn = connect(settings.db_path)
    html = (FIXTURES / "detail_309577.html").read_text(encoding="utf-8")
    pipeline.ingest_detail(conn, html, JUDGMENT_ID)
    for doc_id, name in FIXTURE_PDFS.items():
        dest = settings.pdf_dir / str(JUDGMENT_ID) / f"{doc_id}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / name, dest)
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        store.mark_downloaded(conn, doc_id, str(dest.relative_to(data_dir)), sha, dest.stat().st_size)
    pipeline.extract(conn, settings)
    store.rebuild_index(conn)
    conn.close()
    return settings


@pytest.fixture()
def conn(built_db):
    connection = connect(built_db.db_path, readonly=True)
    yield connection
    connection.close()


@pytest.fixture()
def mutable_db(built_db, tmp_path) -> Settings:
    """A private copy of the built database (and its files) for tests that modify data."""
    data_dir = tmp_path / "data"
    shutil.copytree(built_db.data_dir, data_dir)
    return Settings(data_dir=data_dir, request_delay_s=0, max_retries=1, timeout_s=5)
