import sys
from collections import Counter
from pathlib import Path

from wika_pipeline.io_utils import load_jsonl
from wika_pipeline.review import entry_to_row, review_path, select_entries, write_review_workbook
from wika_pipeline.review_apply import ReviewError, run_apply

DEFAULT_REVIEW_DIR = Path("data") / "review"
DEFAULT_REVIEWERS = Path("config") / "reviewers.yml"
DEFAULT_STAGING_DIR = Path("data") / "staging"


def export_queue(staging_file, review_dir=DEFAULT_REVIEW_DIR, include_all=False):
    entries = load_jsonl(staging_file)
    if not entries:
        raise ValueError(f"{staging_file}: no entries")
    languages = {entry["dialect_code"] for entry in entries}
    documents = {entry["source_document_id"] for entry in entries}
    if len(languages) != 1 or len(documents) != 1:
        raise ValueError(f"{staging_file}: expected one language and one document, found {languages} / {documents}")
    selected = select_entries(entries, include_all)
    path = review_path(review_dir, languages.pop(), documents.pop())
    if path.exists():
        raise FileExistsError(
            f"{path} already exists. Move or rename it first so that reviewers' work is never overwritten."
        )
    write_review_workbook([entry_to_row(entry) for entry in selected], path)
    flag_counts = Counter(flag for entry in selected for flag in entry.get("review_flags") or [])
    return path, len(entries), len(selected), flag_counts


def apply_command(argv):
    usage = (
        "Usage: python -m wika_pipeline.review_cli apply data\\review\\LANG\\DOC_ID.review.xlsx [--dry-run]"
    )
    dry_run = "--dry-run" in argv
    paths = [value for value in argv if value != "--dry-run"]
    if len(paths) != 1:
        raise SystemExit(usage)
    workbook = Path(paths[0])
    document_id = workbook.name.removesuffix(".review.xlsx")
    staging = DEFAULT_STAGING_DIR / f"{document_id}.entries.jsonl"
    try:
        summary = run_apply(workbook, staging, DEFAULT_REVIEWERS, DEFAULT_REVIEW_DIR, dry_run=dry_run)
    except ReviewError as error:
        print(f"Nothing was applied. {len(error.errors)} problem(s):")
        for message in error.errors[:50]:
            print(f"  {message}")
        if len(error.errors) > 50:
            print(f"  ... and {len(error.errors) - 50} more")
        raise SystemExit(1)
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(str(error))
    label = "Checked only (dry run)" if summary["dry_run"] else "Applied"
    print(f"{label}: {summary['to_apply']} decisions")
    for decision, count in sorted(summary["by_decision"].items()):
        print(f"  {decision}: {count}")
    print(f"Rows without a decision yet: {summary['rows_without_decision']}")
    print(f"Rows already applied earlier: {summary['already_applied']}")
    if not summary["dry_run"] and summary["to_apply"]:
        print(f"Updated {summary['reviewed_file']}")


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if argv and argv[0] == "apply":
        apply_command(argv[1:])
        return
    usage = (
        "Usage:\n"
        "  python -m wika_pipeline.review_cli export data\\staging\\DOC_ID.entries.jsonl [--all]\n"
        "  python -m wika_pipeline.review_cli apply data\\review\\LANG\\DOC_ID.review.xlsx [--dry-run]"
    )
    if len(argv) < 2 or argv[0] != "export":
        raise SystemExit(usage)
    include_all = "--all" in argv[2:]
    extra = [value for value in argv[2:] if value != "--all"]
    if extra:
        raise SystemExit(usage)
    try:
        path, total, selected, flag_counts = export_queue(argv[1], include_all=include_all)
    except (ValueError, FileExistsError, FileNotFoundError) as error:
        raise SystemExit(str(error))
    print(f"{total} entries in the staging file, {selected} written to the review workbook")
    for flag, count in sorted(flag_counts.items()):
        print(f"  {flag}: {count}")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main(sys.argv[1:])