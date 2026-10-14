from pathlib import Path

import pytest

from judicial_mcp.pdf.extract import METHOD_NATIVE, METHOD_SITE_OCR, PdfOpenError, extract_pages
from judicial_mcp.pdf.ocr import is_margin_line_number, observations_to_page, ocr_available, ocr_pages

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_native_opinion():
    pages = extract_pages(FIXTURES / "opinion.pdf")
    assert len(pages) == 13
    assert all(p.method == METHOD_NATIVE for p in pages)
    assert "憲法法庭111年憲判字第6號判決協同意見書" in pages[0].text


def test_extract_site_ocr_brief_cleans_noise():
    pages = extract_pages(FIXTURES / "oral_brief_ocr.pdf", site_ocr=True)
    assert pages[0].method == METHOD_SITE_OCR
    first = pages[0].text
    assert "110年度憲一字第1號" in first
    assert "111年2月22日言詞辯論" in first
    assert not first.startswith("1")


def test_extract_rejects_non_pdf(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(PdfOpenError):
        extract_pages(bad)


def test_margin_line_numbers_are_dropped():
    observations = [
        ("1", 0.9, [0.05, 0.9, 0.02, 0.02]),
        ("解釋憲法聲請書", 0.9, [0.3, 0.9, 0.4, 0.02]),
        ("2", 0.9, [0.05, 0.85, 0.02, 0.02]),
        ("第2條", 0.8, [0.3, 0.85, 0.1, 0.02]),
    ]
    assert is_margin_line_number(observations[0])
    page = observations_to_page(3, observations)
    assert page.page_no == 3
    assert page.text == "解釋憲法聲請書第2條"
    assert page.confidence == pytest.approx(0.85)


def test_observations_empty():
    page = observations_to_page(1, [])
    assert page.text == "" and page.confidence is None


@pytest.mark.skipif(not ocr_available(), reason="Apple Vision OCR not available")
def test_ocr_real_page():
    (page,) = ocr_pages(FIXTURES / "position_table.pdf", [1])
    assert "大法官" in page.text
    assert page.confidence and page.confidence > 0.5


def test_native_extraction_drops_running_line_numbers():
    import pymupdf

    from judicial_mcp.pdf.extract import page_text_without_margin_numbers

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    font = pymupdf.Font("cjk")
    writer = pymupdf.TextWriter(page.rect)
    for i, (num, body) in enumerate([("909", "該規定其立法乃屬逾越"), ("910", "原則參見理由")]):
        y = 100 + i * 20
        writer.append((54, y), num, font=font, fontsize=11)
        writer.append((90, y), body, font=font, fontsize=11)
    writer.write_text(page)
    text = page_text_without_margin_numbers(page)
    assert "909" not in text and "910" not in text
    assert "該規定其立法乃屬逾越" in text
