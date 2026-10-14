import pytest

from judicial_mcp.models import AttachmentRef
from judicial_mcp.parse.classify import classify, pair_ocr_twins


def ref(title, section="公開之卷內文書", group="聲請人聲請書、補充聲請書", doc_id=1):
    return AttachmentRef(doc_id=doc_id, section=section, group=group, title=title, ext="pdf")


def test_opinion_justice_and_type():
    m = classify(ref("憲法法庭111年憲判字第6號判決黃大法官虹霞提出之部分協同部分不同意見書", section="意見書", group=None))
    assert m.doc_type == "opinion"
    assert m.justice == "黃虹霞"
    assert m.opinion_type == "部分協同部分不同"


def test_opinion_dissent():
    m = classify(ref("憲法法庭111年憲判字第6號判決蔡大法官明誠提出之不同意見書", section="意見書", group=None))
    assert (m.justice, m.opinion_type) == ("蔡明誠", "不同")


@pytest.mark.parametrize(
    ("section", "doc_type"),
    [("判決全文", "judgment_full"), ("判決摘要", "summary"), ("大法官就主文所採立場表", "position_table")],
)
def test_section_based_types(section, doc_type):
    assert classify(ref("x", section=section, group=None)).doc_type == doc_type


def test_petition_with_date_and_party():
    m = classify(ref("嘉義市議會1100511解釋憲法聲請書及附件_OCR"))
    assert m.doc_type == "petition"
    assert m.is_ocr_variant is True
    assert m.base_title == "嘉義市議會1100511解釋憲法聲請書及附件"
    assert m.party == "嘉義市議會"
    assert m.filed_date == "2021-05-11"


def test_oral_argument_brief_party():
    m = classify(ref("聲請人臺北市議會之代理人紀俊臣教授、張少騰律師、黃品瑜律師之言詞辯論意旨（三）書_OCR"))
    assert m.doc_type == "oral_argument_brief"
    assert m.party == "臺北市議會"


def test_related_agency_brief():
    m = classify(ref("關係機關行政院之代理人洪偉勝律師、李荃和律師、孫迺翊教授之言詞辯論意旨書(1110218修訂版)", group="相對人答辯書、補充答辯書"))
    assert m.doc_type == "oral_argument_brief"
    assert m.party == "行政院"
    assert m.filed_date == "2022-02-18"


def test_slides_and_expert():
    assert classify(ref("專家學者詹鎮榮教授之意見書簡報檔", group="專家諮詢意見書")).doc_type == "slides"
    m = classify(ref("專家學者詹鎮榮教授之意見書", group="專家諮詢意見書"))
    assert m.doc_type == "expert_opinion"
    assert m.party == "詹鎮榮"


def test_response_group():
    m = classify(ref("行政院答辯書", group="相對人答辯書、補充答辯書"))
    assert m.doc_type == "response"


def test_amicus():
    assert classify(ref("某某協會法庭之友意見書", group="法庭之友意見書")).doc_type == "amicus"


def test_pair_ocr_twins_marks_originals():
    metas = [
        classify(ref("嘉義市議會1100511解釋憲法聲請書及附件", doc_id=10)),
        classify(ref("嘉義市議會1100511解釋憲法聲請書及附件_OCR", doc_id=11)),
        classify(ref("聲請人嘉義市議會之代理人梁樹綸律師之言詞辯論意旨書", doc_id=12)),
    ]
    twins = pair_ocr_twins(metas)
    assert twins == {10: 11}


@pytest.mark.parametrize(
    ("title", "justice", "opinion_type"),
    [
        ("憲法法庭113年憲判字第9號判決黃大法官瑞明提出協同意見書", "黃瑞明", "協同"),
        ("憲法法庭112年憲判字第2號判決楊大法官惠欽提出，吳大法官陳鐶、黃大法官昭元加入之不同意見書", "楊惠欽", "不同"),
        ("憲法法庭112年憲判字第6號判決林大法官俊益提出，張大法官瓊文、蔡大法官宗珍加入之部分不同意見書", "林俊益", "部分不同"),
        ("憲法法庭113年憲判字第9號判決許大法官志雄提出部分協同部分不同意見書，黃大法官昭元加入", "許志雄", "部分協同部分不同"),
    ],
)
def test_opinion_title_variants(title, justice, opinion_type):
    m = classify(ref(title, section="意見書", group=None))
    assert (m.justice, m.opinion_type) == (justice, opinion_type)


@pytest.mark.parametrize(
    ("title", "party", "filed_date"),
    [
        ("賴擁連教授1130409專家諮詢意見書_OCR", "賴擁連", "2024-04-09"),
        ("吳宗謀1110701專家諮詢意見書補充意見", "吳宗謀", "2022-07-01"),
        ("曾文亮副研究員1111013意見書_OCR", "曾文亮", "2022-10-13"),
        ("楊皓清法官990505意見書_OCR", "楊皓清", "2010-05-05"),
        ("林超駿教授1120201意見書 _OCR", "林超駿", "2023-02-01"),
    ],
)
def test_expert_names_and_dates(title, party, filed_date):
    m = classify(ref(title, group="專家諮詢意見書"))
    assert m.doc_type == "expert_opinion"
    assert (m.party, m.filed_date) == (party, filed_date)


def test_ocr_suffix_with_stray_space():
    m = classify(ref("林超駿教授1120201意見書 _OCR", group="專家諮詢意見書"))
    assert m.is_ocr_variant and m.base_title == "林超駿教授1120201意見書"


def test_opinion_full_name_before_title():
    m = classify(ref("憲法法庭112年憲判字第14號判決呂太郎大法官提出之部分不同意見書", section="意見書", group=None))
    assert (m.justice, m.opinion_type) == ("呂太郎", "部分不同")


@pytest.mark.parametrize(
    ("title", "party"),
    [
        ("專家諮詢意見書-吳啟瑞", "吳啟瑞"),
        ("專家諮詢意見書-林沛君助理教授_OCR", "林沛君"),
        ("專家諮詢意見書-戴瑀如教授（文字錯漏校正版）", "戴瑀如"),
        ("臺灣稅法學會代表葛克昌教授專家諮詢意見書", "葛克昌"),
        ("中華民國會計師公會全國聯合會代表陳世洋會計師1120422意見書_OCR", "陳世洋"),
        ("監察院國家人權委員會1110112函暨意見_OCR", "監察院國家人權委員會"),
        ("中華民國醫師公會全國聯合會1130205意見書＿OCR", "中華民國醫師公會全國聯合會"),
    ],
)
def test_expert_title_variants(title, party):
    assert classify(ref(title, group="專家諮詢意見書")).party == party


def test_fullwidth_ocr_suffix():
    m = classify(ref("中華民國醫師公會全國聯合會1130205意見書＿OCR", group="專家諮詢意見書"))
    assert m.is_ocr_variant and m.base_title == "中華民國醫師公會全國聯合會1130205意見書"
