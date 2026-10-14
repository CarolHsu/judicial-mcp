"""Full-text search over judgment paragraphs and attachment pages.

FTS5's trigram tokenizer only indexes 3+ character sequences, while many
Chinese legal terms are two characters (人權, 隱私). Terms of 3+ characters go
through the FTS index; shorter ones fall back to a LIKE filter.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

MIN_FTS_TERM = 3
SNIPPET_RADIUS = 60
MAX_LIMIT = 50


@dataclass(frozen=True)
class Query:
    fts_terms: tuple[str, ...]
    like_terms: tuple[str, ...]

    @property
    def all_terms(self) -> tuple[str, ...]:
        return self.fts_terms + self.like_terms


class EmptyQueryError(ValueError):
    pass


def parse_query(raw: str) -> Query:
    terms = tuple(dict.fromkeys(t for t in re.split(r"\s+", raw.strip().replace('"', "")) if t))
    if not terms:
        raise EmptyQueryError("query is empty")
    return Query(
        fts_terms=tuple(t for t in terms if len(t) >= MIN_FTS_TERM),
        like_terms=tuple(t for t in terms if len(t) < MIN_FTS_TERM),
    )


def _fts_expression(query: Query) -> str:
    return " AND ".join(f'"{t}"' for t in query.fts_terms)


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def make_snippet(text: str, terms: tuple[str, ...], radius: int = SNIPPET_RADIUS) -> str:
    """Return text around the first matched term, with matches wrapped in 【】."""
    lowered = text.lower()
    positions = [lowered.find(t.lower()) for t in terms]
    hits = [p for p in positions if p >= 0]
    center = min(hits) if hits else 0
    start = max(0, center - radius)
    end = min(len(text), center + radius * 2)
    snippet = text[start:end].replace("\n", " ")
    for term in sorted(terms, key=len, reverse=True):
        snippet = re.sub(re.escape(term), lambda m: f"【{m.group(0)}】", snippet, flags=re.IGNORECASE)
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def _like_clauses(column: str, query: Query) -> tuple[str, list[str]]:
    clauses = [f"{column} LIKE ? ESCAPE '\\'" for _ in query.like_terms]
    params = [f"%{escape_like(t)}%" for t in query.like_terms]
    return " AND ".join(clauses), params


def search_paragraphs(
    conn: sqlite3.Connection, raw_query: str, *, year: int | None = None, limit: int = 10
) -> list[dict]:
    query = parse_query(raw_query)
    limit = max(1, min(limit, MAX_LIMIT))
    filters, params = [], []
    if query.fts_terms:
        source = "paragraphs_fts f JOIN paragraphs p ON p.judgment_id = f.judgment_id AND p.section = f.section AND p.para_no = f.para_no"
        filters.append("paragraphs_fts MATCH ?")
        params.append(_fts_expression(query))
        order = "bm25(paragraphs_fts)"
    else:
        source = "paragraphs p"
        order = "j.decision_date DESC, p.para_no"
    like_sql, like_params = _like_clauses("p.text", query)
    if like_sql:
        filters.append(like_sql)
        params.extend(like_params)
    if year is not None:
        filters.append("j.year = ?")
        params.append(year)
    sql = (
        f"SELECT j.case_no, j.case_name, j.decision_date, p.section, p.para_no, p.text "  # noqa: S608
        f"FROM {source} JOIN judgments j ON j.id = p.judgment_id "
        f"WHERE {' AND '.join(filters)} ORDER BY {order} LIMIT ?"
    )
    rows = conn.execute(sql, [*params, limit]).fetchall()
    return [
        {
            "case_no": r["case_no"],
            "case_name": r["case_name"],
            "decision_date": r["decision_date"],
            "section": r["section"],
            "para_no": r["para_no"],
            "snippet": make_snippet(r["text"], query.all_terms),
        }
        for r in rows
    ]


def search_pages(
    conn: sqlite3.Connection,
    raw_query: str,
    *,
    doc_type: str | None = None,
    case_no: str | None = None,
    party: str | None = None,
    limit: int = 10,
) -> list[dict]:
    query = parse_query(raw_query)
    limit = max(1, min(limit, MAX_LIMIT))
    filters, params = ["pg.text != ''"], []
    if query.fts_terms:
        source = "pages_fts f JOIN pages pg ON pg.doc_id = f.doc_id AND pg.page_no = f.page_no"
        filters.append("pages_fts MATCH ?")
        params.append(_fts_expression(query))
        order = "bm25(pages_fts)"
    else:
        source = "pages pg"
        order = "j.decision_date DESC, d.ord, pg.page_no"
    like_sql, like_params = _like_clauses("pg.text", query)
    if like_sql:
        filters.append(like_sql)
        params.extend(like_params)
    for column, value in (("d.doc_type", doc_type), ("j.case_no", case_no)):
        if value:
            filters.append(f"{column} = ?")
            params.append(value)
    if party:
        filters.append("(d.party LIKE ? ESCAPE '\\' OR d.title LIKE ? ESCAPE '\\')")
        params.extend([f"%{escape_like(party)}%"] * 2)
    sql = (
        f"SELECT d.id AS doc_id, d.title, d.doc_type, d.party, j.case_no, pg.page_no, pg.method, pg.text "  # noqa: S608
        f"FROM {source} JOIN documents d ON d.id = pg.doc_id JOIN judgments j ON j.id = d.judgment_id "
        f"WHERE {' AND '.join(filters)} ORDER BY {order} LIMIT ?"
    )
    rows = conn.execute(sql, [*params, limit]).fetchall()
    return [
        {
            "doc_id": r["doc_id"],
            "title": r["title"],
            "doc_type": r["doc_type"],
            "party": r["party"],
            "case_no": r["case_no"],
            "page_no": r["page_no"],
            "text_source": r["method"],
            "snippet": make_snippet(r["text"], query.all_terms),
        }
        for r in rows
    ]
