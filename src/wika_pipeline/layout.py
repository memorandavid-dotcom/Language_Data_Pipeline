from collections import Counter

import pymupdf

BOLD_FLAG = 16
ITALIC_FLAG = 2


def style_of(span):
    name = span["font"]
    bold = bool(span["flags"] & BOLD_FLAG) or "bold" in name.lower()
    italic = bool(span["flags"] & ITALIC_FLAG) or "italic" in name.lower()
    label = f"{name} {round(span['size'], 1)}pt"
    if bold:
        label += " bold"
    if italic:
        label += " italic"
    return label


def rows_from_page_dict(data):
    rows = []
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [span for span in line["spans"] if span["text"].strip()]
            if not spans:
                continue
            rows.append(
                {
                    "x0": round(line["bbox"][0], 1),
                    "y0": round(line["bbox"][1], 1),
                    "text": "".join(span["text"] for span in line["spans"]).strip(),
                    "styles": sorted({style_of(span) for span in spans}),
                    "spans": [{"text": span["text"], "size": round(span["size"], 1)} for span in line["spans"]],
                }
            )
    return rows


def describe_lines(pdf_path, page_number):
    doc = pymupdf.open(pdf_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(f"page {page_number} is outside 1 to {doc.page_count}")
        data = doc[page_number - 1].get_text("dict")
    finally:
        doc.close()
    return rows_from_page_dict(data)


def iter_page_lines(pdf_path):
    doc = pymupdf.open(pdf_path)
    try:
        for index in range(doc.page_count):
            yield index + 1, rows_from_page_dict(doc[index].get_text("dict"))
    finally:
        doc.close()


def summarize(rows):
    styles = Counter(style for row in rows for style in row["styles"])
    left_edges = Counter(round(row["x0"]) for row in rows)
    return styles, left_edges


def format_report(page_number, rows, max_lines=40, tail=0):
    styles, left_edges = summarize(rows)
    letters = {style: chr(ord("A") + index) for index, (style, _) in enumerate(styles.most_common())}

    out = [f"=== page {page_number}: {len(rows)} lines ==="]
    out.append("Styles:")
    for style, count in styles.most_common():
        out.append(f"  {letters[style]} = {style}  ({count} lines)")
    edges = ", ".join(f"x={edge}: {count}" for edge, count in left_edges.most_common(8))
    out.append(f"Left edges: {edges}")
    out.append(f"First {min(max_lines, len(rows))} lines (x, styles, text):")
    for number, row in enumerate(rows[:max_lines], start=1):
        tags = "".join(letters[style] for style in row["styles"])
        out.append(f"{number:3}| x={row['x0']:<6} {tags:<3} {row['text']}")
    if tail > 0 and len(rows) > max_lines:
        start = max(max_lines, len(rows) - tail)
        out.append(f"Last {len(rows) - start} lines:")
        for index in range(start, len(rows)):
            row = rows[index]
            tags = "".join(letters[style] for style in row["styles"])
            out.append(f"{index + 1:3}| x={row['x0']:<6} {tags:<3} {row['text']}")
    return "\n".join(out)