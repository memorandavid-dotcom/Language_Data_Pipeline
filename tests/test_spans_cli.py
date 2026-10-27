import pymupdf

from wika_pipeline.spans_cli import collect_lines, format_line


def make_page_dict(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((54, 80), "headword", fontname="helv", fontsize=10)
    page.insert_text((180, 92), "meaning", fontname="helv", fontsize=10)
    data = page.get_text("dict")
    doc.close()
    return data


def test_collect_lines_returns_only_lines_with_text(tmp_path):
    lines = collect_lines(make_page_dict(tmp_path))
    assert len(lines) == 2


def test_format_line_shows_line_and_span_positions(tmp_path):
    lines = collect_lines(make_page_dict(tmp_path))
    text = format_line(1, lines[0])
    assert "line x=54.0" in text
    assert "span x=54.0" in text
    assert "'headword'" in text