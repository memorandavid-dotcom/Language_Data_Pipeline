import pymupdf

from wika_pipeline.parsers.column_dictionary import parse_pdf

PROFILE = {
    "profile_id": "test_profile",
    "profile_version": "0.0.1",
    "running_title": "TEST DICTIONARY",
    "main_headword_x": 54.0,
    "subentry_indent": 18.0,
    "x_tolerance": 3.0,
    "gloss_min_x": 120.0,
    "y_tolerance": 2.0,
    "min_gloss_share": 0.2,
    "min_headword_share": 0.1,
    "max_unexpected_share": 0.1,
}
DOCUMENT = {
    "document_id": "doc_test",
    "source_file": "test.pdf",
    "language_code": "pag",
    "language_name": "Pangasinan",
    "language_confirmed": True,
}
NOW = "2026-01-01T00:00:00+00:00"


def parse_pages(tmp_path, pages):
    doc = pymupdf.open()
    for number, placed in enumerate(pages, start=1):
        page = doc.new_page()
        for x, y, text in placed:
            page.insert_text((x, y), text, fontname="helv", fontsize=10)
        page.insert_text((144, 760), "TEST DICTIONARY", fontname="helv", fontsize=10)
        page.insert_text((206, 772), str(number), fontname="helv", fontsize=10)
    path = tmp_path / "test.pdf"
    doc.save(path)
    doc.close()
    return parse_pdf(path, PROFILE, DOCUMENT, NOW)


def by_word(entries):
    return {entry["word"]: entry for entry in entries}


NORMAL = [
    (54, 80, "alpha"),
    (180, 80, "first gloss"),
    (54, 92, "beta"),
    (180, 92, "second gloss"),
    (180, 104, "second line"),
]

TWO_UP = [
    (54, 80, "alpha"),
    (180, 80, "first gloss"),
    (54, 92, "beta one two"),
    (54, 104, "three four"),
    (180, 92, "gamma five six"),
    (180, 104, "seven eight"),
    (54, 140, "delta"),
    (180, 140, "last gloss"),
]

WRAPPED_HEADWORD = [
    (54, 80, "alpha"),
    (180, 80, "first gloss"),
    (72, 92, "sub,"),
    (72, 104, "sub two"),
    (198, 92, "shared gloss"),
]


def test_normal_page_has_no_layout_warning(tmp_path):
    entries, report = parse_pages(tmp_path, [NORMAL])
    assert report["page_issues"] == []
    assert all("reading_order_break" not in entry["review_flags"] for entry in entries)


def test_jump_back_up_flags_only_the_interrupted_group(tmp_path):
    entries, report = parse_pages(tmp_path, [TWO_UP])
    flagged = {entry["word"] for entry in entries if "reading_order_break" in entry["review_flags"]}
    assert flagged == {"beta one two", "three four"}
    assert "reading_order_break" not in by_word(entries)["alpha"]["review_flags"]
    assert "reading_order_break" not in by_word(entries)["delta"]["review_flags"]
    assert [issue["page"] for issue in report["page_issues"]] == [1]


def test_wrapped_headword_that_was_joined_is_not_a_break(tmp_path):
    entries, report = parse_pages(tmp_path, [WRAPPED_HEADWORD])
    assert report["page_issues"] == []
    assert all("reading_order_break" not in entry["review_flags"] for entry in entries)
    joined = by_word(entries)["sub, sub two"]
    assert joined["meaning"] == "shared gloss"


def test_only_the_affected_page_is_flagged(tmp_path):
    entries, report = parse_pages(tmp_path, [NORMAL, TWO_UP])
    pages = {entry["source_page"] for entry in entries if "reading_order_break" in entry["review_flags"]}
    assert pages == {2}
    assert [issue["page"] for issue in report["page_issues"]] == [2]


def test_entries_keep_their_order_and_ids_after_the_change(tmp_path):
    first, _ = parse_pages(tmp_path, [NORMAL])
    second, _ = parse_pages(tmp_path, [NORMAL])
    assert [entry["entry_id"] for entry in first] == [entry["entry_id"] for entry in second]
    assert [entry["word"] for entry in first] == ["alpha", "beta"]