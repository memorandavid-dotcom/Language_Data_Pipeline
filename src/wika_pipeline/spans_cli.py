import sys

import pymupdf


def collect_lines(page_dict):
    lines = []
    for block in page_dict["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [span for span in line["spans"] if span["text"].strip()]
            if spans:
                lines.append(line)
    return lines


def format_line(number, line):
    x0, y0, x1, _ = line["bbox"]
    out = [f"{number:>3}| line x={x0:.1f}..{x1:.1f} y={y0:.1f}"]
    for span in line["spans"]:
        if not span["text"].strip():
            continue
        sx0, _, sx1, _ = span["bbox"]
        out.append(f"       span x={sx0:.1f}..{sx1:.1f} size={span['size']:.1f}  {span['text']!r}")
    return "\n".join(out)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) != 4:
        raise SystemExit(
            'Usage: python -m wika_pipeline.spans_cli "data\\raw\\FILE.pdf" PAGE FIRST_LINE LAST_LINE'
        )
    pdf_path = argv[0]
    try:
        page_number, first, last = (int(value) for value in argv[1:])
    except ValueError:
        raise SystemExit("PAGE, FIRST_LINE and LAST_LINE must be whole numbers.")
    doc = pymupdf.open(pdf_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise SystemExit(f"page {page_number} is outside 1 to {doc.page_count}")
        lines = collect_lines(doc[page_number - 1].get_text("dict"))
    finally:
        doc.close()
    print(f"=== page {page_number}: {len(lines)} lines, showing {first} to {last} ===")
    for number, line in enumerate(lines, start=1):
        if first <= number <= last:
            print(format_line(number, line))


if __name__ == "__main__":
    main(sys.argv[1:])