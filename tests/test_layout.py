import pymupdf
import pytest

from wika_pipeline.layout import describe_lines, format_report, summarize


def make_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "headword", fontname="hebo", fontsize=11)
    page.insert_text((90, 114), "its gloss text", fontname="helv", fontsize=11)
    page.insert_text((72, 128), "other", fontname="hebo", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_lines_report_position_and_style(tmp_path):
    rows = describe_lines(make_pdf(tmp_path / "a.pdf"), 1)
    assert [row["text"] for row in rows] == ["headword", "its gloss text", "other"]
    assert rows[0]["x0"] < rows[1]["x0"]
    assert "bold" in rows[0]["styles"][0]
    assert "bold" not in rows[1]["styles"][0]


def test_summary_counts_styles_and_left_edges(tmp_path):
    rows = describe_lines(make_pdf(tmp_path / "a.pdf"), 1)
    styles, left_edges = summarize(rows)
    assert sorted(styles.values()) == [1, 2]
    assert left_edges[72] == 2


def test_report_has_legend_and_numbered_lines(tmp_path):
    rows = describe_lines(make_pdf(tmp_path / "a.pdf"), 1)
    report = format_report(1, rows)
    assert "A = " in report and "B = " in report
    assert "  1| x=72.0" in report


def test_page_out_of_range_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="outside 1 to 1"):
        describe_lines(make_pdf(tmp_path / "a.pdf"), 5)