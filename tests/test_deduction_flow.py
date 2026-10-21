import json

import pymupdf

from wika_pipeline.intake import ingest_directory

PAG_TEXT = "Pangasinan Dictionary. This is a Pangasinan word list with enough text."

LANGUAGES_YML = """languages:
  pag:
    name: Pangasinan
    aliases: [Pangasinan]
  pam:
    name: Kapampangan
    aliases: [Kapampangan]
"""


def make_pdf(path, texts):
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def setup(tmp_path, texts, sources_yml="sources: {}\n", name="a.pdf"):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_pdf(raw / name, texts)
    (tmp_path / "sources.yml").write_text(sources_yml, encoding="utf-8")
    (tmp_path / "languages.yml").write_text(LANGUAGES_YML, encoding="utf-8")
    return raw


def run(tmp_path, raw):
    return ingest_directory(
        raw,
        tmp_path / "sources.yml",
        tmp_path / "manifest.json",
        languages_path=tmp_path / "languages.yml",
        pages_dir=tmp_path / "pages",
    )


def test_unregistered_pdf_with_clear_language_is_auto_registered_but_unconfirmed(tmp_path):
    raw = setup(tmp_path, [PAG_TEXT, PAG_TEXT, PAG_TEXT])
    manifest, errors = run(tmp_path, raw)
    assert errors == []
    entry = manifest[0]
    assert entry["language_code"] == "pag"
    assert entry["language_source"] == "detected"
    assert entry["language_confirmed"] is False
    assert entry["registered_in_sources"] is False
    assert entry["license_status"] == "unknown"
    assert entry["needs_license_review"] is True


def test_unregistered_pdf_with_no_language_is_refused(tmp_path):
    raw = setup(tmp_path, ["nothing identifying here at all"] * 3)
    manifest, errors = run(tmp_path, raw)
    assert manifest == []
    assert "could not be detected" in errors[0]


def test_declared_language_that_agrees_is_confirmed(tmp_path):
    sources = (
        "sources:\n  a.pdf:\n    language_code: pag\n    language_name: Pangasinan\n"
        "    document_type: dictionary\n    license_status: unknown\n"
    )
    raw = setup(tmp_path, [PAG_TEXT] * 3, sources)
    manifest, errors = run(tmp_path, raw)
    assert errors == []
    assert manifest[0]["language_confirmed"] is True
    assert manifest[0]["language_source"] == "declared"


def test_declared_language_that_contradicts_text_is_an_error(tmp_path):
    sources = (
        "sources:\n  a.pdf:\n    language_code: pam\n    language_name: Kapampangan\n"
        "    document_type: dictionary\n    license_status: unknown\n"
    )
    raw = setup(tmp_path, [PAG_TEXT] * 3, sources)
    manifest, errors = run(tmp_path, raw)
    assert manifest == []
    assert "suggests 'pag'" in errors[0]


def test_declared_language_is_kept_when_detection_is_inconclusive(tmp_path):
    sources = (
        "sources:\n  a.pdf:\n    language_code: pam\n    language_name: Kapampangan\n"
        "    document_type: dictionary\n    license_status: unknown\n"
    )
    raw = setup(tmp_path, ["no language names in this text at all"] * 3, sources)
    manifest, errors = run(tmp_path, raw)
    assert errors == []
    assert manifest[0]["language_code"] == "pam"
    assert manifest[0]["language_detection"]["confidence"] == "none"


def test_pages_file_is_written_and_scanned_pages_counted(tmp_path):
    raw = setup(tmp_path, [PAG_TEXT, PAG_TEXT, ""])
    manifest, errors = run(tmp_path, raw)
    entry = manifest[0]
    assert entry["pages_with_little_text"] == 1
    pages_file = tmp_path / "pages" / f"{entry['document_id']}.jsonl"
    lines = pages_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[2])["needs_ocr"] is True


def test_rerun_is_repeatable(tmp_path):
    raw = setup(tmp_path, [PAG_TEXT] * 3)
    first, _ = run(tmp_path, raw)
    second, errors = run(tmp_path, raw)
    assert errors == []
    assert len(second) == 1
    assert first[0]["intake_at"] == second[0]["intake_at"]