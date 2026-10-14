"""Derive document type, party, justice and filing date from attachment titles."""

from __future__ import annotations

import re
from collections.abc import Iterable

from judicial_mcp.models import AttachmentRef, DocumentMeta
from judicial_mcp.parse.detail import roc_to_iso

OCR_SUFFIX = "_OCR"

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

_OPINION_RE = re.compile(r"([一-鿿])大法官([一-鿿]{1,3}?)提出之(.*?)意見書")
_ROC_COMPACT_IN_TITLE = re.compile(r"(?<!\d)(1\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?!\d)")
_AGENT_PARTY_RE = re.compile(r"^(?:聲請人|關係機關|相對人|關係人)(.+?)之(?:共同)?(?:訴訟)?代理人")
_EXPERT_RE = re.compile(r"^專家學者(.+?)(?:教授|副教授|助理教授|研究員|副研究員|博士|律師|先生|女士)?之")
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
    for pattern in (_AGENT_PARTY_RE, _EXPERT_RE):
        match = pattern.match(title)
        if match:
            return match.group(1).strip()
    if doc_type in {"petition", "response", "filing", "amicus"}:
        match = _LEADING_PARTY_RE.match(title)
        if match:
            return match.group(1).strip()
    return None


def classify(ref: AttachmentRef) -> DocumentMeta:
    is_ocr = ref.title.endswith(OCR_SUFFIX)
    base_title = ref.title[: -len(OCR_SUFFIX)] if is_ocr else ref.title
    doc_type = _SECTION_TYPES.get(ref.section) or _title_type(base_title, ref.group)

    justice = opinion_type = None
    if doc_type == "opinion":
        match = _OPINION_RE.search(base_title)
        if match:
            justice = match.group(1) + match.group(2)
            opinion_type = match.group(3) or None

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
