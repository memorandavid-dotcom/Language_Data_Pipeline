import json

import pymupdf

from wika_pipeline.extract import extract_pages, read_pages, write_pages


def make_pdf(path, page_texts):
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


LONG_TEXT = "baliñgít fragrant word list with enough characters on this page to count as text"


def test_pages_keep_numbers_and_provenance(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [LONG_TEXT, LONG_TEXT])
    pages = extract_pages(pdf, "doc_abc")
    assert [p["source_page"] for p in pages] == [1, 2]
    assert pages[0]["document_id"] == "doc_abc"
    assert pages[0]["source_file"] == "a.pdf"
    assert pages[0]["extraction_method"] == "pymupdf_text"


def test_diacritics_survive_extraction(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [LONG_TEXT])
    assert "baliñgít" in extract_pages(pdf, "doc_abc")[0]["text"]


def test_blank_page_is_flagged_for_ocr(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [LONG_TEXT, ""])
    pages = extract_pages(pdf, "doc_abc")
    assert pages[0]["needs_ocr"] is False
    assert pages[1]["needs_ocr"] is True


def test_written_pages_round_trip_exactly(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [LONG_TEXT])
    pages = extract_pages(pdf, "doc_abc")
    path = write_pages(pages, tmp_path / "pages", "doc_abc")
    assert read_pages(path) == pages


def test_writing_twice_gives_identical_file(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", [LONG_TEXT])
    pages = extract_pages(pdf, "doc_abc")
    first = write_pages(pages, tmp_path / "pages", "doc_abc").read_bytes()
    second = write_pages(pages, tmp_path / "pages", "doc_abc").read_bytes()
    assert first == second
    assert not list((tmp_path / "pages").glob("*.tmp"))
    assert json.loads(first.decode("utf-8").splitlines()[0])["source_page"] == 1