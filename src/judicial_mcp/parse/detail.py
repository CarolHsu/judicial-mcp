"""Parse a judgment detail page (docdata.aspx?fid=38&id=...)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from judicial_mcp.config import BASE_URL
from judicial_mcp.models import AttachmentRef, Judgment, Paragraph, RelatedCase, Statute

_CASE_RE = re.compile(r"(\d{2,3})年憲判字第(\d+)號")
_ROC_DATE_RE = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")
_ROC_COMPACT_RE = re.compile(r"^(1\d{2})(\d{2})(\d{2})$")
_QUOTED_TITLE_RE = re.compile(r"「(.+)」")
_PARAGRAPH_SECTIONS = ("主文", "理由")


class DetailParseError(ValueError):
    """Raised when a page does not look like a judgment detail page."""


def roc_to_iso(raw: str) -> str | None:
    """Convert 111年05月13日 or 1100511 (ROC calendar) to ISO yyyy-mm-dd."""
    text = raw.strip()
    match = _ROC_DATE_RE.search(text) or _ROC_COMPACT_RE.match(text)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year + 1911:04d}-{month:02d}-{day:02d}"


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    collapsed = re.sub(r"[ \t\r\n]+", " ", text).strip()
    return collapsed or None


def _field_rows(tree: HTMLParser) -> dict[str, Node]:
    """Map each `li.title` label to its sibling `li.text` value node."""
    rows: dict[str, Node] = {}
    for ul in tree.css("div.lawList ul.flex"):
        title = ul.css_first("li.title")
        value = ul.css_first("li.text")
        if title is None or value is None:
            continue
        label = _clean(title.text())
        if label and label not in rows:
            rows[label] = value
    return rows


def _paragraphs(rows: dict[str, Node]) -> tuple[Paragraph, ...]:
    result: list[Paragraph] = []
    for section in _PARAGRAPH_SECTIONS:
        node = rows.get(section)
        if node is None:
            continue
        for li in node.css("ul.paragraphs > li"):
            label = li.css_first("label")
            pre = li.css_first("pre")
            if label is None or pre is None:
                continue
            number = _clean(label.text())
            if not number or not number.isdigit():
                continue
            result.append(Paragraph(section=section, para_no=int(number), text=pre.text().strip()))
    return tuple(result)


def _statutes(rows: dict[str, Node]) -> tuple[Statute, ...]:
    node = rows.get("相關法令")
    if node is None:
        return ()
    items = []
    for a in node.css("a"):
        p = a.css_first("p")
        text = _clean(p.text() if p else a.text())
        if text:
            items.append(Statute(text=text, url=a.attributes.get("href")))
    return tuple(items)


def _related(rows: dict[str, Node]) -> tuple[RelatedCase, ...]:
    node = rows.get("併案")
    if node is None:
        return ()
    items = []
    for a in node.css("a"):
        text = _clean(a.text())
        href = a.attributes.get("href")
        if text:
            items.append(RelatedCase(case_no=text, url=urljoin(BASE_URL + "/", href) if href else None))
    return tuple(items)


def _download_id(href: str | None) -> int | None:
    if not href or "download.aspx" not in href:
        return None
    values = parse_qs(urlparse(href).query).get("id")
    if not values or not values[0].isdigit():
        return None
    return int(values[0])


def _attachment_title(a: Node) -> tuple[str, str]:
    """Return (display title, file extension) for a download anchor."""
    quoted = _QUOTED_TITLE_RE.search(a.attributes.get("title") or "")
    filename = quoted.group(1) if quoted else ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    strong = a.css_first("strong")
    title = _clean(strong.text()) if strong else None
    if not title:
        title = filename.rsplit(".", 1)[0] if filename else _clean(a.text()) or ""
    return title, ext


def _group_of(a: Node) -> str | None:
    node = a.parent
    while node is not None and node.tag != "html":
        classes = (node.attributes.get("class") or "").split()
        if node.tag == "div" and "file_list" in classes:
            strong = node.css_first("strong")
            return _clean(strong.text()) if strong else None
        node = node.parent
    return None


def _attachments(rows: dict[str, Node]) -> tuple[AttachmentRef, ...]:
    seen: set[int] = set()
    items: list[AttachmentRef] = []
    for section, node in rows.items():
        for a in node.css("a"):
            doc_id = _download_id(a.attributes.get("href"))
            if doc_id is None or doc_id in seen:
                continue
            seen.add(doc_id)
            title, ext = _attachment_title(a)
            group = _group_of(a)
            items.append(AttachmentRef(doc_id=doc_id, section=section, group=group, title=title, ext=ext))
    return tuple(items)


def _split_case_title(raw: str) -> tuple[str, str | None]:
    match = re.match(r"^(.*?)【(.+)】\s*$", raw)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return raw.strip(), None


def parse_detail(html: str, judgment_id: int) -> Judgment:
    tree = HTMLParser(html)
    rows = _field_rows(tree)
    raw_title = _clean(rows["判決字號"].text()) if "判決字號" in rows else None
    if not raw_title:
        raise DetailParseError(f"judgment {judgment_id}: no 判決字號 field found")
    case_no, case_name = _split_case_title(raw_title)
    case_match = _CASE_RE.search(case_no)
    decision = _clean(rows["判決日期"].text()) if "判決日期" in rows else None

    def field(name: str) -> str | None:
        node = rows.get(name)
        return _clean(node.text()) if node is not None else None

    return Judgment(
        id=judgment_id,
        case_no=case_no,
        case_name=case_name,
        year=int(case_match.group(1)) if case_match else None,
        number=int(case_match.group(2)) if case_match else None,
        original_case_no=field("原分案號"),
        decision_date=roc_to_iso(decision) if decision else None,
        petitioner=field("聲請人"),
        cause=field("案由"),
        author_note=field("主筆大法官記載"),
        paragraphs=_paragraphs(rows),
        statutes=_statutes(rows),
        related_cases=_related(rows),
        attachments=_attachments(rows),
    )
