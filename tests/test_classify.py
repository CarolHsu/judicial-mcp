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
