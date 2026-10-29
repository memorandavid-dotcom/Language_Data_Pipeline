import json

import pytest

from wika_pipeline.draft_export import draft_export
from wika_pipeline.schema import DictionaryEntry

FORMAT = "fields:\n  - entry_id\n  - word\n  - dialect_code\n  - meaning\n  - validation_review_status\n"


def entry(index, status="extracted", flags=None):
    return DictionaryEntry(
        entry_id=f"id-{index}",
        word=f"w{index}",
        dialect_code="pag",
        dialect_name="Pangasinan",
        meaning=f"m{index}",
        original_text=f"w{index}\nm{index}",
        source_document_id="doc_a",
        source_page=1,
        review_flags=flags or [],
        validation_review_status=status,
        created_at="2026-01-01T00:00:00+00:00",
    ).model_dump(mode="json")


def setup(tmp_path, license_status="cleared", entries=None):
    entries = entries if entries is not None else [
        entry(1),
        entry(2, flags=["no_gloss"]),
        entry(3, status="approved"),
        entry(4, status="rejected"),
        entry(5, status="needs_correction"),
    ]
    path = tmp_path / "entries.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc_a",
                    "language_code": "pag",
                    "language_name": "Pangasinan",
                    "source_file": "a.pdf",
                    "sha256": "abc",
                    "license_status": license_status,
                    "origin": "UH Press",
                    "owner": "UH Press; Benton",
                }
            ]
        ),
        encoding="utf-8",
    )
    fmt = tmp_path / "fmt.yml"
    fmt.write_text(FORMAT, encoding="utf-8")
    return path, manifest, fmt


def test_draft_is_written_with_notice_flags_and_counts(tmp_path):
    path, manifest, fmt = setup(tmp_path)
    result = draft_export(path, manifest, fmt, tmp_path / "drafts", now="2026-10-29T00:00:00+00:00")
    assert result["entries"] == 3 and result["approved"] == 1
    assert result["flagged_for_review"] == 1 and result["not_yet_reviewed"] == 2
    assert result["left_out_by_status"] == {"needs_correction": 1, "rejected": 1}
    folder = tmp_path / "drafts" / "pag" / "doc_a" / result["draft_id"]
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["NOTICE.txt", "doc_a.DRAFT-flags.jsonl", "doc_a.DRAFT-unvalidated.jsonl", "manifest.json"]
    rows = [json.loads(line) for line in (folder / "doc_a.DRAFT-unvalidated.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["entry_id"] for r in rows] == ["id-1", "id-2", "id-3"]
    assert list(rows[0].keys()) == ["entry_id", "word", "dialect_code", "meaning", "validation_review_status"]
    assert rows[0]["validation_review_status"] == "extracted"
    meta = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert meta["status"] == "DRAFT - NOT VALIDATED" and "UH Press" in meta["credit_line"]
    assert "DRAFT - NOT VALIDATED" in (folder / "NOTICE.txt").read_text(encoding="utf-8")


def test_draft_is_repeatable_and_does_not_overwrite(tmp_path):
    path, manifest, fmt = setup(tmp_path)
    first = draft_export(path, manifest, fmt, tmp_path / "drafts")
    second = draft_export(path, manifest, fmt, tmp_path / "drafts")
    assert first["already_exported"] is False and second["already_exported"] is True


@pytest.mark.parametrize("status", ["unknown", "restricted"])
def test_draft_needs_a_cleared_license(tmp_path, status):
    path, manifest, fmt = setup(tmp_path, license_status=status)
    with pytest.raises(ValueError, match="license"):
        draft_export(path, manifest, fmt, tmp_path / "drafts")


def test_draft_refuses_a_document_missing_from_the_manifest(tmp_path):
    path, manifest, fmt = setup(tmp_path)
    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="not in the intake manifest"):
        draft_export(path, manifest, fmt, tmp_path / "drafts")


def test_draft_refuses_mixed_documents(tmp_path):
    other = entry(9)
    other["source_document_id"] = "doc_b"
    path, manifest, fmt = setup(tmp_path, entries=[entry(1), other])
    with pytest.raises(ValueError, match="one document"):
        draft_export(path, manifest, fmt, tmp_path / "drafts")
