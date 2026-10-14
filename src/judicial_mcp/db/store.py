"""Write-side operations used by the ingestion pipeline."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from judicial_mcp.config import detail_url, download_url
from judicial_mcp.models import DocumentMeta, Judgment, PageText

STATUS_PENDING = "pending"
STATUS_DOWNLOADED = "downloaded"
STATUS_EXTRACTED = "extracted"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"  # download failed; retried by the next `download`
STATUS_EXTRACT_FAILED = "extract_failed"  # file downloaded but unreadable; not retried automatically

# pages_fts rows use a deterministic rowid so single pages can be replaced without a table scan.
_MAX_PAGES_PER_DOC = 100_000


def page_fts_rowid(doc_id: int, page_no: int) -> int:
    return doc_id * _MAX_PAGES_PER_DOC + page_no

SKIP_HAS_OCR_TWIN = "scanned original; text taken from its _OCR version"
SKIP_DUPLICATE_OF_HTML = "duplicate of the judgment text on the web page"
SKIP_UNSUPPORTED = "unsupported file type"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def upsert_judgment(conn: sqlite3.Connection, judgment: Judgment) -> None:
    """Insert or replace a judgment and its paragraphs, statutes and related cases."""
    with conn:
        conn.execute(
            """
            INSERT INTO judgments (id, case_no, case_name, year, number, original_case_no, decision_date,
                                   petitioner, cause, author_note, source_url, crawled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                case_no=excluded.case_no, case_name=excluded.case_name, year=excluded.year,
                number=excluded.number, original_case_no=excluded.original_case_no,
                decision_date=excluded.decision_date, petitioner=excluded.petitioner, cause=excluded.cause,
                author_note=excluded.author_note, source_url=excluded.source_url, crawled_at=excluded.crawled_at
            """,
            (
                judgment.id, judgment.case_no, judgment.case_name, judgment.year, judgment.number,
                judgment.original_case_no, judgment.decision_date, judgment.petitioner, judgment.cause,
                judgment.author_note, detail_url(judgment.id), _now(),
            ),
        )
        for table in ("paragraphs", "statutes", "related_cases"):
            conn.execute(f"DELETE FROM {table} WHERE judgment_id = ?", (judgment.id,))  # noqa: S608
        conn.executemany(
            "INSERT INTO paragraphs (judgment_id, section, para_no, text) VALUES (?, ?, ?, ?)",
            [(judgment.id, p.section, p.para_no, p.text) for p in judgment.paragraphs],
        )
        conn.executemany(
            "INSERT INTO statutes (judgment_id, ord, text, url) VALUES (?, ?, ?, ?)",
            [(judgment.id, i, s.text, s.url) for i, s in enumerate(judgment.statutes)],
        )
        conn.executemany(
            "INSERT INTO related_cases (judgment_id, ord, case_no, url) VALUES (?, ?, ?, ?)",
            [(judgment.id, i, r.case_no, r.url) for i, r in enumerate(judgment.related_cases)],
        )
        conn.execute("DELETE FROM paragraphs_fts WHERE judgment_id = ?", (judgment.id,))
        conn.executemany(
            "INSERT INTO paragraphs_fts (text, judgment_id, section, para_no) VALUES (?, ?, ?, ?)",
            [(p.text, judgment.id, p.section, p.para_no) for p in judgment.paragraphs],
        )


def _initial_skip(meta: DocumentMeta, twin_id: int | None) -> str | None:
    if twin_id is not None:
        return SKIP_HAS_OCR_TWIN
    if meta.doc_type == "judgment_full":
        return SKIP_DUPLICATE_OF_HTML
    if meta.ext != "pdf":
        return SKIP_UNSUPPORTED
    return None


def upsert_documents(
    conn: sqlite3.Connection, judgment_id: int, metas: Sequence[DocumentMeta], twins: dict[int, int]
) -> None:
    """Insert or refresh document metadata, preserving download/extraction progress."""
    with conn:
        for ord_, meta in enumerate(metas):
            twin_id = twins.get(meta.doc_id)
            skip = _initial_skip(meta, twin_id)
            conn.execute(
                """
                INSERT INTO documents (id, judgment_id, ord, section, grp, title, base_title, ext, doc_type,
                    is_ocr_variant, twin_id, party, justice, opinion_type, filed_date, source_url,
                    status, skip_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    judgment_id=excluded.judgment_id, ord=excluded.ord, section=excluded.section,
                    grp=excluded.grp, title=excluded.title, base_title=excluded.base_title, ext=excluded.ext,
                    doc_type=excluded.doc_type, is_ocr_variant=excluded.is_ocr_variant,
                    twin_id=excluded.twin_id, party=excluded.party, justice=excluded.justice,
                    opinion_type=excluded.opinion_type, filed_date=excluded.filed_date,
                    source_url=excluded.source_url,
                    status=CASE WHEN documents.status IN ('pending', 'skipped')
                                THEN excluded.status ELSE documents.status END,
                    skip_reason=CASE WHEN documents.status IN ('pending', 'skipped')
                                     THEN excluded.skip_reason ELSE documents.skip_reason END
                """,
                (
                    meta.doc_id, judgment_id, ord_, meta.section, meta.group, meta.title, meta.base_title,
                    meta.ext, meta.doc_type, int(meta.is_ocr_variant), twin_id, meta.party, meta.justice,
                    meta.opinion_type, meta.filed_date, download_url(meta.doc_id),
                    STATUS_SKIPPED if skip else STATUS_PENDING, skip,
                ),
            )


def mark_downloaded(conn: sqlite3.Connection, doc_id: int, file_path: str, sha256: str, size: int) -> None:
    with conn:
        conn.execute(
            "UPDATE documents SET status=?, file_path=?, sha256=?, bytes=?, error=NULL WHERE id=?",
            (STATUS_DOWNLOADED, file_path, sha256, size, doc_id),
        )


def mark_failed(conn: sqlite3.Connection, doc_id: int, error: str, status: str = STATUS_FAILED) -> None:
    with conn:
        conn.execute("UPDATE documents SET status=?, error=? WHERE id=?", (status, error[:500], doc_id))


def replace_pages(conn: sqlite3.Connection, doc_id: int, pages: Iterable[PageText]) -> None:
    rows = [(doc_id, p.page_no, p.text, p.method, p.confidence) for p in pages]
    with conn:
        conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
        conn.executemany(
            "INSERT INTO pages (doc_id, page_no, text, method, confidence) VALUES (?, ?, ?, ?, ?)", rows
        )
        conn.execute(
            "UPDATE documents SET status=?, page_count=?, error=NULL WHERE id=?",
            (STATUS_EXTRACTED, len(rows), doc_id),
        )


def update_pages(conn: sqlite3.Connection, doc_id: int, pages: Iterable[PageText]) -> None:
    """Overwrite specific pages (e.g. with OCR output) and keep the FTS index in sync."""
    with conn:
        for p in pages:
            conn.execute(
                "UPDATE pages SET text=?, method=?, confidence=? WHERE doc_id=? AND page_no=?",
                (p.text, p.method, p.confidence, doc_id, p.page_no),
            )
            rowid = page_fts_rowid(doc_id, p.page_no)
            conn.execute("DELETE FROM pages_fts WHERE rowid = ?", (rowid,))
            if p.text:
                conn.execute(
                    "INSERT INTO pages_fts (rowid, text, doc_id, page_no) VALUES (?, ?, ?, ?)",
                    (rowid, p.text, doc_id, p.page_no),
                )


def rebuild_index(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("DELETE FROM paragraphs_fts")
        conn.execute(
            "INSERT INTO paragraphs_fts (text, judgment_id, section, para_no) "
            "SELECT text, judgment_id, section, para_no FROM paragraphs"
        )
        conn.execute("DELETE FROM pages_fts")
        conn.execute(
            "INSERT INTO pages_fts (rowid, text, doc_id, page_no) "
            f"SELECT doc_id * {_MAX_PAGES_PER_DOC} + page_no, text, doc_id, page_no FROM pages WHERE text != ''"
        )
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('indexed_at', ?)", (_now(),))
    conn.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES ('optimize')")
    conn.execute("INSERT INTO pages_fts(pages_fts) VALUES ('optimize')")
    conn.commit()
