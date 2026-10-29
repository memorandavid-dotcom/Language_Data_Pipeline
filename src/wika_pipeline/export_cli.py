import sys
from pathlib import Path

from wika_pipeline.export import GateFailure, compare_format, export_document, load_export_format
from wika_pipeline.io_utils import load_jsonl

MANIFEST = Path("data") / "interim" / "document_manifest.json"
AUDIT = Path("data") / "review" / "audit_log.jsonl"
FORMAT = Path("config") / "export_format.yml"
EXPORTS = Path("data") / "exports"

USAGE = (
    "Usage:\n"
    "  python -m wika_pipeline.export_cli check data\\review\\LANG\\DOC_ID.reviewed.jsonl\n"
    "  python -m wika_pipeline.export_cli export data\\review\\LANG\\DOC_ID.reviewed.jsonl\n"
    "  python -m wika_pipeline.export_cli check-format samples\\SOMETHING.jsonl"
)


def print_gates(gates):
    for gate in gates:
        mark = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{mark}] {gate['gate']}: {gate['detail']}")


def check_format_command(path):
    fields = load_export_format(FORMAT)
    report = compare_format(load_jsonl(path), fields)
    print(f"{path}: {report['rows']} rows")
    print(f"  Fields only in the sample (not exported): {report['only_in_sample'] or 'none'}")
    print(f"  Fields in {FORMAT} but not in the sample: {report['only_in_config'] or 'none'}")
    print(f"  Same field order: {report['same_order']}")
    print(f"  Rows whose keys differ from the first row: {report['rows_with_different_keys']}")


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) != 2 or argv[0] not in ("check", "export", "check-format"):
        raise SystemExit(USAGE)
    command, path = argv
    try:
        if command == "check-format":
            check_format_command(path)
            return
        result = export_document(path, MANIFEST, AUDIT, FORMAT, EXPORTS, check_only=(command == "check"))
    except GateFailure as failure:
        print("Export refused. Gate results:")
        print_gates(failure.gates)
        raise SystemExit(1)
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(str(error))
    if command == "check":
        print(f"All gates pass. {result['approved']} approved entries would be exported.")
        print_gates(result["gates"])
        return
    if result["already_exported"]:
        print(f"Identical export already exists: {result['path']}")
    else:
        print(f"Exported {result['entries']} approved entries")
        print(f"Wrote {result['path']}")


if __name__ == "__main__":
    main(sys.argv[1:])