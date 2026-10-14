"""Per-page text extraction from PDFs, flagging pages that need OCR."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from judicial_mcp.models import PageText
from judicial_mcp.pdf.clean import clean_page_text
from judicial_mcp.pdf.margins import drop_margin_numbers

# A page with fewer meaningful characters than this is treated as image-only.
MIN_TEXT_CHARS = 20
_MEANINGFUL_RE = re.compile(r"[0-9A-Za-z一-鿿]")

METHOD_NATIVE = "native"  # text layer from the original digital document
METHOD_SITE_OCR = "site_ocr"  # text layer from the court site's own OCR (_OCR files)
METHOD_OCR = "ocr"  # our OCR (Apple Vision)
METHOD_PENDING = "pending_ocr"  # no usable text yet; OCR queued


class PdfOpenError(RuntimeError):
    """Raised when a file cannot be opened as a PDF."""


def meaningful_chars(text: str) -> int:
    return len(_MEANINGFUL_RE.findall(text))


def page_text_without_margin_numbers(page: pymupdf.Page) -> str:
    """Page text in reading order, one line per PDF text line, without margin line numbers."""
    lines = [
        line
        for block in page.get_text("dict")["blocks"]
        if block.get("type") == 0
        for line in block["lines"]
    ]
    spans = [span for line in lines for span in line["spans"]]
    kept = {
        id(span)
        for span in drop_margin_numbers(spans, lambda s: s["text"], lambda s: (s["bbox"][0], s["bbox"][2]), page.rect.width)
    }
    rendered = ("".join(span["text"] for span in line["spans"] if id(span) in kept) for line in lines)
    return "\n".join(rendered)


def extract_pages(path: Path, *, site_ocr: bool = False) -> tuple[PageText, ...]:
    """Extract and clean the text layer of every page.

    Pages without enough text are returned with method `pending_ocr` and empty text.
    """
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf raises several exception types
        raise PdfOpenError(f"cannot open {path.name}: {exc}") from exc
    text_method = METHOD_SITE_OCR if site_ocr else METHOD_NATIVE
    with doc:
        pages = []
        for index, page in enumerate(doc, start=1):
            text = clean_page_text(page_text_without_margin_numbers(page), site_ocr=site_ocr)
            if meaningful_chars(text) >= MIN_TEXT_CHARS:
                pages.append(PageText(page_no=index, text=text, method=text_method))
            else:
                pages.append(PageText(page_no=index, text="", method=METHOD_PENDING))
    return tuple(pages)
