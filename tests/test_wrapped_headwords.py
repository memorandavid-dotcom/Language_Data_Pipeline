import pymupdf

from wika_pipeline.parsers.column_dictionary import (
    is_pronunciation_row,
    needs_continuation,
    parse_pdf,
)

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
LINKERS = ["na", "de", "ya", "a"]
DOCUMENT = {
    "document_id": "doc_test",
    "source_file": "test.pdf",
    "language_code": "pag",
    "language_name": "Pangasinan",
    "language_confirmed": True,
}
NOW = "2026-01-01T00:00:00+00:00"


def parse_placed(tmp_path, placed, linkers=None):
    profile = dict(PROFILE)
    if linkers is not None:
        profile["wrap_linkers"] = linkers
    doc = pymupdf.open()
    page = doc.new_page()
    for x, y, text in placed:
        page.insert_text((x, y), text, fontname="helv", fontsize=10)
    page.insert_text((144, 760), "TEST DICTIONARY", fontname="helv", fontsize=10)
    page.insert_text((206, 772), "1", fontname="helv", fontsize=10)
    path = tmp_path / "test.pdf"
    doc.save(path)
    doc.close()
    entries, report = parse_pdf(path, profile, DOCUMENT, NOW)
    return entries, report


def test_is_pronunciation_row():
    assert is_pronunciation_row("/anghEl/")
    assert is_pronunciation_row("  /hinEbra/ ")
    assert not is_pronunciation_row("/")
    assert not is_pronunciation_row("//")
    assert not is_pronunciation_row("gin /hinEbra/")
    assert not is_pronunciation_row("angel")


def test_pronunciation_line_is_attached_to_the_entry_above(tmp_path):
    entries, report = parse_placed(
        tmp_path,
        [
            (54, 80, "expediente"),
            (54, 92, "/espediente/"),
            (180, 80, "records"),
            (54, 104, "next"),
            (180, 104, "other"),
        ],
    )
    assert [entry["word"] for entry in entries] == ["expediente", "next"]
    first = entries[0]
    assert first["pronunciation_guide"] == "/espediente/"
    assert first["meaning"] == "records"
    assert "no_gloss" not in first["review_flags"]
    assert "reading_order_break" not in first["review_flags"]
    assert report["page_issues"] == []
    assert "/espediente/" in first["original_text"]
    assert entries[1]["pronunciation_guide"] is None


def test_pronunciation_line_after_a_gloss_is_not_attached(tmp_path):
    entries, _ = parse_placed(
        tmp_path,
        [
            (54, 80, "alpha"),
            (180, 80, "gloss"),
            (54, 92, "/stray/"),
            (180, 92, "other"),
        ],
    )
    assert [entry["word"] for entry in entries] == ["alpha", "/stray/"]


def test_needs_continuation_with_linkers():
    assert needs_continuation("arapen na", ["na"])
    assert not needs_continuation("arapen na", [])
    assert not needs_continuation("na", ["na"])
    assert not needs_continuation("kana", ["na"])
    assert not needs_continuation("arapen nab", ["na"])


def test_headword_ending_with_linker_joins_the_next_row(tmp_path):
    entries, report = parse_placed(
        tmp_path,
        [
            (54, 80, "arapen na"),
            (54, 92, "taon"),
            (180, 80, "next year"),
            (54, 104, "other"),
            (180, 104, "x"),
        ],
        LINKERS,
    )
    assert [entry["word"] for entry in entries] == ["arapen na taon", "other"]
    joined = entries[0]
    assert joined["meaning"] == "next year"
    assert "headword_continued" in joined["review_flags"]
    assert "complex_headword" in joined["review_flags"]
    assert "no_gloss" not in joined["review_flags"]
    assert "reading_order_break" not in joined["review_flags"]
    assert report["page_issues"] == []


def test_without_linkers_in_the_profile_nothing_is_joined(tmp_path):
    entries, _ = parse_placed(
        tmp_path,
        [
            (54, 80, "arapen na"),
            (54, 92, "taon"),
            (180, 80, "next year"),
        ],
    )
    assert [entry["word"] for entry in entries] == ["arapen na", "taon"]
    assert "no_gloss" in entries[0]["review_flags"]


def test_a_headword_that_is_only_a_linker_is_not_joined(tmp_path):
    entries, _ = parse_placed(
        tmp_path,
        [
            (54, 80, "a"),
            (54, 92, "b"),
            (180, 92, "gloss"),
        ],
        LINKERS,
    )
    assert [entry["word"] for entry in entries] == ["a", "b"]


def test_a_row_that_only_ends_with_letters_of_a_linker_is_not_joined(tmp_path):
    entries, _ = parse_placed(
        tmp_path,
        [
            (54, 80, "bakasyon kana"),
            (54, 92, "taon"),
            (180, 92, "gloss"),
        ],
        LINKERS,
    )
    assert [entry["word"] for entry in entries] == ["bakasyon kana", "taon"]