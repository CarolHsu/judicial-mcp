from judicial_mcp.pdf.clean import clean_page_text


def test_removes_margin_line_number_column():
    raw = "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12\n蕙法訴訟言詞辯論意旨（三）書\n案\n號：1 1 0 年度憲一字第1 號"
    out = clean_page_text(raw, site_ocr=True)
    assert not out.startswith("1")
    assert "110年度憲一字第1號" in out


def test_removes_line_number_column_in_middle_of_page():
    raw = "前頁結尾。\n1\n2\n3\n4\n5\n6\n告於鈞庭網頁，該等書狀之提出"
    assert clean_page_text(raw) == "前頁結尾。\n告於鈞庭網頁，該等書狀之提出"


def test_keeps_inline_number_sequences():
    assert clean_page_text("A 1 2 3 4 5 B") == "A 1 2 3 4 5 B"


def test_keeps_number_column_not_starting_at_one():
    out = clean_page_text("附表：\n10\n11\n12\n13\n14\n合計")
    assert "10" in out and "14" in out


def test_keeps_short_number_sequences():
    assert "第1、2、3項" in clean_page_text("依第1、2、3項規定")


def test_joins_spaced_digits_in_site_ocr():
    raw = "( 下同）1 1 1 年2 月1 6 日及2 月2 1 日始送達聲請人"
    assert clean_page_text(raw, site_ocr=True) == "(下同）111年2月16日及2月21日始送達聲請人"


def test_native_text_keeps_spaced_digits():
    assert clean_page_text("第 3 4 項") == "第3 4項"
    assert clean_page_text("附表 10 1 2") == "附表10 1 2"


def test_site_ocr_only_joins_digits_before_units_or_long_runs():
    assert clean_page_text("得處 3 年以下 1 2 萬元", site_ocr=True) == "得處3年以下12萬元"
    assert clean_page_text("附表 10 1 2", site_ocr=True) == "附表10 1 2"
    assert clean_page_text("郵遞區號 1 1 0 2 0 1", site_ocr=True) == "郵遞區號110201"


def test_joins_wrapped_cjk_lines():
    raw = "嘉義市議會（下稱聲請人一）臺北市議會（下稱聲請人\n二）臺南市議會"
    assert clean_page_text(raw) == "嘉義市議會（下稱聲請人一）臺北市議會（下稱聲請人二）臺南市議會"


def test_keeps_paragraph_breaks_after_sentence_end_and_headings():
    raw = "聲請人一至五認有爭議，故聲請憲法解釋。 \n多數意見認為進口肉品\n壹、程序部分 \n    聲請人一及四"
    out = clean_page_text(raw)
    assert out.split("\n") == ["聲請人一至五認有爭議，故聲請憲法解釋。", "多數意見認為進口肉品", "壹、程序部分", "聲請人一及四"]


def test_drops_stray_symbol_lines():
    raw = "前文。\n•\n-\n\\ /\n後文"
    assert clean_page_text(raw) == "前文。\n後文"


def test_keeps_latin_word_spacing():
    raw = "Joint FAO/WHO Expert Committee on Food Additives"
    assert clean_page_text(raw) == raw


def test_normalizes_kangxi_radicals():
    assert clean_page_text("⾏政院") == "行政院"


def test_empty_input():
    assert clean_page_text("  \n \n") == ""


def test_drops_page_number_lines_at_page_edges():
    raw = "1 \n \n憲法法庭111年憲判字第6號判決協同意見書 \n本文。\n- 2 -"
    assert clean_page_text(raw) == "憲法法庭111年憲判字第6號判決協同意見書本文。"


def test_keeps_numbers_inside_page_body():
    raw = "標題\n12\n結尾"
    assert "12" in clean_page_text(raw)
