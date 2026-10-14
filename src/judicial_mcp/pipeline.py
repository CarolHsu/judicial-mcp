"""Ingestion steps: crawl pages, download attachments, extract text, OCR."""

from __future__ import annotations

import hashlib
import logging
import multiprocessing
import sqlite3
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from judicial_mcp.config import Settings, detail_url, download_url, listing_url
from judicial_mcp.db import store
from judicial_mcp.http import FetchError, PoliteClient
from judicial_mcp.models import PageText
from judicial_mcp.parse.classify import classify, pair_ocr_twins
from judicial_mcp.parse.detail import parse_detail
from judicial_mcp.parse.listing import parse_listing
from judicial_mcp.pdf.extract import METHOD_OCR, METHOD_PENDING, PdfOpenError, extract_pages, meaningful_chars

log = logging.getLogger(__name__)

MAX_LISTING_PAGES = 50
OCR_CHUNK_PAGES = 20
_PDF_MAGIC = b"%PDF"


def discover_ids(client: PoliteClient) -> tuple[int, ...]:
    ids: dict[int, None] = {}
    for page in range(1, MAX_LISTING_PAGES + 1):
        found = parse_listing(client.get_text(listing_url(page)))
        new = [i for i in found if i not in ids]
        if not new:
            break
        ids.update(dict.fromkeys(new))
    return tuple(ids)


def ingest_detail(conn: sqlite3.Connection, html: str, judgment_id: int) -> int:
    """Parse one detail page and store it. Returns the number of attachments."""
    judgment = parse_detail(html, judgment_id)
    metas = [classify(a) for a in judgment.attachments]
    store.upsert_judgment(conn, judgment)
    store.upsert_documents(conn, judgment.id, metas, pair_ocr_twins(metas))
    return len(metas)


def crawl(conn: sqlite3.Connection, settings: Settings, client: PoliteClient, *, limit: int | None = None) -> dict:
    ids = discover_ids(client)
    if limit:
        ids = ids[:limit]
    log.info("found %d judgments", len(ids))
    settings.raw_html_dir.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, []
    for judgment_id in ids:
        try:
            html = client.get_text(detail_url(judgment_id))
            (settings.raw_html_dir / f"{judgment_id}.html").write_text(html, encoding="utf-8")
            n = ingest_detail(conn, html, judgment_id)
            ok += 1
            log.info("judgment %d: %d attachments", judgment_id, n)
        except (FetchError, ValueError, sqlite3.IntegrityError) as exc:  # DetailParseError is a ValueError
            log.error("judgment %d failed: %s", judgment_id, exc)
            failed.append(judgment_id)
    return {"judgments": ok, "failed": failed}


def _pending_docs(conn: sqlite3.Connection, statuses: tuple[str, ...], limit: int | None) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(statuses))
    sql = f"SELECT id, judgment_id, file_path, is_ocr_variant FROM documents WHERE status IN ({marks}) ORDER BY judgment_id DESC, ord"  # noqa: S608
    rows = conn.execute(sql, statuses).fetchall()
    return rows[:limit] if limit else rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(conn: sqlite3.Connection, settings: Settings, client: PoliteClient, *, limit: int | None = None) -> dict:
    done, failed = 0, 0
    for row in _pending_docs(conn, (store.STATUS_PENDING, store.STATUS_FAILED), limit):
        doc_id = row["id"]
        dest = settings.pdf_dir / str(row["judgment_id"]) / f"{doc_id}.pdf"
        try:
            if not dest.exists():
                client.download(download_url(doc_id), dest)
            with dest.open("rb") as fh:
                if fh.read(4) != _PDF_MAGIC:
                    raise PdfOpenError("downloaded file is not a PDF")
            store.mark_downloaded(conn, doc_id, str(dest.relative_to(settings.data_dir)), _sha256(dest), dest.stat().st_size)
            done += 1
        except (FetchError, PdfOpenError, OSError) as exc:
            log.error("download %d failed: %s", doc_id, exc)
            store.mark_failed(conn, doc_id, str(exc))
            dest.unlink(missing_ok=True)
            failed += 1
    return {"downloaded": done, "failed": failed}


def extract(conn: sqlite3.Connection, settings: Settings, *, limit: int | None = None, redo: bool = False) -> dict:
    """Extract text layers. With `redo`, re-extract processed documents too (after cleaning-rule
    changes), keeping pages already OCR'd by us so that work is not repeated."""
    statuses = (store.STATUS_DOWNLOADED, store.STATUS_EXTRACTED) if redo else (store.STATUS_DOWNLOADED,)
    done, failed, pending_pages = 0, 0, 0
    for row in _pending_docs(conn, statuses, limit):
        path = settings.data_dir / row["file_path"]
        try:
            pages = _keep_our_ocr(conn, row["id"], extract_pages(path, site_ocr=bool(row["is_ocr_variant"])))
            store.replace_pages(conn, row["id"], pages)
            pending_pages += sum(1 for p in pages if p.method == METHOD_PENDING)
            done += 1
        except (PdfOpenError, OSError) as exc:
            log.error("extract %d failed: %s", row["id"], exc)
            store.mark_failed(conn, row["id"], str(exc), status=store.STATUS_EXTRACT_FAILED)
            failed += 1
    return {"extracted": done, "failed": failed, "pages_needing_ocr": pending_pages}


def _keep_our_ocr(conn: sqlite3.Connection, doc_id: int, fresh: tuple[PageText, ...]) -> tuple[PageText, ...]:
    ocr_rows = conn.execute(
        "SELECT page_no, text, confidence FROM pages WHERE doc_id = ? AND method = ?", (doc_id, METHOD_OCR)
    ).fetchall()
    ours = {r["page_no"]: PageText(r["page_no"], r["text"], METHOD_OCR, r["confidence"]) for r in ocr_rows}
    return tuple(ours.get(p.page_no, p) for p in fresh)


def ocr(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    methods: tuple[str, ...] = (METHOD_PENDING,),
    limit_pages: int | None = None,
    workers: int = 1,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """OCR pages whose text source is in `methods`, committing after each chunk of pages."""
    from judicial_mcp.pdf import ocr as ocr_engine

    if not ocr_engine.ocr_available():
        raise ocr_engine.OcrUnavailableError("OCR requires macOS with `ocrmac` installed (uv sync --extra ocr)")
    marks = ",".join("?" * len(methods))
    rows = conn.execute(
        f"SELECT p.doc_id, p.page_no, p.text, d.file_path FROM pages p JOIN documents d ON d.id = p.doc_id "  # noqa: S608
        f"WHERE p.method IN ({marks}) ORDER BY d.judgment_id DESC, d.ord, p.page_no",
        methods,
    ).fetchall()
    if limit_pages:
        rows = rows[:limit_pages]
    existing = {(r["doc_id"], r["page_no"]): r["text"] for r in rows}
    jobs = _ocr_jobs(rows, settings.data_dir)
    total, done = len(rows), 0
    for doc_id, results in _run_ocr_jobs(jobs, ocr_engine.ocr_pages, workers):
        store.update_pages(conn, doc_id, [p for p in results if _is_improvement(p, existing[(doc_id, p.page_no)])])
        done += len(results)
        if progress:
            progress(done, total)
    return {"ocr_pages": done, "total_candidates": total}


OcrJob = tuple[int, Path, tuple[int, ...]]  # (doc_id, pdf path, page numbers)


def _ocr_jobs(rows: list[sqlite3.Row], data_dir: Path) -> list[OcrJob]:
    """Group pages by document, split into chunks so work spreads evenly across workers."""
    by_doc: dict[int, tuple[str, list[int]]] = {}
    for r in rows:
        by_doc.setdefault(r["doc_id"], (r["file_path"], []))[1].append(r["page_no"])
    return [
        (doc_id, data_dir / file_path, tuple(pages[i : i + OCR_CHUNK_PAGES]))
        for doc_id, (file_path, pages) in by_doc.items()
        for i in range(0, len(pages), OCR_CHUNK_PAGES)
    ]


def _run_ocr_jobs(
    jobs: list[OcrJob], ocr_fn: Callable[[Path, tuple[int, ...]], tuple[PageText, ...]], workers: int
) -> Iterator[tuple[int, tuple[PageText, ...]]]:
    """Yield (doc_id, pages) per job; failures are logged and skipped so a bad file can't stop the run."""
    if workers <= 1:
        for doc_id, path, pages in jobs:
            try:
                yield doc_id, ocr_fn(path, pages)
            except Exception as exc:  # OCR engines raise assorted errors
                log.error("ocr doc %d pages %s failed: %s", doc_id, pages[:1], exc)
        return
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        futures = {pool.submit(ocr_fn, path, pages): (doc_id, pages) for doc_id, path, pages in jobs}
        for future in as_completed(futures):
            doc_id, pages = futures[future]
            try:
                yield doc_id, future.result()
            except Exception as exc:  # includes worker crashes
                log.error("ocr doc %d pages %s failed: %s", doc_id, pages[:1], exc)


def _is_improvement(new: PageText, old_text: str) -> bool:
    """Keep existing (site OCR) text when our OCR recovers far less of the page."""
    old = meaningful_chars(old_text)
    return old == 0 or meaningful_chars(new.text) >= old * 0.5
