import sys
from collections import Counter

from pydantic import ValidationError

from wika_pipeline.io_utils import load_jsonl
from wika_pipeline.schema import DictionaryEntry


def audit_rows(rows):
    report = {
        "total_rows": len(rows),
        "schema_invalid": 0,
        "invalid_reasons": Counter(),
        "invalid_line_numbers": [],
        "empty_meaning": 0,
        "exact_duplicates": 0,
        "status_counts": Counter(),
    }
    seen = set()
    for line_no, row in enumerate(rows, start=1):
        try:
            entry = DictionaryEntry(**row)
        except ValidationError as error:
            report["schema_invalid"] += 1
            report["invalid_line_numbers"].append(line_no)
            for item in error.errors():
                report["invalid_reasons"][f"{item['loc'][0]}: {item['type']}"] += 1
            continue

        report["status_counts"][entry.validation_review_status.value] += 1
        if not entry.meaning or not entry.meaning.strip():
            report["empty_meaning"] += 1

        key = (entry.word, entry.part_of_speech, entry.meaning)
        if key in seen:
            report["exact_duplicates"] += 1
        seen.add(key)
    return report


def print_report(path, report):
    print(f"File: {path}")
    print(f"  Total rows:        {report['total_rows']}")
    print(f"  Rejected by schema: {report['schema_invalid']}")
    for reason, count in report["invalid_reasons"].most_common():
        print(f"      {reason}  x{count}")
    shown = report["invalid_line_numbers"][:10]
    if shown:
        print(f"  First rejected line numbers: {shown}")
    print(f"  Empty meaning:     {report['empty_meaning']}")
    print(f"  Exact duplicates:  {report['exact_duplicates']}")
    print(f"  Status counts:     {dict(report['status_counts'])}")


def main(paths):
    for path in paths:
        print_report(path, audit_rows(load_jsonl(path)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python -m wika_pipeline.audit FILE.jsonl [FILE2.jsonl ...]")
    main(sys.argv[1:])