import sys

from wika_pipeline.language import fold
from wika_pipeline.layout import describe_lines


def matching_numbers(rows, needle, context):
    wanted = fold(needle)
    shown = set()
    for index, row in enumerate(rows):
        if wanted in fold(row["text"]):
            first = max(0, index - context)
            last = min(len(rows) - 1, index + context)
            shown.update(range(first, last + 1))
    return sorted(shown)


def format_matches(page_number, rows, needle, context=4):
    numbers = matching_numbers(rows, needle, context)
    if not numbers:
        return f"=== page {page_number}: no line contains '{needle}' ==="
    out = [f"=== page {page_number}: lines around '{needle}' (x, y, text) ==="]
    previous = None
    for index in numbers:
        if previous is not None and index != previous + 1:
            out.append("   ...")
        row = rows[index]
        out.append(f"{index + 1:3}| x={row['x0']:<6} y={row['y0']:<6} {row['text']}")
        previous = index
    return "\n".join(out)


def parse_args(argv):
    context = 4
    if "--context" in argv:
        position = argv.index("--context")
        try:
            context = int(argv[position + 1])
        except (IndexError, ValueError):
            raise SystemExit("--context needs a whole number, for example: --context 6")
        argv = argv[:position] + argv[position + 2:]
    if len(argv) != 3:
        raise SystemExit(
            'Usage: python -m wika_pipeline.find_cli "data\\raw\\FILE.pdf" PAGE TEXT [--context N]'
        )
    try:
        page_number = int(argv[1])
    except ValueError:
        raise SystemExit("PAGE must be a whole number.")
    return argv[0], page_number, argv[2], context


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pdf_path, page_number, needle, context = parse_args(argv)
    try:
        rows = describe_lines(pdf_path, page_number)
    except ValueError as error:
        raise SystemExit(str(error))
    print(format_matches(page_number, rows, needle, context))


if __name__ == "__main__":
    main(sys.argv[1:])