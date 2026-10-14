import shutil
from pathlib import Path

import httpx
import pytest

from judicial_mcp import pipeline
from judicial_mcp.config import Settings
from judicial_mcp.db import search
from judicial_mcp.db.connection import connect
from judicial_mcp.http import FetchError, PoliteClient
from judicial_mcp.models import PageText
from judicial_mcp.pdf.extract import METHOD_OCR

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Stands in for PoliteClient: serves fixtures, records calls."""

    def __init__(self, broken_ids: frozenset[int] = frozenset()):
        self.broken_ids = broken_ids
        self.downloads: list[str] = []

    def get_text(self, url: str) -> str:
        if "judcurrentNew1" in url:
            return (FIXTURES / "listing_page1.html").read_text(encoding="utf-8")
        return (FIXTURES / "detail_309577.html").read_text(encoding="utf-8")

    def download(self, url: str, dest: Path) -> tuple[str, int]:
        self.downloads.append(url)
        doc_id = int(url.rsplit("=", 1)[1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if doc_id in self.broken_ids:
            dest.write_bytes(b"<html>error</html>")
        else:
            shutil.copy(FIXTURES / "position_table.pdf", dest)
        return "application/pdf", dest.stat().st_size


@pytest.fixture()
def settings(tmp_path):
    return Settings(data_dir=tmp_path, request_delay_s=0, max_retries=2, timeout_s=5)


def test_discover_ids_stops_when_no_new_ids():
    assert len(pipeline.discover_ids(FakeClient())) == 59


def test_crawl_download_extract(settings):
    conn = connect(settings.db_path)
    report = pipeline.crawl(conn, settings, FakeClient(), limit=1)
    assert report == {"judgments": 1, "failed": []}
    assert len(list(settings.raw_html_dir.glob("*.html"))) == 1

    client = FakeClient(broken_ids=frozenset({473763}))
    downloaded = pipeline.download(conn, settings, client, limit=4)
    assert downloaded == {"downloaded": 3, "failed": 1}
    status = dict(conn.execute("SELECT id, status FROM documents WHERE id = 473763").fetchone())
    assert status["status"] == "failed"
    assert not any("473794" in u for u in client.downloads)  # scanned original skipped

    extracted = pipeline.extract(conn, settings)
    assert extracted["extracted"] == 3
    conn.close()


def test_crawl_records_failures(settings):
    class Failing(FakeClient):
        def get_text(self, url: str) -> str:
            if "docdata" in url:
                raise FetchError("boom")
            return super().get_text(url)

    conn = connect(settings.db_path)
    report = pipeline.crawl(conn, settings, Failing(), limit=2)
    assert report["judgments"] == 0 and len(report["failed"]) == 2


def test_ocr_fills_pending_pages_and_updates_index(mutable_db, monkeypatch):
    conn = connect(mutable_db.db_path)
    conn.execute("UPDATE pages SET method='pending_ocr', text='' WHERE doc_id=473788 AND page_no=1")
    conn.commit()

    def fake_ocr(path, page_numbers):
        return tuple(PageText(page_no=n, text="辨識出來的獨特測試字串", method=METHOD_OCR, confidence=0.9) for n in page_numbers)

    monkeypatch.setattr("judicial_mcp.pdf.ocr.ocr_pages", fake_ocr)
    monkeypatch.setattr("judicial_mcp.pdf.ocr.ocr_available", lambda: True)
    progress = []
    result = pipeline.ocr(conn, mutable_db, progress=lambda d, t: progress.append((d, t)))
    assert result == {"ocr_pages": 1, "total_candidates": 1}
    assert progress == [(1, 1)]
    assert search.search_pages(conn, "獨特測試字串")[0]["doc_id"] == 473788
    conn.close()


def test_ocr_keeps_better_site_text():
    site = "這是一段很長的網站OCR文字" * 5
    assert not pipeline._is_improvement(PageText(1, "短", METHOD_OCR), site)
    assert pipeline._is_improvement(PageText(1, site + "更多", METHOD_OCR), site)
    assert pipeline._is_improvement(PageText(1, "", METHOD_OCR), "")


def test_polite_client_retries_then_succeeds(settings, tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        if request.url.path.endswith("download.aspx"):
            return httpx.Response(200, content=b"%PDF-1.7 data", headers={"content-type": "application/pdf"})
        return httpx.Response(200, text="<html>ok</html>")

    with PoliteClient(settings, transport=httpx.MockTransport(handler)) as client:
        assert client.get_text("https://example.test/page") == "<html>ok</html>"
        dest = tmp_path / "f" / "1.pdf"
        content_type, size = client.download("https://example.test/download/download.aspx?id=1", dest)
    assert calls["n"] == 3
    assert (content_type, size) == ("application/pdf", 13)
    assert dest.read_bytes().startswith(b"%PDF")
    assert not dest.with_suffix(".pdf.part").exists()


def test_polite_client_gives_up(settings):
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    with PoliteClient(settings, transport=transport) as client, pytest.raises(FetchError):
        client.get_text("https://example.test/x")


def test_recrawl_recomputes_status_of_unprocessed_docs(settings):
    from judicial_mcp.db import store
    from judicial_mcp.models import AttachmentRef
    from judicial_mcp.parse.classify import classify

    conn = connect(settings.db_path)
    pipeline.crawl(conn, settings, FakeClient(), limit=1)
    jid = conn.execute("SELECT id FROM judgments").fetchone()[0]
    original = classify(AttachmentRef(1, "公開之卷內文書", "g", "某聲請書", "pdf"))
    store.upsert_documents(conn, jid, [original], {})
    assert conn.execute("SELECT status FROM documents WHERE id = 1").fetchone()[0] == "pending"
    twin = classify(AttachmentRef(2, "公開之卷內文書", "g", "某聲請書_OCR", "pdf"))
    store.upsert_documents(conn, jid, [original, twin], {1: 2})
    assert conn.execute("SELECT status FROM documents WHERE id = 1").fetchone()[0] == "skipped"


def test_crawl_survives_duplicate_case_no(settings):
    conn = connect(settings.db_path)
    report = pipeline.crawl(conn, settings, FakeClient(), limit=2)  # both ids serve the same 字號
    assert report["judgments"] == 1 and len(report["failed"]) == 1


def test_extract_failure_is_not_retried_by_download(settings):
    conn = connect(settings.db_path)
    pipeline.crawl(conn, settings, FakeClient(), limit=1)
    pipeline.download(conn, settings, FakeClient(), limit=1)
    (doc_id, path) = conn.execute("SELECT id, file_path FROM documents WHERE status='downloaded'").fetchone()
    (settings.data_dir / path).write_bytes(b"%PDF-broken")
    pipeline.extract(conn, settings)
    assert conn.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()[0] == "extract_failed"
    client = FakeClient()
    pipeline.download(conn, settings, client)
    assert not any(str(doc_id) in u for u in client.downloads)


def test_ocr_unavailable_raises(built_db, monkeypatch):
    from judicial_mcp.pdf.ocr import OcrUnavailableError

    monkeypatch.setattr("judicial_mcp.pdf.ocr.ocr_available", lambda: False)
    conn = connect(built_db.db_path)
    with pytest.raises(OcrUnavailableError):
        pipeline.ocr(conn, built_db)


def test_download_aborts_when_transfer_exceeds_deadline(settings, tmp_path):
    import time as _time

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"%PDF"
            _time.sleep(0.3)
            yield b"more"

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream()))
    dest = tmp_path / "slow.pdf"
    with PoliteClient(settings, transport=transport, max_download_s=0.1) as client, pytest.raises(FetchError):
        client.download("https://example.test/download.aspx?id=1", dest)
    assert not dest.exists()
    assert not dest.with_suffix(".pdf.part").exists()


def test_extract_redo_keeps_our_ocr_pages(mutable_db):
    conn = connect(mutable_db.db_path)
    conn.execute("UPDATE pages SET text='我們的OCR結果', method='ocr', confidence=0.9 WHERE doc_id=473763 AND page_no=2")
    conn.execute("UPDATE pages SET text='舊的文字' WHERE doc_id=473763 AND page_no=3")
    conn.commit()
    result = pipeline.extract(conn, mutable_db, redo=True)
    assert result["extracted"] == 3
    rows = dict(conn.execute("SELECT page_no, text FROM pages WHERE doc_id=473763 AND page_no IN (2, 3)").fetchall())
    assert rows[2] == "我們的OCR結果"
    assert rows[3] != "舊的文字"
    conn.close()


def test_reparse_reclassifies_from_saved_html(settings):
    conn = connect(settings.db_path)
    pipeline.crawl(conn, settings, FakeClient(), limit=1)
    conn.execute("UPDATE documents SET justice = NULL, status = 'extracted' WHERE doc_type = 'opinion'")
    conn.commit()
    assert pipeline.reparse(conn, settings) == {"judgments": 1, "failed": []}
    rows = conn.execute("SELECT justice, status FROM documents WHERE doc_type = 'opinion'").fetchall()
    assert rows and all(r["justice"] for r in rows)
    assert all(r["status"] == "extracted" for r in rows)  # progress is preserved
