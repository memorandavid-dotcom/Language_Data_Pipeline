import pytest

from wika_pipeline.extract import write_pages
from wika_pipeline.inspect_cli import format_page, load_document_pages, show_pages, sparse_pages


def page(number, text, needs_ocr=False):
    return {
        "document_id": "doc_x",
        "source_file": "a.pdf",
        "source_page": number,
        "text": text,
        "char_count": len(text.strip()),
        "needs_ocr": needs_ocr,
    }


def test_format_page_numbers_each_line_and_keeps_text_exact():
    out = format_page(page(7, "baliñgít\n  indented line"))
    assert "page 7" in out
    assert "  1| baliñgít" in out
    assert "  2|   indented line" in out


def test_sparse_pages_lists_flagged_pages_only():
    pages = [page(1, "x", True), page(2, "ok text"), page(3, "", True)]
    assert sparse_pages(pages) == [1, 3]


def test_show_pages_reports_missing_page():
    out = show_pages([page(1, "a")], [1, 5])
    assert "page 5: not in this document" in out


def test_missing_document_gives_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="Run the intake first"):
        load_document_pages("doc_nope", tmp_path)


def test_loads_pages_written_by_the_pipeline(tmp_path):
    write_pages([page(1, "hello")], tmp_path, "doc_x")
    assert load_document_pages("doc_x", tmp_path)[0]["text"] == "hello"