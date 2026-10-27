import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from wika_pipeline.io_utils import load_jsonl
from wika_pipeline.review import DECISIONS, read_review_workbook
from wika_pipeline.schema import DictionaryEntry

OPEN_STATUSES = {"extracted", "pending_review", "in_review", "needs_correction"}
STATUS_FOR = {
    "approve": "approved",
    "correct": "approved",
    "reject": "rejected",
    "unsure": "needs_correction",
}
FIELD_FOR_CORRECTION = {"corrected_word": "word", "corrected_meaning": "meaning"}


class ReviewError(Exception):
    def __init__(self, errors):
        super().__init__(f"{len(errors)} problem(s) found")
        self.errors = errors


def load_reviewers(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    reviewers = data.get("reviewers")
    if not isinstance(reviewers, dict) or not reviewers:
        raise ValueError(f"{path}: needs a 'reviewers' mapping with at least one reviewer")
    result = {}
    for reviewer_id, info in reviewers.items():
        info = info or {}
        languages = info.get("languages")
        if not isinstance(languages, list) or not languages:
            raise ValueError(f"{path}: reviewer {reviewer_id} needs a non-empty 'languages' list")
        result[str(reviewer_id)] = {
            "languages": {str(language) for language in languages},
            "active": info.get("active", True) is True,
        }
    return result


def same_text(a, b):
    return (a or "").strip() == (b or "").strip()


def already_applied(entry, row, decision):
    if entry.get("validation_review_status") != STATUS_FOR[decision]:
        return False
    if entry.get("reviewer_id") != row.get("reviewer_id"):
        return False
    if decision == "correct":
        if row.get("corrected_word") and not same_text(entry["word"], row["corrected_word"]):
            return False
        if row.get("corrected_meaning") and not same_text(entry.get("meaning"), row["corrected_meaning"]):
            return False
    return True


def validate_rows(rows, entries_by_id, reviewers):
    actions = []
    errors = []
    skipped = 0
    seen = set()
    for row in rows:
        decision = (row.get("decision") or "").lower()
        if not decision:
            continue
        where = f"row {row['_row']}"
        entry = entries_by_id.get(row.get("entry_id"))
        if entry is None:
            errors.append(f"{where}: entry_id not found in the staged entries (wrong workbook?)")
            continue
        if decision not in DECISIONS:
            errors.append(f"{where}: decision '{decision}' is not one of {', '.join(DECISIONS)}")
            continue
        if row["entry_id"] in seen:
            errors.append(f"{where}: entry appears twice with a decision")
            continue
        seen.add(row["entry_id"])

        reviewer_id = row.get("reviewer_id")
        reviewer = reviewers.get(reviewer_id) if reviewer_id else None
        if not reviewer_id:
            errors.append(f"{where}: reviewer_id is empty")
            continue
        if reviewer is None:
            errors.append(f"{where}: reviewer_id '{reviewer_id}' is not in the reviewers file")
            continue
        if not reviewer["active"]:
            errors.append(f"{where}: reviewer '{reviewer_id}' is not active")
            continue
        if entry["dialect_code"] not in reviewer["languages"]:
            errors.append(f"{where}: reviewer '{reviewer_id}' is not authorised for language '{entry['dialect_code']}'")
            continue

        if entry.get("validation_review_status") not in OPEN_STATUSES:
            if already_applied(entry, row, decision):
                skipped += 1
            else:
                errors.append(
                    f"{where}: entry already has the final status '{entry['validation_review_status']}' "
                    "and this decision would change it"
                )
            continue

        if not same_text(row.get("word"), entry["word"]) or not same_text(row.get("meaning"), entry.get("meaning")):
            errors.append(f"{where}: word or meaning no longer matches the staged entry (workbook edited or out of date)")
            continue

        corrected_word = row.get("corrected_word")
        corrected_meaning = row.get("corrected_meaning")
        if decision == "correct":
            changes_word = corrected_word is not None and not same_text(corrected_word, entry["word"])
            changes_meaning = corrected_meaning is not None and not same_text(corrected_meaning, entry.get("meaning"))
            if not changes_word and not changes_meaning:
                errors.append(f"{where}: decision 'correct' needs a corrected_word or corrected_meaning that differs from the entry")
                continue
        elif corrected_word is not None or corrected_meaning is not None:
            errors.append(f"{where}: corrections are only allowed with the decision 'correct'")
            continue
        if decision in ("reject", "unsure") and not row.get("notes"):
            errors.append(f"{where}: decision '{decision}' needs a reason in notes")
            continue

        actions.append(
            {
                "row": row["_row"],
                "entry_id": row["entry_id"],
                "decision": decision,
                "reviewer_id": reviewer_id,
                "notes": row.get("notes"),
                "corrected_word": corrected_word,
                "corrected_meaning": corrected_meaning,
            }
        )
    return actions, errors, skipped


def apply_actions(entries, actions, now, batch):
    updated = copy.deepcopy(entries)
    index = {entry["entry_id"]: entry for entry in updated}
    events = []
    errors = []
    for action in actions:
        entry = index[action["entry_id"]]
        before_status = entry["validation_review_status"]
        changes = {}
        if action["decision"] == "correct":
            for column, field in FIELD_FOR_CORRECTION.items():
                new_value = action[column]
                if new_value is not None and not same_text(new_value, entry.get(field)):
                    changes[field] = [entry.get(field), new_value]
                    entry[field] = new_value
        entry["validation_review_status"] = STATUS_FOR[action["decision"]]
        entry["reviewer_id"] = action["reviewer_id"]
        entry["reviewed_at"] = now
        entry["review_notes"] = action["notes"]
        try:
            DictionaryEntry.model_validate(entry)
        except Exception as error:
            errors.append(f"row {action['row']}: the updated entry is not valid ({error})")
            continue
        events.append(
            {
                "event_id": str(uuid.uuid4()),
                "batch_id": batch["batch_id"],
                "timestamp": now,
                "entry_id": entry["entry_id"],
                "document_id": entry.get("source_document_id"),
                "language_code": entry["dialect_code"],
                "reviewer_id": action["reviewer_id"],
                "decision": action["decision"],
                "from_status": before_status,
                "to_status": entry["validation_review_status"],
                "changes": changes,
                "notes": action["notes"],
                "workbook": batch["workbook"],
                "workbook_sha256": batch["workbook_sha256"],
            }
        )
    if errors:
        raise ReviewError(errors)
    return updated, events


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_jsonl_atomic(entries, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(path) + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return temp


def append_audit(events, audit_path):
    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_path, "a", encoding="utf-8", newline="\n") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        f.flush()


def run_apply(workbook_path, staging_path, reviewers_path, review_dir, dry_run=False, now=None):
    workbook_path = Path(workbook_path)
    review_dir = Path(review_dir)
    name = workbook_path.name
    suffix = ".review.xlsx"
    if not name.endswith(suffix):
        raise ValueError(f"{name}: expected a file named DOC_ID{suffix}")
    document_id = name[: -len(suffix)]

    reviewed_path = workbook_path.parent / f"{document_id}.reviewed.jsonl"
    base_path = reviewed_path if reviewed_path.exists() else Path(staging_path)
    entries = load_jsonl(base_path)
    if not entries:
        raise ValueError(f"{base_path}: no entries")
    documents = {entry.get("source_document_id") for entry in entries}
    if documents != {document_id}:
        raise ValueError(f"{base_path}: entries belong to {documents}, but the workbook is for {document_id}")

    reviewers = load_reviewers(reviewers_path)
    rows = read_review_workbook(workbook_path)
    entries_by_id = {entry["entry_id"]: entry for entry in entries}
    actions, errors, skipped = validate_rows(rows, entries_by_id, reviewers)
    if errors:
        raise ReviewError(errors)

    counts = {}
    for action in actions:
        counts[action["decision"]] = counts.get(action["decision"], 0) + 1
    summary = {
        "rows_in_workbook": len(rows),
        "rows_without_decision": sum(1 for row in rows if not row.get("decision")),
        "already_applied": skipped,
        "to_apply": len(actions),
        "by_decision": counts,
        "dry_run": dry_run,
        "reviewed_file": str(reviewed_path),
    }
    if dry_run or not actions:
        return summary

    now = now or datetime.now(timezone.utc).isoformat()
    batch = {
        "batch_id": str(uuid.uuid4()),
        "workbook": name,
        "workbook_sha256": sha256_file(workbook_path),
    }
    updated, events = apply_actions(entries, actions, now, batch)
    temp = write_jsonl_atomic(updated, reviewed_path)
    append_audit(events, review_dir / "audit_log.jsonl")
    temp.replace(reviewed_path)
    summary["batch_id"] = batch["batch_id"]
    return summary