import sys

from wika_pipeline.layout import describe_lines, format_report


def parse_args(argv):
    tail = 0
    if "--tail" in argv:
        position = argv.index("--tail")
        try:
            tail = int(argv[position + 1])
        except (IndexError, ValueError):
            raise SystemExit("--tail needs a whole number, for example: --tail 6")
        argv = argv[:position] + argv[position + 2:]
    if len(argv) < 2:
        raise SystemExit(
            'Usage: python -m wika_pipeline.layout_cli "data\\raw\\FILE.pdf" PAGE [PAGE ...] [--tail N]'
        )
    try:
        pages = [int(value) for value in argv[1:]]
    except ValueError:
        raise SystemExit("Page numbers must be whole numbers.")
    return argv[0], pages, tail


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pdf_path, pages, tail = parse_args(argv)
    for page_number in pages:
        try:
            rows = describe_lines(pdf_path, page_number)
        except ValueError as error:
            raise SystemExit(str(error))
        print(format_report(page_number, rows, tail=tail))
        print()


if __name__ == "__main__":
    main(sys.argv[1:])