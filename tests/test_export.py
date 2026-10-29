import json

import pytest

from wika_pipeline.export import (
    GateFailure,
    compare_format,
    evaluate_gates,
    export_document,
    load_export_format,
    provenance_row,
    sample_row,
)
from wika_pipeline.schema import DictionaryEntry

FIELDS = ["entry_id", "word", "dialect_code", "dialect_name", "part_of_speech", "meaning", "validation_review_status"]
NOW = "2026-03-01T00:00:00+00:00"


def make_entry(word, meaning="m", status="approved", reviewer="rev_pag", **extra):
    entry = DictionaryEntry(
        entry_id=f"id-{word}",
        word=word,
        dialect_code="pag",
        dialect_name="Pangasinan",
        meaning=meaning,
        original_text=f"{word}\n{meaning}",
        source_document_id="doc_a",
        source_file="a.pdf",
        source_page=5,
        parser_version="p-1",
        review_flags=["complex_headword"],
        validation_review_status=status,
        reviewer_id=reviewer if status == "approved" else None,
        reviewed_at=NOW if status == "approved" else None,
        created_at="2026-01-01T00:00:00+00:00",
        parent_headword=extra.pop("parent_headword", None),
        **extra,
    )
    return entry.model_dump(mode="json")


def good_document(**overrides):
    document = {
        "document_id": "doc_a",
        "source_file": "a.pdf",
        "sha256": "f" * 64,
        "language_code": "pag",
        "language_name": "Pangasinan",
        "language_source": "declared",
        "language_confirmed": True,
        "license_status": "cleared",
        "origin": "publisher site",
        "owner": "Some Press",
    }
    document.update(overrides)
    return document


def audit_for(entries):
    return [
        {"entry_id": e["entry_id"], "to_status": "approved", "reviewer_id": e["reviewer_id"]}
        for e in entries
        if e["validation_review_status"] == "approved"
    ]


def gate(gates, name):
    return next(g for g in gates if g["gate"] == name)


def test_all_gates_pass_for_a_clean_approved_set():
    entries = [make_entry("a"), make_entry("b")]
    gates = evaluate_gates(entries, good_document(), audit_for(entries))
    assert all(g["passed"] for g in gates), [g for g in gates if not g["passed"]]


@pytest.mark.parametrize(
    "document, failing",
    [
        (None, "document_registered"),
        (good_document(language_confirmed=False, language_source="detected"), "language_confirmed"),
        (good_document(license_status="unknown"), "license_cleared"),
        (good_document(license_status="restricted"), "license_cleared"),
        (good_document(origin=None), "license_evidence_recorded"),
        (good_document(owner=""), "license_evidence_recorded"),
        (good_document(language_code="pam"), "language_matches_document"),
        (good_document(document_id="doc_other"), "one_document"),
    ],
)
def test_document_level_gates(document, failing):
    entries = [make_entry("a")]
    gates = evaluate_gates(entries, document, audit_for(entries))
    assert not gate(gates, failing)["passed"]


def test_no_approved_entries_fails():
    entries = [make_entry("a", status="extracted")]
    gates = evaluate_gates(entries, good_document(), [])
    assert not gate(gates, "has_approved_entries")["passed"]


def test_approval_without_an_audit_event_fails():
    entries = [make_entry("a"), make_entry("b")]
    gates = evaluate_gates(entries, good_document(), audit_for(entries[:1]))
    assert not gate(gates, "approved_entries_have_audit_trail")["passed"]


def test_audit_event_by_a_different_reviewer_fails():
    entries = [make_entry("a")]
    audit = [{"entry_id": "id-a", "to_status": "approved", "reviewer_id": "someone_else"}]
    assert not gate(evaluate_gates(entries, good_document(), audit), "approved_entries_have_audit_trail")["passed"]


def test_duplicate_ids_fail():
    entries = [make_entry("a"), make_entry("a")]
    gates = evaluate_gates(entries, good_document(), audit_for(entries))
    assert not gate(gates, "unique_entry_ids")["passed"]


def test_sample_row_has_exactly_the_configured_fields_in_order():
    entry = make_entry("a")
    row = sample_row(entry, FIELDS)
    assert list(row) == FIELDS
    assert row["part_of_speech"] is None
    assert row["validation_review_status"] == "approved"


def test_provenance_row_holds_everything_else_keyed_by_entry_id():
    entry = make_entry("a", parent_headword="main")
    row = provenance_row(entry, FIELDS)
    assert row["entry_id"] == "id-a"
    assert row["source_page"] == 5 and row["parent_headword"] == "main"
    assert row["review_flags"] == ["complex_headword"]
    assert "word" not in row and "meaning" not in row


def test_format_file_rules(tmp_path):
    path = tmp_path / "f.yml"
    path.write_text("fields: [entry_id, word]\n", encoding="utf-8")
    assert load_export_format(path) == ["entry_id", "word"]
    for text in ["fields: []\n", "fields: [word]\n", "fields: [entry_id, nope]\n", "fields: [entry_id, entry_id]\n", "x: 1\n"]:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            load_export_format(path)


def test_compare_format_reports_differences():
    rows = [{"entry_id": 1, "word": "a", "extra": 2}, {"entry_id": 2, "word": "b"}]
    report = compare_format(rows, ["entry_id", "word", "meaning"])
    assert report["only_in_sample"] == ["extra"]
    assert report["only_in_config"] == ["meaning"]
    assert report["rows_with_different_keys"] == 1
    assert report["same_order"] is True


def test_compare_format_detects_a_different_order():
    assert compare_format([{"word": "a", "entry_id": 1}], ["entry_id", "word"])["same_order"] is False


@pytest.fixture
def project(tmp_path):
    entries = [
        make_entry("alpha", "one"),
        make_entry("beta", "two"),
        make_entry("gamma", "three", status="rejected"),
        make_entry("delta", "four", status="extracted"),
    ]
    reviewed = tmp_path / "review" / "pag" / "doc_a.reviewed.jsonl"
    reviewed.parent.mkdir(parents=True)
    reviewed.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([good_document()]), encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    audit.write_text("".join(json.dumps(e) + "\n" for e in audit_for(entries)), encoding="utf-8")
    fmt = tmp_path / "format.yml"
    fmt.write_text("fields: [" + ", ".join(FIELDS) + "]\n", encoding="utf-8")
    return {"reviewed": reviewed, "manifest": manifest, "audit": audit, "format": fmt, "exports": tmp_path / "exports", "entries": entries}


def run(project, **kwargs):
    return export_document(
        project["reviewed"], project["manifest"], project["audit"], project["format"], project["exports"], now=NOW, **kwargs
    )


def test_export_writes_only_approved_entries_in_the_sample_format(project):
    result = run(project)
    folder = project["exports"] / "pag" / "doc_a" / result["export_id"]
    rows = [json.loads(line) for line in (folder / "doc_a.approved.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["word"] for r in rows] == ["alpha", "beta"]
    assert all(list(r) == FIELDS for r in rows)
    assert all(r["validation_review_status"] == "approved" for r in rows)
    provenance = [json.loads(line) for line in (folder / "doc_a.provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [p["entry_id"] for p in provenance] == [r["entry_id"] for r in rows]


def test_manifest_records_counts_hashes_and_gates(project):
    import hashlib

    result = run(project)
    folder = project["exports"] / "pag" / "doc_a" / result["export_id"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries_in_reviewed_file"] == 4
    assert manifest["entries_exported"] == 2
    assert manifest["excluded_by_status"] == {"extracted": 1, "rejected": 1}
    assert manifest["split_group_key"] == "source_document_id"
    assert manifest["reviewer_ids"] == ["rev_pag"]
    assert manifest["source_sha256"] == "f" * 64
    assert all(g["passed"] for g in manifest["gates"])
    for name, info in manifest["files"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == info["sha256"]


def test_the_same_content_is_not_exported_twice(project):
    first = run(project)
    second = run(project)
    assert first["already_exported"] is False and second["already_exported"] is True
    assert first["export_id"] == second["export_id"]
    assert len(list((project["exports"] / "pag" / "doc_a").iterdir())) == 1


def test_changed_content_gets_a_new_export_id(project):
    first = run(project)
    entries = project["entries"]
    entries.append(make_entry("epsilon", "five"))
    project["reviewed"].write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    project["audit"].write_text("".join(json.dumps(e) + "\n" for e in audit_for(entries)), encoding="utf-8")
    second = run(project)
    assert second["export_id"] != first["export_id"]
    assert len(list((project["exports"] / "pag" / "doc_a").iterdir())) == 2


def test_a_failed_gate_writes_nothing(project):
    project["manifest"].write_text(json.dumps([good_document(license_status="unknown")]), encoding="utf-8")
    with pytest.raises(GateFailure) as caught:
        run(project)
    assert any(g["gate"] == "license_cleared" and not g["passed"] for g in caught.value.gates)
    assert not project["exports"].exists()


def test_check_only_writes_nothing_even_when_everything_passes(project):
    result = run(project, check_only=True)
    assert result["approved"] == 2
    assert not project["exports"].exists()


def test_missing_audit_log_blocks_the_export(project):
    project["audit"].unlink()
    with pytest.raises(GateFailure) as caught:
        run(project)
    assert any(g["gate"] == "approved_entries_have_audit_trail" and not g["passed"] for g in caught.value.gates)


def test_document_missing_from_the_manifest_blocks_the_export(project):
    project["manifest"].write_text("[]", encoding="utf-8")
    with pytest.raises(GateFailure):
        run(project)


def test_no_temp_folder_is_left_behind(project):
    run(project)
    names = [p.name for p in (project["exports"] / "pag" / "doc_a").iterdir()]
    assert not any(name.startswith(".tmp") for name in names)