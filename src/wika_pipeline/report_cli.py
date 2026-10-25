import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from wika_pipeline.parse_cli import compact_ranges

PERCENT = re.compile(r"(\d+)%")


def group_skips(skipped):
    groups = defaultdict(lambda: {"pages": [], "percents": []})
    for item in skipped:
        reason = item["reason"]
        template = PERCENT.sub("N%", reason)
        groups[template]["pages"].append(item["page"])
        groups[template]["percents"].extend(int(value) for value in PERCENT.findall(reason))
    return groups


def format_skip_report(report):
    skipped = report["pages_skipped"]
    out = [
        f"{report['source_file']}: parsed {report['pages_parsed']} of {report['pages_total']} pages, "
        f"{len(skipped)} skipped"
    ]
    groups = group_skips(skipped)
    for template, group in sorted(groups.items(), key=lambda item: -len(item[1]["pages"])):
        line = f"  [{template}]  {len(group['pages'])} pages"
        if group["percents"]:
            line += f"  (N ranged from {min(group['percents'])}% to {max(group['percents'])}%)"
        out.append(line)
        out.append(f"      pages: {compact_ranges(group['pages'])}")
    if report["page_issues"]:
        out.append(f"Page issues: {len(report['page_issues'])}")
        for issue in report["page_issues"][:10]:
            out.append(f"  page {issue['page']}: {issue['issue']}")
    return "\n".join(out)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) != 1:
        raise SystemExit("Usage: python -m wika_pipeline.report_cli data\\staging\\DOC_ID.parse_report.json")
    path = Path(argv[0])
    if not path.exists():
        raise SystemExit(f"No such report: {path}")
    print(format_skip_report(json.loads(path.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main(sys.argv[1:])