import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from wika_pipeline.io_utils import load_jsonl
from wika_pipeline.schema import DictionaryEntry


class GateFailure(Exception):
    def __init__(self, gates):
        failed = [gate for gate in gates if not gate["passed"]]
        super().__init__(f"{len(failed)} export gate(s) failed")
        self.gates = gates


def load_export_format(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    fields = data.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError(f"{path}: needs a non-empty 'fields' list")
    fields = [str(field) for field in fields]
    if len(set(fields)) != len(fields):
        raise ValueError(f"{path}: 'fields' contains duplicates")
    if "entry_id" not in fields:
        raise ValueError(f"{path}: 'fields' must include entry_id")
    unknown = [field for field in fields if field not in DictionaryEntry.model_fields]
    if unknown:
        raise ValueError(f"{path}: unknown fields {unknown}")
    return fields


def compare_format(sample_rows, fields):
    if not sample_rows:
        raise ValueError("the sample file has no rows")
    first_keys = list(sample_rows[0].keys())
    all_keys = set()
    inconsistent = 0
    for row in sample_rows:
        all_keys.update(row.keys())
        if set(row.keys()) != set(first_keys):
            inconsistent += 1
    return {
        "rows": len(sample_rows),
        "only_in_sample": [key for key in first_keys if key not in fields],
        "only_in_config": [field for field in fields if field not in all_keys],
        "same_order": [key for key in first_keys if key in fields] == [f for f in fields if f in first_keys],
        "rows_with_different_keys": inconsistent,
    }


def load_manifest(paths):
    if isinstance(paths, (str, Path)):
        paths = [paths]
    documents = []
    for path in paths:
        if Path(path).exists():
            with open(path, encoding="utf-8") as f:
                documents += json.load(f)
    return documents


def find_document(manifest, document_id):
    for document in manifest:
        if document.get("document_id") == document_id:
            return document
    return None


def evaluate_gates(entries, document, audit_events):
    gates = []

    def add(name, passed, detail):
        gates.append({"gate": name, "passed": bool(passed), "detail": detail})

    add("document_registered", document is not None, "found in the intake manifest" if document else "document id not in the manifest")
    if document is None:
        return gates

    document_ids = {entry.get("source_document_id") for entry in entries}
    add("one_document", document_ids == {document["document_id"]}, f"entries come from {sorted(map(str, document_ids))}")
    languages = {entry.get("dialect_code") for entry in entries}
    add(
        "language_matches_document",
        languages == {document["language_code"]},
        f"entries say {sorted(map(str, languages))}, manifest says {document['language_code']}",
    )
    add(
        "language_confirmed",
        document.get("language_confirmed") is True,
        f"language_source={document.get('language_source')}, language_confirmed={document.get('language_confirmed')}",
    )
    add("license_cleared", document.get("license_status") == "cleared", f"license_status={document.get('license_status')}")
    add(
        "license_evidence_recorded",
        bool(document.get("origin")) and bool(document.get("owner")),
        f"origin={'set' if document.get('origin') else 'missing'}, owner={'set' if document.get('owner') else 'missing'}",
    )

    approved = [entry for entry in entries if entry.get("validation_review_status") == "approved"]
    add("has_approved_entries", len(approved) > 0, f"{len(approved)} approved of {len(entries)}")

    ids = [entry["entry_id"] for entry in approved]
    add("unique_entry_ids", len(set(ids)) == len(ids), f"{len(ids) - len(set(ids))} repeated ids")

    last_approval = {}
    for event in audit_events:
        if event.get("to_status") == "approved":
            last_approval[event.get("entry_id")] = event
    without_trail = [
        entry["entry_id"]
        for entry in approved
        if not entry.get("reviewer_id")
        or not entry.get("reviewed_at")
        or last_approval.get(entry["entry_id"], {}).get("reviewer_id") != entry.get("reviewer_id")
    ]
    add(
        "approved_entries_have_audit_trail",
        not without_trail,
        f"{len(without_trail)} approved entries have no matching audit event",
    )

    invalid = 0
    for entry in approved:
        try:
            DictionaryEntry.model_validate(entry)
        except Exception:
            invalid += 1
    add("approved_entries_valid", invalid == 0, f"{invalid} approved entries fail the schema")
    return gates


def approval_basis(approved, audit_events):
    last = {}
    for event in audit_events:
        if event.get("to_status") == "approved":
            last[event.get("entry_id")] = event
    counts = Counter(last.get(entry["entry_id"], {}).get("decision", "unknown") for entry in approved)
    return dict(sorted(counts.items()))


def sample_row(entry, fields):
    return {field: entry.get(field) for field in fields}


def provenance_row(entry, fields):
    row = {"entry_id": entry["entry_id"]}
    for name in DictionaryEntry.model_fields:
        if name not in fields and name != "entry_id":
            row[name] = entry.get(name)
    return row


def jsonl_bytes(rows):
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def export_document(reviewed_path, manifest_path, audit_path, format_path, exports_dir, now=None, check_only=False):
    entries = load_jsonl(reviewed_path)
    if not entries:
        raise ValueError(f"{reviewed_path}: no entries")
    document_ids = {entry.get("source_document_id") for entry in entries}
    if len(document_ids) != 1:
        raise ValueError(f"{reviewed_path}: expected one document, found {sorted(map(str, document_ids))}")
    document_id = next(iter(document_ids))

    manifest = load_manifest(manifest_path)
    document = find_document(manifest, document_id)
    audit_events = load_jsonl(audit_path) if Path(audit_path).exists() else []
    fields = load_export_format(format_path)

    gates = evaluate_gates(entries, document, audit_events)
    if not all(gate["passed"] for gate in gates):
        raise GateFailure(gates)
    if check_only:
        return {"gates": gates, "approved": sum(1 for e in entries if e["validation_review_status"] == "approved")}

    approved = [entry for entry in entries if entry["validation_review_status"] == "approved"]
    dataset = jsonl_bytes([sample_row(entry, fields) for entry in approved])
    provenance = jsonl_bytes([provenance_row(entry, fields) for entry in approved])
    export_id = "exp_" + sha256_bytes(dataset + provenance)[:12]

    target = Path(exports_dir) / document["language_code"] / document_id / export_id
    if target.exists():
        return {"already_exported": True, "path": str(target), "export_id": export_id, "entries": len(approved), "gates": gates}

    dataset_name = f"{document_id}.approved.jsonl"
    provenance_name = f"{document_id}.provenance.jsonl"
    excluded = Counter(entry["validation_review_status"] for entry in entries if entry["validation_review_status"] != "approved")
    manifest_out = {
        "export_id": export_id,
        "created_at": now or datetime.now(timezone.utc).isoformat(),
        "language_code": document["language_code"],
        "language_name": document["language_name"],
        "language_confirmed": document["language_confirmed"],
        "document_id": document_id,
        "source_file": document["source_file"],
        "source_sha256": document["sha256"],
        "license_status": document["license_status"],
        "origin": document["origin"],
        "owner": document["owner"],
        "entries_in_reviewed_file": len(entries),
        "entries_exported": len(approved),
        "excluded_by_status": dict(sorted(excluded.items())),
        "approval_basis": approval_basis(approved, audit_events),
        "fields": fields,
        "files": {
            dataset_name: {"sha256": sha256_bytes(dataset), "rows": len(approved)},
            provenance_name: {"sha256": sha256_bytes(provenance), "rows": len(approved)},
        },
        "parser_versions": sorted({entry.get("parser_version") for entry in approved if entry.get("parser_version")}),
        "reviewer_ids": sorted({entry["reviewer_id"] for entry in approved}),
        "split_group_key": "source_document_id",
        "split_note": (
            "Entries from one source document must stay in the same train/dev/test split. "
            "Entries derived from a document (for example its reversed finderlist) belong to the same group."
        ),
        "gates": gates,
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".tmp-{export_id}"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir()
    (temp / dataset_name).write_bytes(dataset)
    (temp / provenance_name).write_bytes(provenance)
    (temp / "manifest.json").write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.rename(target)
    return {"already_exported": False, "path": str(target), "export_id": export_id, "entries": len(approved), "gates": gates}
