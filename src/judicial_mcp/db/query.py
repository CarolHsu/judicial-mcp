"""Read-side lookups returning JSON-friendly dicts."""

from __future__ import annotations

import re
import sqlite3

from judicial_mcp.db.search import escape_like

MAX_PAGES_PER_READ = 20
MAX_PARAGRAPHS_PER_READ = 80

_CASE_REF_RE = re.compile(r"(\d{2,3})\s*年?\s*(?:度)?\s*憲判(?:字)?\s*(?:第)?\s*(\d+)\s*號?")
_SHORT_REF_RE = re.compile(r"^\s*(\d{2,3})\s*[-/／]\s*(\d+)\s*$")


class NotFoundError(LookupError):
    pass


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def resolve_judgment_id(conn: sqlite3.Connection, ref: str | int) -> int:
    """Accept 111年憲判字第6號, 111憲判6, 111-6, or the site id 309577."""
    text = str(ref).strip()
    match = _CASE_REF_RE.search(text) or _SHORT_REF_RE.match(text)
    if match:
        row = conn.execute(
            "SELECT id FROM judgments WHERE year = ? AND number = ?", (int(match.group(1)), int(match.group(2)))
        ).fetchone()
        if row:
            return row["id"]
    if text.isdigit():
        row = conn.execute("SELECT id FROM judgments WHERE id = ?", (int(text),)).fetchone()
        if row:
            return row["id"]
    row = conn.execute("SELECT id FROM judgments WHERE case_no = ? OR case_name = ?", (text, text)).fetchone()
    if row:
        return row["id"]
    raise NotFoundError(f"找不到判決：{text}（可用格式：111年憲判字第6號、111憲判6、111-6）")


def list_judgments(conn: sqlite3.Connection, *, year: int | None = None, keyword: str | None = None) -> list[dict]:
    filters, params = [], []
    if year is not None:
        filters.append("year = ?")
        params.append(year)
    if keyword:
        filters.append("(case_name LIKE ? ESCAPE '\\' OR cause LIKE ? ESCAPE '\\' OR petitioner LIKE ? ESCAPE '\\')")
        params.extend([f"%{escape_like(keyword)}%"] * 3)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"SELECT case_no, case_name, decision_date, petitioner FROM judgments {where} "  # noqa: S608
        "ORDER BY year DESC, number DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_judgment(conn: sqlite3.Connection, judgment_id: int) -> dict:
    judgment = _row(conn.execute("SELECT * FROM judgments WHERE id = ?", (judgment_id,)).fetchone())
    if judgment is None:
        raise NotFoundError(f"judgment id {judgment_id} not found")
    main = conn.execute(
        "SELECT para_no, text FROM paragraphs WHERE judgment_id = ? AND section = '主文' ORDER BY para_no",
        (judgment_id,),
    ).fetchall()
    reason_count = conn.execute(
        "SELECT COUNT(*) FROM paragraphs WHERE judgment_id = ? AND section = '理由'", (judgment_id,)
    ).fetchone()[0]
    statutes = conn.execute(
        "SELECT text, url FROM statutes WHERE judgment_id = ? ORDER BY ord", (judgment_id,)
    ).fetchall()
    related = conn.execute(
        "SELECT case_no, url FROM related_cases WHERE judgment_id = ? ORDER BY ord", (judgment_id,)
    ).fetchall()
    doc_counts = conn.execute(
        "SELECT doc_type, COUNT(*) AS n FROM documents WHERE judgment_id = ? AND status != 'skipped' "
        "GROUP BY doc_type ORDER BY n DESC",
        (judgment_id,),
    ).fetchall()
    return {
        **{k: judgment[k] for k in ("case_no", "case_name", "original_case_no", "decision_date", "petitioner", "cause", "author_note", "source_url")},
        "main_text": [{"para_no": r["para_no"], "text": r["text"]} for r in main],
        "reasoning_paragraph_count": reason_count,
        "statutes": [dict(r) for r in statutes],
        "related_cases": [dict(r) for r in related],
        "documents_by_type": {r["doc_type"]: r["n"] for r in doc_counts},
    }


def get_paragraphs(
    conn: sqlite3.Connection, judgment_id: int, section: str, start: int, end: int | None
) -> list[dict]:
    last = end if end is not None else start + MAX_PARAGRAPHS_PER_READ - 1
    last = min(last, start + MAX_PARAGRAPHS_PER_READ - 1)
    rows = conn.execute(
        "SELECT para_no, text FROM paragraphs WHERE judgment_id = ? AND section = ? AND para_no BETWEEN ? AND ? "
        "ORDER BY para_no",
        (judgment_id, section, start, last),
    ).fetchall()
    return [dict(r) for r in rows]


def list_documents(conn: sqlite3.Connection, judgment_id: int, doc_type: str | None = None) -> list[dict]:
    params: list = [judgment_id]
    type_filter = ""
    if doc_type:
        type_filter = "AND doc_type = ?"
        params.append(doc_type)
    rows = conn.execute(
        "SELECT id AS doc_id, title, doc_type, grp AS 'group', party, justice, opinion_type, filed_date, "
        "page_count, status, source_url FROM documents "
        f"WHERE judgment_id = ? AND status != 'skipped' {type_filter} ORDER BY ord",  # noqa: S608
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def read_document(conn: sqlite3.Connection, doc_id: int, start_page: int, max_pages: int) -> dict:
    doc = _row(
        conn.execute(
            "SELECT d.id AS doc_id, d.title, d.doc_type, d.party, d.page_count, d.status, d.source_url, "
            "d.twin_id, j.case_no FROM documents d JOIN judgments j ON j.id = d.judgment_id WHERE d.id = ?",
            (doc_id,),
        ).fetchone()
    )
    if doc is None:
        raise NotFoundError(f"document {doc_id} not found")
    twin_id = doc.pop("twin_id")
    if doc["status"] == "skipped" and twin_id is not None:
        # Scanned original: its text lives on the _OCR sibling.
        twin = read_document(conn, twin_id, start_page, max_pages)
        return {**twin, "doc_id": doc_id, "text_from_doc_id": twin_id, "source_url": doc["source_url"]}
    count = max(1, min(max_pages, MAX_PAGES_PER_READ))
    pages = conn.execute(
        "SELECT page_no, text, method AS text_source FROM pages WHERE doc_id = ? AND page_no >= ? "
        "ORDER BY page_no LIMIT ?",
        (doc_id, max(1, start_page), count),
    ).fetchall()
    page_list = [dict(p) for p in pages]
    last_read = page_list[-1]["page_no"] if page_list else None
    has_more = bool(doc["page_count"] and last_read and last_read < doc["page_count"])
    return {**doc, "pages": page_list, "next_page": last_read + 1 if has_more else None}


def find_by_statute(conn: sqlite3.Connection, keyword: str) -> list[dict]:
    rows = conn.execute(
        "SELECT j.case_no, j.case_name, j.decision_date, s.text AS statute, s.url FROM statutes s "
        "JOIN judgments j ON j.id = s.judgment_id WHERE s.text LIKE ? ESCAPE '\\' ORDER BY j.year DESC, j.number DESC",
        (f"%{escape_like(keyword.strip())}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def corpus_stats(conn: sqlite3.Connection) -> dict:
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    methods = conn.execute("SELECT method, COUNT(*) AS n FROM pages GROUP BY method").fetchall()
    statuses = conn.execute("SELECT status, COUNT(*) AS n FROM documents GROUP BY status").fetchall()
    return {
        "judgments": one("SELECT COUNT(*) FROM judgments"),
        "date_range": list(conn.execute("SELECT MIN(decision_date), MAX(decision_date) FROM judgments").fetchone()),
        "documents_by_status": {r["status"]: r["n"] for r in statuses},
        "pages_by_text_source": {r["method"]: r["n"] for r in methods},
        "indexed_at": (conn.execute("SELECT value FROM meta WHERE key = 'indexed_at'").fetchone() or [None])[0],
    }
