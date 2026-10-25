import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from wika_pipeline.parsers.column_dictionary import load_profile, parse_pdf, write_outputs

MANIFEST_PATH = Path("data/interim/document_manifest.json")
STAGING_DIR = Path("data/staging")


def compact_ranges(numbers):
    ranges = []
    for number in sorted(numbers):
        if ranges and number == ranges[-1][1] + 1:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def find_document(pdf_path, manifest_path=MANIFEST_PATH):
    if not Path(manifest_path).exists():
        raise SystemExit("No manifest found. Run the intake first.")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    for entry in manifest:
        if entry["source_file"] == Path(pdf_path).name:
            return entry
    raise SystemExit(f"{Path(pdf_path).name} is not in the manifest. Run the intake first.")


def format_entries_for_page(entries, page_number):
    on_page = [e for e in entries if e["source_page"] == page_number]
    if not on_page:
        return f"--- page {page_number}: no entries start on this page ---"
    lines = [f"--- page {page_number}: {len(on_page)} entries start here ---"]
    for number, entry in enumerate(on_page, start=1):
        parent = f"  (under {entry['parent_headword']})" if entry["parent_headword"] else ""
        flags = f"  FLAGS: {', '.join(entry['review_flags'])}" if entry["review_flags"] else ""
        lines.append(f"{number:3}| {entry['word']}  =>  {entry['meaning']}{parent}{flags}")
    return "\n".join(lines)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2:
        raise SystemExit(
            'Usage: python -m wika_pipeline.parse_cli "data\\raw\\FILE.pdf" PROFILE.yml '
            "[--show-page N ...]"
        )
    pdf_path, profile_path = argv[0], argv[1]
    show_pages = []
    if len(argv) > 2:
        if argv[2] != "--show-page":
            raise SystemExit("Unknown option. Use --show-page N [N ...]")
        try:
            show_pages = [int(value) for value in argv[3:]]
        except ValueError:
            raise SystemExit("Page numbers must be whole numbers.")

    profile = load_profile(profile_path)
    document = find_document(pdf_path)
    created_at = datetime.now(timezone.utc).isoformat()
    entries, report = parse_pdf(pdf_path, profile, document, created_at)
    entries_path, report_path = write_outputs(entries, report, STAGING_DIR)

    print(f"Parsed {report['pages_parsed']} of {report['pages_total']} pages")
    skipped_pages = [item["page"] for item in report["pages_skipped"]]
    print(f"Pages skipped: {compact_ranges(skipped_pages) or 'none'}")
    print(f"Page issues: {len(report['page_issues'])}")
    print(f"Entries: {report['entries_total']}  (with flags: {report['entries_with_flags']})")
    for flag, count in report["flag_counts"].items():
        print(f"    {flag}: {count}")
    parsed_pages = sorted({e["source_page"] for e in entries})
    if parsed_pages:
        picks = sorted({parsed_pages[0], parsed_pages[len(parsed_pages) // 2], parsed_pages[-1]})
        print(f"Check these pages by hand against the PDF: {picks}")
    print(f"Wrote {entries_path}")
    print(f"Wrote {report_path}")
    for page_number in show_pages:
        print()
        print(format_entries_for_page(entries, page_number))


if __name__ == "__main__":
    main(sys.argv[1:])