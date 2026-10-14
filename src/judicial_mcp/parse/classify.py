"""Derive document type, party, justice and filing date from attachment titles."""

from __future__ import annotations

import re
from collections.abc import Iterable

from judicial_mcp.models import AttachmentRef, DocumentMeta
from judicial_mcp.parse.detail import roc_to_iso

_OCR_SUFFIX_RE = re.compile(r"\s*[_＿]\s*OCR\s*$")  # also full-width ＿ and stray spaces

_SECTION_TYPES = {
    "意見書": "opinion",
    "判決全文": "judgment_full",
    "判決摘要": "summary",
    "大法官就主文所採立場表": "position_table",
}

DOC_TYPE_LABELS = {
    "opinion": "大法官意見書",
    "judgment_full": "判決全文(PDF)",
    "summary": "判決摘要",
    "position_table": "主文立場表",
    "petition": "聲請書",
    "response": "答辯書",
    "oral_argument_brief": "言詞辯論意旨書",
    "slides": "簡報",
    "expert_opinion": "專家諮詢意見書",
    "amicus": "法庭之友意見書",
    "transcript": "筆錄",
    "filing": "其他書狀",
}

# Author is the first "X大法官YY提出"; titles vary: "提出之協同意見書", "提出協同意見書",
# "提出，A大法官…加入之不同意見書".
_OPINION_AUTHOR_RE = re.compile(r"([一-鿿])大法官([一-鿿]{1,3}?)(?:共同)?提出")
_OPINION_TYPE_RE = re.compile(r"(部分協同部分不同|部分不同|部分協同|協同|不同)意見書")
# ROC dates written compactly in titles: 1100511 (yyy) or 990505 (yy).
_ROC_COMPACT_IN_TITLE = re.compile(r"(?<!\d)((?:1\d{2}|[89]\d)(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?!\d)")
_OPINION_FULLNAME_RE = re.compile(r"判決([一-鿿]{2,4})大法官(?:共同)?提出")
_PERSON_TITLES = "副教授|助理教授|教授|副研究員|助研究員|研究員|法官|會計師|律師|博士|先生|女士"
_PERSON_NAME_RE = re.compile(rf"^(?:專家學者)?([一-鿿]{{2,4}}?)(?:{_PERSON_TITLES}|\d|之)")
_DASH_NAME_RE = re.compile(rf"-\s*([一-鿿]{{2,4}}?)(?:{_PERSON_TITLES}|[（(_＿\s]|$)")
_REPRESENTATIVE_RE = re.compile(rf"代表([一-鿿]{{2,4}}?)(?:{_PERSON_TITLES})")
_LEADING_ORG_RE = re.compile(r"^([一-鿿（）()]+?)(?=\d{6,7})")
_AGENT_PARTY_RE = re.compile(r"^(?:聲請人|關係機關|相對人|關係人)(.+?)之(?:共同)?(?:訴訟)?代理人")
_LEADING_PARTY_RE = re.compile(r"^([一-鿿（）()]+?)(?=1\d{6}|解釋|統一解釋|聲請|答辯|補充)")


def _title_type(title: str, group: str | None) -> str:
    grp = group or ""
    if "簡報" in title:
        return "slides"
    if "言詞辯論意旨" in title:
        return "oral_argument_brief"
    if "法庭之友" in title or "法庭之友" in grp:
        return "amicus"
    if "專家" in grp or title.startswith("專家學者"):
        return "expert_opinion"
    if "筆錄" in title:
        return "transcript"
    if "答辯" in title or "答辯" in grp:
        return "response"
    if "聲請" in title:
        return "petition"
    return "filing"


def _party(title: str, doc_type: str) -> str | None:
    match = _AGENT_PARTY_RE.match(title)
    if match:
        return match.group(1).strip()
    if doc_type in {"expert_opinion", "slides"}:
        for pattern in (_DASH_NAME_RE, _REPRESENTATIVE_RE):
            match = pattern.search(title)
            if match:
                return match.group(1)
        for pattern in (_PERSON_NAME_RE, _LEADING_ORG_RE):
            match = pattern.match(title)
            if match:
                return match.group(1)
    if doc_type in {"petition", "response", "filing", "amicus"}:
        match = _LEADING_PARTY_RE.match(title)
        if match:
            return match.group(1).strip()
    return None


def classify(ref: AttachmentRef) -> DocumentMeta:
    is_ocr = bool(_OCR_SUFFIX_RE.search(ref.title))
    base_title = _OCR_SUFFIX_RE.sub("", ref.title) if is_ocr else ref.title
    doc_type = _SECTION_TYPES.get(ref.section) or _title_type(base_title, ref.group)

    justice = opinion_type = None
    if doc_type == "opinion":
        author = _OPINION_AUTHOR_RE.search(base_title)
        full_name = None if author else _OPINION_FULLNAME_RE.search(base_title)
        kind = _OPINION_TYPE_RE.search(base_title)
        justice = author.group(1) + author.group(2) if author else (full_name.group(1) if full_name else None)
        opinion_type = kind.group(1) if kind else None

    date_match = _ROC_COMPACT_IN_TITLE.search(base_title)
    return DocumentMeta(
        doc_id=ref.doc_id,
        section=ref.section,
        group=ref.group,
        title=ref.title,
        base_title=base_title,
        ext=ref.ext,
        doc_type=doc_type,
        is_ocr_variant=is_ocr,
        party=_party(base_title, doc_type),
        justice=justice,
        opinion_type=opinion_type,
        filed_date=roc_to_iso(date_match.group(1)) if date_match else None,
    )


def pair_ocr_twins(metas: Iterable[DocumentMeta]) -> dict[int, int]:
    """Map original doc_id -> its `_OCR` sibling's doc_id (same section/group/base title)."""
    items = tuple(metas)
    ocr_by_key = {(m.section, m.group, m.base_title): m.doc_id for m in items if m.is_ocr_variant}
    return {
        m.doc_id: ocr_by_key[(m.section, m.group, m.base_title)]
        for m in items
        if not m.is_ocr_variant and (m.section, m.group, m.base_title) in ocr_by_key
    }
