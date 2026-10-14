from pathlib import Path

import pytest

from judicial_mcp.parse.detail import parse_detail, roc_to_iso
from judicial_mcp.parse.listing import parse_listing

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def judgment():
    html = (FIXTURES / "detail_309577.html").read_text(encoding="utf-8")
    return parse_detail(html, 309577)


def test_header_fields(judgment):
    assert judgment.case_no == "111年憲判字第6號"
    assert judgment.case_name == "萊劑殘留標準之權限爭議案"
    assert (judgment.year, judgment.number) == (111, 6)
    assert judgment.original_case_no == "110年度憲一字第4號"
    assert judgment.decision_date == "2022-05-13"
    assert judgment.petitioner == "嘉義市議會等"
    assert judgment.cause.startswith("聲請人一至五分別就其制定食品安全相關之自治條例")


def test_main_text_paragraphs(judgment):
    main = [p for p in judgment.paragraphs if p.section == "主文"]
    assert [p.para_no for p in main] == [1, 2, 3]
    assert main[0].text.startswith("一、進口肉品及其產製品殘留乙型受體素")
    assert main[2].text == "三、其餘聲請不受理。"


def test_reasoning_paragraphs(judgment):
    reasons = [p for p in judgment.paragraphs if p.section == "理由"]
    assert len(reasons) > 50
    assert reasons[0].text == "壹、案件事實與聲請意旨【1】"
    assert [p.para_no for p in reasons] == list(range(1, len(reasons) + 1))


def test_statutes(judgment):
    assert len(judgment.statutes) >= 5
    first = judgment.statutes[0]
    assert first.text == "105年10月16日制定公布之嘉義市食品安全管理自治條例第6條第2項"
    assert first.url.startswith("https://law.chiayi.gov.tw/")


def test_related_cases(judgment):
    nos = [r.case_no for r in judgment.related_cases]
    assert "111年度憲地字第1號(桃園市議會)" in nos
    assert all(r.url.startswith("https://cons.judicial.gov.tw/docdata.aspx") for r in judgment.related_cases)


def test_attachments_sections_and_groups(judgment):
    by_id = {a.doc_id: a for a in judgment.attachments}
    assert by_id[473788].section == "大法官就主文所採立場表"
    assert by_id[473763].section == "意見書"
    assert by_id[473763].title == "憲法法庭111年憲判字第6號判決張大法官瓊文提出之協同意見書"
    assert by_id[473789].section == "判決全文"
    assert by_id[473790].section == "判決摘要"
    assert by_id[473794].section == "公開之卷內文書"
    assert by_id[473794].group == "聲請人聲請書、補充聲請書"
    assert by_id[473819].group == "專家諮詢意見書"
    assert by_id[473794].ext == "pdf"


def test_attachments_unique_and_complete(judgment):
    ids = [a.doc_id for a in judgment.attachments]
    assert len(ids) == len(set(ids))
    assert len(ids) == 39  # every distinct download.aspx id on the page


def test_external_links_are_not_attachments(judgment):
    assert all(a.doc_id > 0 for a in judgment.attachments)


@pytest.mark.parametrize(
    ("raw", "iso"),
    [("111年05月13日", "2022-05-13"), ("112年1月3日", "2023-01-03"), ("1100511", "2021-05-11"), ("bad", None)],
)
def test_roc_to_iso(raw, iso):
    assert roc_to_iso(raw) == iso


def test_parse_listing():
    html = (FIXTURES / "listing_page1.html").read_text(encoding="utf-8")
    ids = parse_listing(html)
    assert len(ids) == 59
    assert 309577 in ids
    assert len(ids) == len(set(ids))
