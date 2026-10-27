import pymupdf

from wika_pipeline.parsers.column_dictionary import needs_continuation, parse_pdf

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


def parse_items(tmp_path, items):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 80
    for x, text in items:
        page.insert_text((x, y), text, fontname="helv", fontsize=10)
        y += 12
    page.insert_text((144, 760), "TEST DICTIONARY", fontname="helv", fontsize=10)
    page.insert_text((206, 772), "1", fontname="helv", fontsize=10)
    path = tmp_path / "test.pdf"
    doc.save(path)
    doc.close()
    entries, _ = parse_pdf(path, PROFILE, DOCUMENT, NOW)
    return entries


def test_needs_continuation_for_trailing_comma_or_open_parenthesis():
    assert needs_continuation("agewagew,")
    assert needs_continuation("kaabay (pl.")
    assert not needs_continuation("kaabay (pl. kabkaabay)")
    assert not needs_continuation("abay")


def test_unclosed_parenthesis_joins_the_next_headword_line(tmp_path):
    entries = parse_items(
        tmp_path,
        [
            (54, "abay"),
            (180, "side"),
            (72, "kaabay (pl."),
            (72, "kabkaabay)"),
            (198, "person close by"),
            (54, "abel"),
            (180, "cloth"),
        ],
    )
    words = [entry["word"] for entry in entries]
    assert words == ["abay", "kaabay (pl. kabkaabay)", "abel"]
    joined = entries[1]
    assert joined["meaning"] == "person close by"
    assert joined["parent_headword"] == "abay"
    assert "headword_continued" in joined["review_flags"]
    assert "complex_headword" in joined["review_flags"]
    assert "no_gloss" not in joined["review_flags"]


def test_trailing_comma_joins_the_next_headword_line(tmp_path):
    entries = parse_items(
        tmp_path,
        [
            (54, "agew"),
            (180, "day"),
            (72, "agewagew,"),
            (72, "inagewagew"),
            (198, "daily"),
        ],
    )
    assert [entry["word"] for entry in entries] == ["agew", "agewagew, inagewagew"]
    assert entries[1]["meaning"] == "daily"


def test_headword_that_already_has_a_gloss_is_not_joined(tmp_path):
    entries = parse_items(
        tmp_path,
        [
            (54, "abay"),
            (180, "side, (man-)"),
            (54, "abel"),
            (180, "cloth"),
        ],
    )
    assert [entry["word"] for entry in entries] == ["abay", "abel"]


def test_different_kinds_are_not_joined(tmp_path):
    entries = parse_items(
        tmp_path,
        [
            (54, "abay,"),
            (72, "kaabay"),
            (198, "neighbor"),
        ],
    )
    assert [entry["word"] for entry in entries] == ["abay,", "kaabay"]
    assert "no_gloss" in entries[0]["review_flags"]