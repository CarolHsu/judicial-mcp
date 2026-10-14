"""Clean text extracted (or OCR'd) from court filing PDFs.

Court filings are typeset on ruled paper with a margin column of line numbers,
and the site-provided OCR inserts spaces between digits and CJK characters.
These rules undo that so full-text search and quoting work.
"""

from __future__ import annotations

import re
import unicodedata

_CJK = r"　-〿㐀-䶿一-鿿豈-﫿＀-￯"
_MIN_LINE_NUMBER_RUN = 5

# A column of line numbers: "1", "2", ... each alone on its own line.
_NUMBER_COLUMN_RE = re.compile(r"(?:^|(?<=\n))[ \t]*1[ \t]*\n(?:[ \t]*\d{1,2}[ \t]*\n)+")
_UNITS = "年月日號条條項款目頁元萬億千百歲人次件"
# Site OCR splits numbers into single digits ("1 1 1 年"). Only rejoin when that is unambiguous:
# three or more single digits, or digits directly followed by a unit.
_SPACED_DIGITS_RE = re.compile(rf"(?<![\d.])\d(?: \d){{2,}}(?![\d.])|(?<![\d.])\d(?: \d)+(?= ?[{_UNITS}])")
_SPACE_AROUND_CJK_RE = re.compile(rf"(?<=[{_CJK}\d])[ \t ]+(?=[{_CJK}])|(?<=[{_CJK}])[ \t ]+(?=\d)")
_SPACE_INSIDE_BRACKETS_RE = re.compile(r"(?<=[(\[（「『])[ \t]+|[ \t]+(?=[)\]）」』])")
_MEANINGFUL_RE = re.compile(rf"[0-9A-Za-z{_CJK}]")
_FULLWIDTH_SPACE_ONLY_RE = re.compile(r"^[　\s]+$")
_SENTENCE_END = tuple("。！？：」』")
_HEADING_RE = re.compile(
    r"^(?:[壹貳參肆伍陸柒捌玖拾]+、|[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[)）]|\d+[.、]|[A-Za-z][.、])"
)
_INDENT_RE = re.compile(r"^(?:[ \t]{2,}|　)")
_PAGE_NUMBER_LINE_RE = re.compile(r"^[\s\-–—]*(?:第\s*)?\d{1,4}(?:\s*頁)?(?:\s*/\s*\d{1,4})?[\s\-–—]*$")


def _normalize_compat_chars(text: str) -> str:
    """Map Kangxi radicals and CJK compatibility ideographs to unified ideographs."""

    def fix(ch: str) -> str:
        code = ord(ch)
        if 0x2E80 <= code <= 0x2FDF or 0xF900 <= code <= 0xFAFF:
            return unicodedata.normalize("NFKC", ch)
        return ch

    return "".join(fix(ch) for ch in text)


def _strip_line_number_columns(text: str) -> str:
    """Remove margin line-number columns (1, 2, 3, ... on separate lines), keeping other numbers."""

    def replace(match: re.Match[str]) -> str:
        lines = match.group(0).split("\n")[:-1]
        numbers = [int(line) for line in lines]
        run = 1
        while run < len(numbers) and numbers[run] == numbers[run - 1] + 1:
            run += 1
        if run < _MIN_LINE_NUMBER_RUN:
            return match.group(0)
        return "".join(f"{line}\n" for line in lines[run:])

    return _NUMBER_COLUMN_RE.sub(replace, text)


def _clean_line(line: str, site_ocr: bool = False) -> str:
    out = _SPACED_DIGITS_RE.sub(lambda m: m.group(0).replace(" ", ""), line) if site_ocr else line
    out = _SPACE_AROUND_CJK_RE.sub("", out)
    out = _SPACE_INSIDE_BRACKETS_RE.sub("", out)
    return re.sub(r"[ \t ]{2,}", " ", out)


def _starts_paragraph(raw_line: str, cleaned: str) -> bool:
    return bool(_INDENT_RE.match(raw_line) or _HEADING_RE.match(cleaned))


def _join_lines(raw_lines: list[str], site_ocr: bool) -> str:
    paragraphs: list[str] = []
    previous_is_heading = False
    for raw in raw_lines:
        cleaned = _clean_line(raw, site_ocr).strip(" \t　")
        if not cleaned:
            continue
        new_paragraph = (
            not paragraphs
            or _starts_paragraph(raw, cleaned)
            or previous_is_heading
            or paragraphs[-1].endswith(_SENTENCE_END)
        )
        if new_paragraph:
            paragraphs.append(cleaned)
        else:
            last = paragraphs[-1]
            sep = " " if re.search(r"[A-Za-z0-9,.;]$", last) and re.match(r"[A-Za-z0-9]", cleaned) else ""
            paragraphs[-1] = _clean_line(last + sep + cleaned, site_ocr)
        previous_is_heading = bool(_HEADING_RE.match(cleaned)) and len(cleaned) <= 30 and not cleaned.endswith("，")
    return "\n".join(paragraphs)


def clean_page_text(raw: str, *, site_ocr: bool = False) -> str:
    """Clean one page of extracted text.

    `site_ocr` enables digit rejoining, which is only needed for the court site's own OCR layer.
    """
    text = _normalize_compat_chars(raw).replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_line_number_columns(text)
    lines = [
        line
        for line in text.split("\n")
        if _MEANINGFUL_RE.search(line) and not _FULLWIDTH_SPACE_ONLY_RE.match(line)
    ]
    return _join_lines(_strip_edge_page_numbers(lines), site_ocr)


def _strip_edge_page_numbers(lines: list[str]) -> list[str]:
    """Drop page-number lines ("1", "- 2 -", "第3頁", "4/20") at the top or bottom of a page."""
    start, end = 0, len(lines)
    while start < end and _PAGE_NUMBER_LINE_RE.match(lines[start]):
        start += 1
    while end > start and _PAGE_NUMBER_LINE_RE.match(lines[end - 1]):
        end -= 1
    return lines[start:end]
