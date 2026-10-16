import json

import pymupdf
import pytest

from wika_pipeline.intake import (
    IntakeError,
    build_manifest_entry,
    ingest_directory,
    inspect_pdf,
    sha256_file,
)

SOURCE = {
    "language_code": "pag",
    "language_name": "Pangasinan",
    "document_type": "dictionary",
    "license_status": "unknown",
}


def make_pdf(path, pages=2, text="synthetic test page"):
    doc = pymupdf.open()
    for number in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text} {number + 1}")
    doc.save(path)
    doc.close()
    return path


def write_config(path, name="a.pdf", **overrides):
    source = dict(SOURCE)
    source.update(overrides)
    lines = ["sources:", f"  {name}:"] + [f"    {k}: {v}" for k, v in source.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_hash_is_stable_and_content_sensitive(tmp_path):
    a = make_pdf(tmp_path / "a.pdf")
    assert sha256_file(a) == sha256_file(a)
    b = make_pdf(tmp_path / "b.pdf", text="different")
    assert sha256_file(a) != sha256_file(b)


def test_page_count(tmp_path):
    assert inspect_pdf(make_pdf(tmp_path / "a.pdf", pages=3)) == 3


def test_fake_pdf_is_rejected(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_text("this is not a pdf", encoding="utf-8")
    with pytest.raises(IntakeError, match="not a PDF"):
        inspect_pdf(fake)


def test_manifest_entry_fields(tmp_path):
    entry = build_manifest_entry(make_pdf(tmp_path / "a.pdf"), SOURCE)
    assert entry["document_id"] == "doc_" + entry["sha256"][:12]
    assert entry["page_count"] == 2
    assert entry["needs_license_review"] is True


def test_cleared_license_does_not_need_review(tmp_path):
    source = dict(SOURCE, license_status="cleared")
    assert build_manifest_entry(make_pdf(tmp_path / "a.pdf"), source)["needs_license_review"] is False


def test_missing_required_field_is_rejected(tmp_path):
    source = {k: v for k, v in SOURCE.items() if k != "license_status"}
    with pytest.raises(IntakeError, match="license_status"):
        build_manifest_entry(make_pdf(tmp_path / "a.pdf"), source)


def test_invalid_license_status_is_rejected(tmp_path):
    with pytest.raises(IntakeError, match="license_status must be"):
        build_manifest_entry(make_pdf(tmp_path / "a.pdf"), dict(SOURCE, license_status="maybe"))


def test_unregistered_pdf_is_refused(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_pdf(raw / "a.pdf")
    config = tmp_path / "sources.yml"
    config.write_text("sources: {}\n", encoding="utf-8")
    manifest, errors = ingest_directory(raw, config, tmp_path / "m.json")
    assert manifest == []
    assert "not registered" in errors[0]


def test_reingest_is_repeatable_without_duplicates(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_pdf(raw / "a.pdf")
    config = write_config(tmp_path / "sources.yml")
    manifest_path = tmp_path / "m.json"
    first, _ = ingest_directory(raw, config, manifest_path)
    second, errors = ingest_directory(raw, config, manifest_path)
    assert errors == []
    assert len(second) == 1
    assert first[0]["document_id"] == second[0]["document_id"]
    assert first[0]["intake_at"] == second[0]["intake_at"]
    assert len(json.loads(manifest_path.read_text(encoding="utf-8"))) == 1


def test_changed_file_is_flagged_and_old_entry_kept(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_pdf(raw / "a.pdf")
    config = write_config(tmp_path / "sources.yml")
    manifest_path = tmp_path / "m.json"
    first, _ = ingest_directory(raw, config, manifest_path)
    make_pdf(raw / "a.pdf", text="edited")
    second, errors = ingest_directory(raw, config, manifest_path)
    assert "changed" in errors[0]
    assert second[0]["sha256"] == first[0]["sha256"]