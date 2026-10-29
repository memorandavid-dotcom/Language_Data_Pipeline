import hashlib
import json
import math
import random
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from wika_pipeline.io_utils import load_jsonl
from wika_pipeline.review import entry_to_row, write_review_workbook
from wika_pipeline.review_apply import OPEN_STATUSES, append_audit, load_reviewers, write_jsonl_atomic
from wika_pipeline.schema import DictionaryEntry


class SamplingError(Exception):
    def __init__(self, problems):
        super().__init__(f"{len(problems)} problem(s) found")
        self.problems = problems


def load_policy(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    policy = {}
    for key in ("max_error_rate", "confidence"):
        value = data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value < 1:
            raise ValueError(f"{path}: '{key}' must be a number between 0 and 1")
        policy[key] = float(value)
    return policy


def required_sample_size(max_error_rate, confidence):
    return math.ceil(math.log(1 - confidence) / math.log(1 - max_error_rate))


def population_of(entries):
    return [
        entry
        for entry in entries
        if not entry.get("review_flags") and entry.get("validation_review_status") in OPEN_STATUSES
    ]


def stratified_pick(ids, size, seed):
    rng = random.Random(seed)
    total = len(ids)
    picks = []
    for index in range(size):
        low = index * total // size
        high = (index + 1) * total // size
        picks.append(ids[rng.randrange(low, high)])
    return picks


def ids_hash(ids):
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def audits_dir(review_dir, language_code):
    return Path(review_dir) / language_code / "audits"


def write_json_atomic(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(path) + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_base_entries(staging_path, review_dir):
    entries = load_jsonl(staging_path)
    if not entries:
        raise ValueError(f"{staging_path}: no entries")
    languages = {entry["dialect_code"] for entry in entries}
    documents = {entry["source_document_id"] for entry in entries}
    if len(languages) != 1 or len(documents) != 1:
        raise ValueError(f"{staging_path}: expected one language and one document")
    language, document = next(iter(languages)), next(iter(documents))
    reviewed = Path(review_dir) / language / f"{document}.reviewed.jsonl"
    if reviewed.exists():
        entries = load_jsonl(reviewed)
    return entries, language, document, reviewed


def create_sample(staging_path, review_dir, policy, seed=None, now=None):
    entries, language, document, _ = load_base_entries(staging_path, review_dir)
    folder = audits_dir(review_dir, language)
    for existing in sorted(folder.glob(f"{document}.*.json")) if folder.exists() else []:
        if json.loads(existing.read_text(encoding="utf-8")).get("status") == "open":
            raise ValueError(f"{existing.name} is still open. Conclude it before starting another sample.")

    population = population_of(entries)
    ids = [entry["entry_id"] for entry in population]
    size = required_sample_size(policy["max_error_rate"], policy["confidence"])
    if len(ids) <= size:
        raise ValueError(
            f"Only {len(ids)} unflagged entries are still open, and a sample needs {size}. "
            "At this size reviewing all of them is simpler than sampling."
        )
    seed = secrets.randbelow(2**31) if seed is None else seed
    picks = stratified_pick(ids, size, seed)
    population_hash = ids_hash(ids)
    sample_id = "aud_" + hashlib.sha256(f"{document}:{seed}:{population_hash}".encode("utf-8")).hexdigest()[:10]

    workbook = Path(review_dir) / language / f"{document}.audit-{sample_id}.review.xlsx"
    if workbook.exists():
        raise FileExistsError(f"{workbook} already exists.")
    picked = set(picks)
    write_review_workbook([entry_to_row(entry) for entry in population if entry["entry_id"] in picked], workbook)

    manifest = {
        "sample_id": sample_id,
        "status": "open",
        "document_id": document,
        "language_code": language,
        "created_at": now or datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "method": "one random entry from each of N equal slices of the unflagged entries in book order",
        "policy": policy,
        "errors_allowed_in_sample": 0,
        "population_size": len(ids),
        "population_ids_sha256": population_hash,
        "population_ids": ids,
        "sample_size": len(picks),
        "sample_ids": picks,
        "sample_pages": sorted({e["source_page"] for e in population if e["entry_id"] in picked}),
        "workbook": workbook.name,
    }
    manifest_path = folder / f"{document}.{sample_id}.json"
    write_json_atomic(manifest, manifest_path)
    return {"manifest": manifest, "manifest_path": manifest_path, "workbook": workbook}


def latest_events(audit_path):
    latest = {}
    if Path(audit_path).exists():
        for event in load_jsonl(audit_path):
            latest[event["entry_id"]] = event
    return latest


def conclude_sample(manifest_path, approver, reviewers_path, review_dir, dry_run=False, now=None):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["status"] != "open":
        raise ValueError(f"{manifest_path.name} is already {manifest['status']}.")
    language, document = manifest["language_code"], manifest["document_id"]

    reviewers = load_reviewers(reviewers_path)
    person = reviewers.get(approver)
    if person is None or not person["active"] or language not in person["languages"]:
        raise ValueError(f"'{approver}' must be an active reviewer authorised for language '{language}'.")

    reviewed_path = Path(review_dir) / language / f"{document}.reviewed.jsonl"
    if not reviewed_path.exists():
        raise ValueError("No decisions have been applied yet. Run review_cli apply on the sample workbook first.")
    entries = load_jsonl(reviewed_path)
    by_id = {entry["entry_id"]: entry for entry in entries}

    population_ids = manifest["population_ids"]
    if ids_hash(population_ids) != manifest["population_ids_sha256"]:
        raise ValueError("The sample manifest was edited: its population list no longer matches its fingerprint.")
    missing = [entry_id for entry_id in population_ids if entry_id not in by_id]
    if missing:
        raise ValueError(f"{len(missing)} entries from the sampled population are not in the reviewed file (was the data re-parsed?).")
    if manifest["sample_size"] < required_sample_size(manifest["policy"]["max_error_rate"], manifest["policy"]["confidence"]):
        raise ValueError("The recorded sample is smaller than the policy requires.")

    latest = latest_events(Path(review_dir) / "audit_log.jsonl")
    problems = []
    errors = 0
    for entry_id in manifest["sample_ids"]:
        entry = by_id[entry_id]
        if entry["validation_review_status"] in OPEN_STATUSES:
            problems.append(f"{entry['word']} (page {entry['source_page']}): no decision applied yet")
            continue
        event = latest.get(entry_id)
        if event is None:
            problems.append(f"{entry['word']} (page {entry['source_page']}): decided but not in the audit log")
        elif event["decision"] != "approve":
            errors += 1
    if problems:
        raise SamplingError(problems)

    now = now or datetime.now(timezone.utc).isoformat()
    sample_set = set(manifest["sample_ids"])
    result = {
        "sample_size": manifest["sample_size"],
        "errors_found": errors,
        "population_size": manifest["population_size"],
        "dry_run": dry_run,
    }
    if errors:
        result["outcome"] = "failed"
        if not dry_run:
            manifest.update(status="failed", concluded_at=now, concluded_by=approver, errors_found=errors)
            write_json_atomic(manifest, manifest_path)
        return result

    targets = [
        by_id[entry_id]
        for entry_id in population_ids
        if entry_id not in sample_set and by_id[entry_id]["validation_review_status"] in OPEN_STATUSES
    ]
    result["outcome"] = "passed"
    result["to_approve"] = len(targets)
    if dry_run:
        return result

    policy = manifest["policy"]
    note = (
        f"Approved in bulk after audit sample {manifest['sample_id']}: {manifest['sample_size']} of "
        f"{manifest['population_size']} unflagged entries checked, {errors} errors "
        f"(policy: error rate at most {policy['max_error_rate']:.1%} at {policy['confidence']:.0%} confidence)."
    )
    batch_id = str(uuid.uuid4())
    target_ids = {entry["entry_id"] for entry in targets}
    updated = []
    events = []
    for entry in entries:
        if entry["entry_id"] in target_ids:
            before = entry["validation_review_status"]
            entry = dict(entry)
            entry.update(
                validation_review_status="approved", reviewer_id=approver, reviewed_at=now, review_notes=note
            )
            DictionaryEntry.model_validate(entry)
            events.append(
                {
                    "event_id": str(uuid.uuid4()),
                    "batch_id": batch_id,
                    "timestamp": now,
                    "entry_id": entry["entry_id"],
                    "document_id": document,
                    "language_code": language,
                    "reviewer_id": approver,
                    "decision": "bulk_approve",
                    "from_status": before,
                    "to_status": "approved",
                    "changes": {},
                    "notes": note,
                    "audit_sample_id": manifest["sample_id"],
                    "workbook": manifest["workbook"],
                    "workbook_sha256": None,
                }
            )
        updated.append(entry)
    temp = write_jsonl_atomic(updated, reviewed_path)
    append_audit(events, Path(review_dir) / "audit_log.jsonl")
    temp.replace(reviewed_path)
    manifest.update(status="passed", concluded_at=now, concluded_by=approver, errors_found=0, bulk_approved=len(events))
    write_json_atomic(manifest, manifest_path)
    result["approved"] = len(events)
    return result


def create_full_review(manifest_path, review_dir):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["status"] != "failed":
        raise ValueError(f"A full review is only needed after a failed sample; this one is '{manifest['status']}'.")
    language, document = manifest["language_code"], manifest["document_id"]
    entries = load_jsonl(Path(review_dir) / language / f"{document}.reviewed.jsonl")
    population = set(manifest["population_ids"])
    remaining = [
        entry for entry in entries if entry["entry_id"] in population and entry["validation_review_status"] in OPEN_STATUSES
    ]
    workbook = Path(review_dir) / language / f"{document}.full-{manifest['sample_id']}.review.xlsx"
    if workbook.exists():
        raise FileExistsError(f"{workbook} already exists.")
    write_review_workbook([entry_to_row(entry) for entry in remaining], workbook)
    return workbook, len(remaining)
