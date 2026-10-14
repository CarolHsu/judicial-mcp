import json

import pytest
from mcp import Client

from judicial_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def server(built_db):
    return build_server(built_db.db_path)


def _payload(result):
    assert not result.is_error, result.content
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


async def test_lists_all_tools(server):
    async with Client(server) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
    assert tools == {
        "search_judgments", "search_documents", "get_judgment", "get_judgment_paragraphs",
        "list_judgments", "list_documents", "read_document", "find_judgments_by_statute", "corpus_info",
    }


async def test_search_judgments_tool(server):
    async with Client(server) as client:
        data = _payload(await client.call_tool("search_judgments", {"query": "乙型受體素", "limit": 3}))
    assert data["count"] >= 1
    assert data["results"][0]["case_no"] == "111年憲判字第6號"


async def test_get_judgment_and_paragraphs(server):
    async with Client(server) as client:
        j = _payload(await client.call_tool("get_judgment", {"case": "111憲判6"}))
        p = _payload(await client.call_tool("get_judgment_paragraphs", {"case": "111-6", "start": 1, "end": 2}))
    assert j["case_name"] == "萊劑殘留標準之權限爭議案"
    assert [x["para_no"] for x in p["paragraphs"]] == [1, 2]


async def test_documents_flow(server):
    async with Client(server) as client:
        docs = _payload(await client.call_tool("list_documents", {"case": "111年憲判字第6號", "doc_type": "opinion"}))
        doc = _payload(await client.call_tool("read_document", {"doc_id": 473763, "max_pages": 2}))
        hits = _payload(await client.call_tool("search_documents", {"query": "協同意見", "case": "111-6"}))
    assert docs["count"] == 4
    assert doc["next_page"] == 3
    assert hits["count"] >= 1


async def test_statute_and_info(server):
    async with Client(server) as client:
        statute = _payload(await client.call_tool("find_judgments_by_statute", {"statute": "自治條例"}))
        info = _payload(await client.call_tool("corpus_info", {}))
        listing = _payload(await client.call_tool("list_judgments", {"year": 111}))
    assert statute["count"] >= 1
    assert info["judgments"] == 1
    assert listing["judgments"][0]["case_no"] == "111年憲判字第6號"


async def test_not_found_is_tool_error(server):
    async with Client(server) as client:
        result = await client.call_tool("get_judgment", {"case": "999年憲判字第1號"})
    assert result.is_error
    assert "找不到判決" in result.content[0].text
