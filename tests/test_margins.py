from judicial_mcp.pdf.margins import drop_margin_numbers
from judicial_mcp.pdf.ocr import observations_to_page


def items(*rows):
    return [{"text": t, "x0": a, "x1": b} for t, a, b in rows]


def keep(rows, width=595):
    out = drop_margin_numbers(rows, lambda r: r["text"], lambda r: (r["x0"], r["x1"]), width)
    return [r["text"] for r in out]


def test_drops_running_line_numbers_left_of_body():
    rows = items(("909 ", 54, 75), ("該規定其立法乃屬逾越", 90, 505), ("910", 54, 75), ("原則參見理由", 90, 505))
    assert keep(rows) == ["該規定其立法乃屬逾越", "原則參見理由"]


def test_keeps_numbers_inside_body_and_centered_page_number():
    rows = items(("第81段", 90, 140), ("7", 300, 305), ("37", 293, 305), ("本文內容", 90, 505))
    assert keep(rows) == ["第81段", "7", "37", "本文內容"]


def test_drops_right_margin_numbers():
    rows = items(("本文內容", 90, 505), ("12", 520, 530))
    assert keep(rows) == ["本文內容"]


def test_no_body_text_keeps_everything():
    rows = items(("1", 10, 20), ("2", 10, 20))
    assert keep(rows) == ["1", "2"]


def test_vision_observations_with_numbers_just_past_fixed_margin():
    observations = [
        ("909", 0.9, [0.09, 0.9, 0.036, 0.02]),  # ends at 0.126, beyond the old 0.12 band
        ("該規定其立法乃屬逾越", 0.9, [0.151, 0.9, 0.7, 0.02]),
        ("910", 0.9, [0.09, 0.87, 0.036, 0.02]),
        ("原則參見理由", 0.9, [0.151, 0.87, 0.7, 0.02]),
    ]
    assert observations_to_page(1, observations).text == "該規定其立法乃屬逾越原則參見理由"
