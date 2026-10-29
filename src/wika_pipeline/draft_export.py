import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from wika_pipeline.export import find_document, jsonl_bytes, load_export_format, sample_row, sha256_bytes
from wika_pipeline.io_utils import load_jsonl

EXCLUDED_STATUSES = {"rejected", "needs_correction"}

NOTICE = (
    "DRAFT - NOT VALIDATED.\n"
    "These entries were extracted by software. Entries that are not marked approved have not been checked by a "
    "language validator. Do not use this file as approved data, do not train or publish from it, and expect errors.\n"
    "The source book is licensed CC BY-NC-SA 4.0: non-commercial use only, credit the author, and share any "
    "derivative under the same license. See manifest.json for the credit line.\n"
)


def draft_export(entries_path, manifest_path, format_path, drafts_dir, now=None):
    entries = load_jsonl(entries_path)
    if not entries:
        raise ValueError(f"{entries_path}: no entries")
    document_ids = {entry.get("source_document_id") for entry in entries}
    if len(document_ids) != 1:
        raise ValueError(f"{entries_path}: expected one document, found {sorted(map(str, document_ids))}")
    document_id = next(iter(document_ids))

    with open(manifest_path, encoding="utf-8") as f:
        document = find_document(json.load(f), document_id)
    if document is None:
        raise ValueError(f"{document_id} is not in the intake manifest")
    if document.get("license_status") != "cleared" or not document.get("origin") or not document.get("owner"):
        raise ValueError(
            f"{document_id}: the license must be recorded as cleared, with origin and owner, in config/sources.yml "
            "and the intake re-run, before even a draft can be written"
        )
    languages = {entry.get("dialect_code") for entry in entries}
    if languages != {document["language_code"]}:
        raise ValueError(f"entries say {sorted(map(str, languages))}, manifest says {document['language_code']}")

    fields = load_export_format(format_path)
    kept = [entry for entry in entries if entry.get("validation_review_status") not in EXCLUDED_STATUSES]
    skipped = Counter(entry.get("validation_review_status") for entry in entries if entry not in kept)
    dataset = jsonl_bytes([sample_row(entry, fields) for entry in kept])
    flags = jsonl_bytes(
        [
            {
                "entry_id": entry["entry_id"],
                "source_page": entry.get("source_page"),
                "validation_review_status": entry.get("validation_review_status"),
                "review_flags": entry.get("review_flags") or [],
            }
            for entry in kept
        ]
    )
    draft_id = "draft_" + sha256_bytes(dataset + flags)[:12]
    target = Path(drafts_dir) / document["language_code"] / document_id / draft_id
    stats = {
        "entries": len(kept),
        "approved": sum(1 for e in kept if e["validation_review_status"] == "approved"),
        "flagged_for_review": sum(1 for e in kept if e.get("review_flags")),
        "not_yet_reviewed": sum(1 for e in kept if e["validation_review_status"] != "approved"),
        "left_out_by_status": dict(sorted(skipped.items())),
    }
    if target.exists():
        return {"already_exported": True, "path": str(target), "draft_id": draft_id, **stats}

    dataset_name = f"{document_id}.DRAFT-unvalidated.jsonl"
    flags_name = f"{document_id}.DRAFT-flags.jsonl"
    manifest_out = {
        "status": "DRAFT - NOT VALIDATED",
        "draft_id": draft_id,
        "created_at": now or datetime.now(timezone.utc).isoformat(),
        "language_code": document["language_code"],
        "language_name": document["language_name"],
        "document_id": document_id,
        "source_file": document["source_file"],
        "source_sha256": document["sha256"],
        "license_status": document["license_status"],
        "origin": document["origin"],
        "owner": document["owner"],
        "credit_line": f"{document['owner']}. {document['origin']}",
        "fields": fields,
        "counts": stats,
        "files": {
            dataset_name: {"sha256": sha256_bytes(dataset), "rows": len(kept)},
            flags_name: {"sha256": sha256_bytes(flags), "rows": len(kept)},
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".tmp-{draft_id}"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir()
    (temp / dataset_name).write_bytes(dataset)
    (temp / flags_name).write_bytes(flags)
    (temp / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    (temp / "manifest.json").write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.rename(target)
    return {"already_exported": False, "path": str(target), "draft_id": draft_id, **stats}
