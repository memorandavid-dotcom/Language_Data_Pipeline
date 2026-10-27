import sys
from collections import Counter, defaultdict

from wika_pipeline.io_utils import load_jsonl


def count_flags(entries):
    return Counter(flag for entry in entries for flag in entry["review_flags"])


def entries_with_flag(entries, flag):
    return [entry for entry in entries if flag in entry["review_flags"]]

def pages_with_flag(entries, flag):
    counts = Counter(entry["source_page"] for entry in entries if flag in entry["review_flags"])
    return sorted(counts.items())

def find_duplicates(entries):
    groups = defaultdict(list)
    for entry in entries:
        key = (entry["word"], entry["part_of_speech"], entry["meaning"], entry.get("parent_headword"))
        groups[key].append(entry)
    return [group for group in groups.values() if len(group) > 1]


def format_line(entry, width=60):
    meaning = entry["meaning"]
    if meaning is None:
        shown = "(none)"
    elif len(meaning) > width:
        shown = meaning[:width] + "..."
    else:
        shown = meaning
    homograph = f" [{entry['homograph_number']}]" if entry.get("homograph_number") else ""
    return f"p{entry['source_page']:>4} | {entry['word']}{homograph} => {shown}"


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv or len(argv) > 3:
        raise SystemExit(
            "Usage:\n"
            "  python -m wika_pipeline.flags_cli FILE.jsonl             (count each flag)\n"
            "  python -m wika_pipeline.flags_cli FILE.jsonl FLAG [N]    (list up to N entries, default 40)\n"
               "  python -m wika_pipeline.flags_cli FILE.jsonl FLAG pages  (list the pages that have the flag)\n"
            "  python -m wika_pipeline.flags_cli FILE.jsonl duplicates"
        )
    entries = load_jsonl(argv[0])
    if len(argv) == 1:
        counts = count_flags(entries)
        print(f"{len(entries)} entries")
        for flag, count in sorted(counts.items()):
            print(f"  {flag}: {count}")
        return
    what = argv[1]
    if what == "duplicates":
        groups = find_duplicates(entries)
        print(f"{len(groups)} duplicate groups")
        for group in groups:
            for entry in group:
                print(format_line(entry))
            print()
        return
    if len(argv) == 3 and argv[2] == "pages":
        pages = pages_with_flag(entries, what)
        print(f"{len(pages)} pages have entries with the flag '{what}'")
        for page, count in pages:
            print(f"  page {page}: {count} entries")
        return
    try:
        limit = int(argv[2]) if len(argv) == 3 else 40
    except ValueError:
        raise SystemExit("N must be a whole number.")
    matches = entries_with_flag(entries, what)
    print(f"{len(matches)} entries have the flag '{what}' (showing {min(limit, len(matches))})")
    for entry in matches[:limit]:
        print(format_line(entry))


if __name__ == "__main__":
    main(sys.argv[1:])