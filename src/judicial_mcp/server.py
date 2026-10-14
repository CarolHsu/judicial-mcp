"""MCP server exposing Constitutional Court judgments and their case files."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from judicial_mcp.db import query as q
from judicial_mcp.db import search
from judicial_mcp.db.connection import DatabaseMissingError, connect
from judicial_mcp.parse.classify import DOC_TYPE_LABELS

DocType = Literal[
    "opinion", "summary", "position_table", "petition", "response", "oral_argument_brief",
    "slides", "expert_opinion", "amicus", "transcript", "filing",
]
CaseRef = Annotated[str, Field(description="判決字號，例如「111年憲判字第6號」「111憲判6」「111-6」")]

INSTRUCTIONS = """\
憲法法庭判決資料庫（111年起之憲判字判決），資料來源：https://cons.judicial.gov.tw 。
內容包含判決主文、理由（含段碼【n】）、相關法令、併案，以及「公開之卷內文書」等附件 PDF 的全文
（聲請書、答辯書、言詞辯論意旨書、專家諮詢意見書、法庭之友意見書、大法官意見書、判決摘要）。

使用建議：
- 找判決見解 → search_judgments；找當事人書狀、專家意見、大法官意見書內容 → search_documents。
- 搜尋詞以空白分隔、全部須命中（AND）。三字以上的詞走全文索引最快。
- 引用時請附判決字號與段碼（例：111年憲判字第6號判決理由第35段），或文件標題與頁碼，並附 source_url。
- 附件文字多來自掃描檔 OCR（text_source = ocr / site_ocr），可能有錯字；引用前可提醒使用者核對原檔。
"""

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _tool_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn anticipated lookup/query errors into ToolError messages the model can read."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (q.NotFoundError, search.EmptyQueryError, DatabaseMissingError) as exc:
            raise ToolError(str(exc)) from exc
        except sqlite3.OperationalError as exc:
            raise ToolError(f"查詢失敗，請調整搜尋詞：{exc}") from exc

    return wrapper


def build_server(db_path: Path) -> MCPServer:
    server = MCPServer(name="judicial-mcp", title="憲法法庭判決", instructions=INSTRUCTIONS, version="0.1.0")
    state: dict[str, sqlite3.Connection] = {}
    lock = threading.Lock()

    def db() -> sqlite3.Connection:
        # Opened lazily so the server can start (and report a clear error) before data exists.
        with lock:
            if "conn" not in state:
                state["conn"] = connect(db_path, readonly=True)
            return state["conn"]

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def search_judgments(
        query: Annotated[str, Field(description="搜尋詞，空白分隔，例如「地方自治 食品安全」")],
        year: Annotated[int | None, Field(description="民國年度，例如 112")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict:
        """全文搜尋判決的主文與理由段落，回傳判決字號、段碼與命中片段（【】標示命中處）。"""
        hits = search.search_paragraphs(db(), query, year=year, limit=limit)
        return {"count": len(hits), "results": hits}

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def search_documents(
        query: Annotated[str, Field(description="搜尋詞，空白分隔")],
        doc_type: Annotated[DocType | None, Field(description="限定文件類型")] = None,
        case: Annotated[str | None, Field(description="限定某判決，例如「111年憲判字第6號」")] = None,
        party: Annotated[str | None, Field(description="限定提出者，例如「行政院」「臺北市議會」")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict:
        """全文搜尋判決附件（聲請書、答辯書、言詞辯論意旨書、專家意見、大法官意見書等 PDF 轉出的文字），以頁為單位回傳命中片段。"""
        case_no = None
        if case:
            case_no = q.get_judgment(db(), q.resolve_judgment_id(db(), case))["case_no"]
        hits = search.search_pages(db(), query, doc_type=doc_type, case_no=case_no, party=party, limit=limit)
        return {"count": len(hits), "results": hits}

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def get_judgment(case: CaseRef) -> dict:
        """取得判決基本資料：案名、日期、聲請人、案由、主文全文、相關法令、併案、附件統計。理由請用 get_judgment_paragraphs 分段讀取。"""
        return q.get_judgment(db(), q.resolve_judgment_id(db(), case))

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def get_judgment_paragraphs(
        case: CaseRef,
        section: Annotated[Literal["理由", "主文"], Field(description="段落區塊")] = "理由",
        start: Annotated[int, Field(ge=1, description="起始段碼")] = 1,
        end: Annotated[int | None, Field(ge=1, description="結束段碼（含），一次最多 80 段")] = None,
    ) -> dict:
        """依段碼讀取判決理由（或主文）原文，段碼即判決中的【n】。"""
        judgment_id = q.resolve_judgment_id(db(), case)
        paragraphs = q.get_paragraphs(db(), judgment_id, section, start, end)
        return {"case_no": q.get_judgment(db(), judgment_id)["case_no"], "section": section, "paragraphs": paragraphs}

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def list_judgments(
        year: Annotated[int | None, Field(description="民國年度")] = None,
        keyword: Annotated[str | None, Field(description="比對案名、案由、聲請人")] = None,
    ) -> dict:
        """列出判決（新到舊），可依年度或關鍵字篩選。"""
        items = q.list_judgments(db(), year=year, keyword=keyword)
        return {"count": len(items), "judgments": items}

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def list_documents(
        case: CaseRef,
        doc_type: Annotated[DocType | None, Field(description="限定文件類型")] = None,
    ) -> dict:
        """列出某判決的附件文件（doc_id、標題、類型、提出者、頁數），再用 read_document 讀內容。"""
        docs = q.list_documents(db(), q.resolve_judgment_id(db(), case), doc_type)
        return {"count": len(docs), "documents": docs}

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def read_document(
        doc_id: Annotated[int, Field(description="list_documents / search_documents 回傳的 doc_id")],
        start_page: Annotated[int, Field(ge=1)] = 1,
        max_pages: Annotated[int, Field(ge=1, le=20)] = 5,
    ) -> dict:
        """分頁讀取附件全文。回傳 next_page 時代表還有後續頁。"""
        return q.read_document(db(), doc_id, start_page, max_pages)

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def find_judgments_by_statute(
        statute: Annotated[str, Field(description="法規名稱或條號片段，例如「食品安全衛生管理法」「第15條」")],
    ) -> dict:
        """依判決「相關法令」欄位找出涉及某法規的判決。"""
        items = q.find_by_statute(db(), statute)
        return {"count": len(items), "results": items}

    @server.tool(annotations=_READ_ONLY)
    @_tool_errors
    def corpus_info() -> dict:
        """資料庫概況：判決數、日期範圍、附件處理進度、文件類型代碼說明。"""
        return {**q.corpus_stats(db()), "doc_type_labels": DOC_TYPE_LABELS}

    return server
