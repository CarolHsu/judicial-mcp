"""Immutable domain records shared by the parser, store and server."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Paragraph:
    section: str  # "主文" or "理由"
    para_no: int
    text: str


@dataclass(frozen=True)
class Statute:
    text: str
    url: str | None


@dataclass(frozen=True)
class RelatedCase:
    case_no: str
    url: str | None


@dataclass(frozen=True)
class AttachmentRef:
    """A downloadable file as listed on the judgment page."""

    doc_id: int
    section: str  # page section title, e.g. "意見書", "公開之卷內文書"
    group: str | None  # sub-heading inside 公開之卷內文書
    title: str
    ext: str


@dataclass(frozen=True)
class DocumentMeta:
    """An attachment enriched with fields derived from its title."""

    doc_id: int
    section: str
    group: str | None
    title: str
    base_title: str
    ext: str
    doc_type: str
    is_ocr_variant: bool
    party: str | None
    justice: str | None
    opinion_type: str | None
    filed_date: str | None  # ISO yyyy-mm-dd


@dataclass(frozen=True)
class Judgment:
    id: int
    case_no: str  # 111年憲判字第6號
    case_name: str | None  # 萊劑殘留標準之權限爭議案
    year: int | None
    number: int | None
    original_case_no: str | None
    decision_date: str | None  # ISO yyyy-mm-dd
    petitioner: str | None
    cause: str | None
    author_note: str | None
    paragraphs: tuple[Paragraph, ...]
    statutes: tuple[Statute, ...]
    related_cases: tuple[RelatedCase, ...]
    attachments: tuple[AttachmentRef, ...]


@dataclass(frozen=True)
class PageText:
    page_no: int  # 1-based
    text: str
    method: str  # "native" | "ocr" | "empty"
    confidence: float | None = None
