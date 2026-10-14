import pytest

from judicial_mcp.db import query, search
from judicial_mcp.db.connection import DatabaseMissingError, connect


def test_documents_status_after_pipeline(conn):
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM documents")}
    assert rows[473763]["status"] == "extracted"
    assert rows[473763]["page_count"] == 13
    assert rows[473794]["status"] == "skipped"  # scanned original with an _OCR twin
    assert rows[473794]["twin_id"] == 473795
    assert rows[473789]["status"] == "skipped"  # judgment PDF duplicates the HTML
    assert rows[473796]["status"] == "pending"


@pytest.mark.parametrize("ref", ["111年憲判字第6號", "111憲判6", "111-6", "309577", "萊劑殘留標準之權限爭議案"])
def test_resolve_judgment_id(conn, ref):
    assert query.resolve_judgment_id(conn, ref) == 309577


def test_resolve_unknown(conn):
    with pytest.raises(query.NotFoundError):
        query.resolve_judgment_id(conn, "999年憲判字第1號")


def test_get_judgment(conn):
    j = query.get_judgment(conn, 309577)
    assert j["case_no"] == "111年憲判字第6號"
    assert len(j["main_text"]) == 3
    assert j["reasoning_paragraph_count"] > 50
    assert j["documents_by_type"]["opinion"] == 4
    assert "judgment_full" not in j["documents_by_type"]


def test_get_paragraphs_range_and_cap(conn):
    paras = query.get_paragraphs(conn, 309577, "理由", 3, 5)
    assert [p["para_no"] for p in paras] == [3, 4, 5]
    capped = query.get_paragraphs(conn, 309577, "理由", 1, 1000)
    assert len(capped) == query.MAX_PARAGRAPHS_PER_READ


def test_list_documents_filter(conn):
    opinions = query.list_documents(conn, 309577, "opinion")
    assert {d["justice"] for d in opinions} == {"張瓊文", "詹森林", "黃虹霞", "蔡明誠"}


def test_read_document_paging(conn):
    first = query.read_document(conn, 473763, 1, 5)
    assert [p["page_no"] for p in first["pages"]] == [1, 2, 3, 4, 5]
    assert first["next_page"] == 6
    last = query.read_document(conn, 473763, 11, 5)
    assert last["next_page"] is None


def test_read_document_missing(conn):
    with pytest.raises(query.NotFoundError):
        query.read_document(conn, 1, 1, 1)


def test_find_by_statute(conn):
    hits = query.find_by_statute(conn, "臺北市食品安全自治條例")
    assert hits and hits[0]["case_no"] == "111年憲判字第6號"


def test_corpus_stats(conn):
    stats = query.corpus_stats(conn)
    assert stats["judgments"] == 1
    assert stats["pages_by_text_source"]["native"] >= 13
    assert stats["indexed_at"]


def test_search_paragraphs_fts(conn):
    hits = search.search_paragraphs(conn, "乙型受體素")
    assert hits
    assert "【乙型受體素】" in hits[0]["snippet"]


def test_search_paragraphs_short_term_fallback(conn):
    hits = search.search_paragraphs(conn, "萊劑")
    assert all("萊劑" in h["snippet"] for h in hits)


def test_search_paragraphs_mixed_terms_and_year(conn):
    assert search.search_paragraphs(conn, "地方自治 中央", year=111)
    assert search.search_paragraphs(conn, "地方自治", year=112) == []


def test_search_pages(conn):
    hits = search.search_pages(conn, "協同意見", doc_type="opinion")
    assert hits and hits[0]["doc_id"] == 473763
    brief = search.search_pages(conn, "言詞辯論", party="臺北市議會")
    assert brief and brief[0]["text_source"] == "site_ocr"


def test_search_empty_query(conn):
    with pytest.raises(search.EmptyQueryError):
        search.search_pages(conn, "   ")


def test_snippet_marks_terms():
    text = "甲" * 100 + "地方自治" + "乙" * 300
    snippet = search.make_snippet(text, ("地方自治",))
    assert snippet.startswith("…") and snippet.endswith("…")
    assert "【地方自治】" in snippet


def test_readonly_missing_db(tmp_path):
    with pytest.raises(DatabaseMissingError):
        connect(tmp_path / "nope.db", readonly=True)


def test_like_wildcards_are_literal(conn):
    assert query.find_by_statute(conn, "%") == []
    assert query.list_judgments(conn, keyword="_") == []
    assert search.search_pages(conn, "意見", party="%") == []


def test_read_skipped_original_reads_its_ocr_twin(mutable_db):
    from judicial_mcp.db import store
    from judicial_mcp.models import PageText

    rw = connect(mutable_db.db_path)
    rw.execute("UPDATE documents SET status='extracted', page_count=1 WHERE id=473795")
    store.replace_pages(rw, 473795, [PageText(1, "雙胞胎OCR內容", "ocr")])
    rw.close()
    ro = connect(mutable_db.db_path, readonly=True)
    doc = query.read_document(ro, 473794, 1, 5)
    assert doc["text_from_doc_id"] == 473795
    assert doc["pages"][0]["text"] == "雙胞胎OCR內容"
    ro.close()
