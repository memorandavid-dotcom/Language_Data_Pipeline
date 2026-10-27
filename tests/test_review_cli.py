import json

import pytest

from wika_pipeline.review import read_review_workbook
from wika_pipeline.review_cli import export_queue


def write_staging(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def make(word, flags, language="pag", document="doc_a"):
    return {
        "entry_id": f"id-{word}",
        "word": word,
        "meaning": "m",
        "source_page": 18,
        "review_flags": flags,
        "original_text": word,
        "dialect_code": language,
        "source_document_id": document,
        "validation_review_status": "extracted",
    }


def test_export_writes_only_flagged_entries_and_counts_flags(tmp_path):
    staging = tmp_path / "doc_a.entries.jsonl"
    write_staging(staging, [make("a", ["no_gloss"]), make("b", []), make("c", ["no_gloss", "complex_headword"])])
    path, total, selected, counts = export_queue(staging, tmp_path / "review")
    assert (total, selected) == (3, 2)
    assert counts == {"no_gloss": 2, "complex_headword": 1}
    assert path == tmp_path / "review" / "pag" / "doc_a.review.xlsx"
    assert [row["word"] for row in read_review_workbook(path)] == ["a", "c"]


def test_export_all_includes_clean_entries(tmp_path):
    staging = tmp_path / "doc_a.entries.jsonl"
    write_staging(staging, [make("a", []), make("b", ["no_gloss"])])
    _, _, selected, _ = export_queue(staging, tmp_path / "review", include_all=True)
    assert selected == 2


def test_existing_review_file_is_never_overwritten(tmp_path):
    staging = tmp_path / "doc_a.entries.jsonl"
    write_staging(staging, [make("a", ["no_gloss"])])
    export_queue(staging, tmp_path / "review")
    with pytest.raises(FileExistsError, match="already exists"):
        export_queue(staging, tmp_path / "review")


def test_mixed_languages_in_one_file_are_refused(tmp_path):
    staging = tmp_path / "x.entries.jsonl"
    write_staging(staging, [make("a", ["no_gloss"], language="pag"), make("b", ["no_gloss"], language="pam")])
    with pytest.raises(ValueError, match="one language and one document"):
        export_queue(staging, tmp_path / "review")


def test_empty_staging_file_is_refused(tmp_path):
    staging = tmp_path / "x.entries.jsonl"
    staging.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no entries"):
        export_queue(staging, tmp_path / "review")