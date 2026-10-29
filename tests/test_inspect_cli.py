import pytest

from wika_pipeline.extract import write_pages
from wika_pipeline.inspect_cli import (
    format_page,
    format_search,
    load_document_pages,
    parse_search_args,
    search_pages,
    show_pages,
    sparse_pages,
)


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


def test_search_finds_words_ignoring_case_and_accents():
    pages = [page(1, "nothing here"), page(2, "line one\nCopyright 1971 by Press\nline three")]
    results = search_pages(pages, ["COPYRÍGHT"], context=0)
    assert results == [(2, [(2, "Copyright 1971 by Press")])]


def test_search_context_and_page_limit():
    pages = [page(1, "a\nb\nlicense\nc\nd"), page(30, "license")]
    results = search_pages(pages, ["license"], context=1, max_page=10)
    assert [number for number, _ in results] == [1]
    assert [n for n, _ in results[0][1]] == [2, 3, 4]


def test_search_output_marks_gaps_and_empty_results():
    pages = [page(1, "license\nx\ny\nz\nrights")]
    text = format_search(search_pages(pages, ["license", "rights"], context=0))
    assert "   ..." in text and "page 1" in text
    assert format_search([]) == "No page contains those words."


def test_search_arguments():
    assert parse_search_args(["copyright", "license"]) == (["copyright", "license"], 1, None)
    assert parse_search_args(["x", "--context", "3", "--max-page", "20"]) == (["x"], 3, 20)
    with pytest.raises(SystemExit):
        parse_search_args(["--context", "3"])
    with pytest.raises(SystemExit):
        parse_search_args(["x", "--max-page"])
