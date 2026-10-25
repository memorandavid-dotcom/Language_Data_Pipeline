import json

import pytest

from wika_pipeline.parse_cli import compact_ranges, find_document, format_entries_for_page


def test_compact_ranges():
    assert compact_ranges([1, 2, 4, 17, 18, 19, 222]) == "1-2, 4, 17-19, 222"
    assert compact_ranges([]) == ""


def test_missing_manifest_gives_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="Run the intake first"):
        find_document("data/raw/a.pdf", tmp_path / "none.json")


def test_unknown_pdf_gives_clear_message(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps([{"source_file": "b.pdf"}]), encoding="utf-8")
    with pytest.raises(SystemExit, match="not in the manifest"):
        find_document("data/raw/a.pdf", manifest)


def test_finds_document_by_file_name(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps([{"source_file": "a.pdf", "document_id": "doc_1"}]), encoding="utf-8")
    assert find_document("data/raw/a.pdf", manifest)["document_id"] == "doc_1"


def test_format_entries_for_page_shows_flags_and_parent():
    entries = [
        {"source_page": 3, "word": "kabinyág", "meaning": "baptized", "parent_headword": "binyág",
         "review_flags": ["no_gloss"]},
        {"source_page": 4, "word": "x", "meaning": "y", "parent_headword": None, "review_flags": []},
    ]
    text = format_entries_for_page(entries, 3)
    assert "kabinyág  =>  baptized" in text
    assert "(under binyág)" in text and "FLAGS: no_gloss" in text
    assert "no entries start" in format_entries_for_page(entries, 9)