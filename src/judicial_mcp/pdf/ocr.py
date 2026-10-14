"""OCR for image-only PDF pages using Apple Vision (macOS) via ocrmac."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import pymupdf

from judicial_mcp.models import PageText
from judicial_mcp.pdf.clean import clean_page_text
from judicial_mcp.pdf.extract import METHOD_OCR

log = logging.getLogger(__name__)

RENDER_DPI = 200
LANGUAGES = ["zh-Hant", "en-US"]
# Vision bbox x is normalized 0..1 from the left edge.
_MARGIN_LEFT = 0.12
_MARGIN_RIGHT = 0.88
_LINE_NUMBER_RE = re.compile(r"^\d{1,2}$")

Observation = tuple[str, float, Sequence[float]]  # (text, confidence, [x, y, w, h])


class OcrUnavailableError(RuntimeError):
    """Raised when no OCR engine is installed on this machine."""


def ocr_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import ocrmac  # noqa: F401
    except ImportError:
        return False
    return True


def is_margin_line_number(obs: Observation) -> bool:
    text, _, bbox = obs
    x, _, w, _ = bbox
    in_margin = x + w <= _MARGIN_LEFT or x >= _MARGIN_RIGHT
    return in_margin and bool(_LINE_NUMBER_RE.match(text.strip()))


def observations_to_page(page_no: int, observations: Sequence[Observation]) -> PageText:
    body = [o for o in observations if not is_margin_line_number(o)]
    raw = "\n".join(o[0] for o in body)
    confidence = sum(o[1] for o in body) / len(body) if body else None
    return PageText(page_no=page_no, text=clean_page_text(raw), method=METHOD_OCR, confidence=confidence)


def _recognize(image: object) -> list[Observation]:
    from ocrmac import ocrmac

    return ocrmac.OCR(image, recognition_level="accurate", language_preference=LANGUAGES).recognize()


def ocr_pages(path: Path, page_numbers: Sequence[int]) -> tuple[PageText, ...]:
    """OCR the given 1-based pages of a PDF."""
    if not ocr_available():
        raise OcrUnavailableError("OCR requires macOS with `ocrmac` installed (uv sync --extra ocr)")
    from PIL import Image

    results = []
    with pymupdf.open(path) as doc:
        for page_no in page_numbers:
            pix = doc[page_no - 1].get_pixmap(dpi=RENDER_DPI)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            results.append(observations_to_page(page_no, _recognize(image)))
    return tuple(results)
