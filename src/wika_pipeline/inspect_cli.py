import sys
from pathlib import Path

from wika_pipeline.extract import read_pages
from wika_pipeline.language import fold

PAGES_DIR = Path("data/interim/pages")


def load_document_pages(document_id, pages_dir=PAGES_DIR):
    path = Path(pages_dir) / f"{document_id}.jsonl"
    if not path.exists():
        raise SystemExit(f"No page file for {document_id}. Run the intake first.")
    return read_pages(path)


def sparse_pages(pages):
    return [page["source_page"] for page in pages if page["needs_ocr"]]


def format_page(page):
    lines = page["text"].splitlines()
    header = (
        f"--- {page['source_file']}  page {page['source_page']}  "
        f"chars={page['char_count']}  lines={len(lines)} ---"
    )
    body = [f"{number:3}| {line}" for number, line in enumerate(lines, start=1)]
    return "\n".join([header] + body)


def show_pages(pages, wanted):
    by_number = {page["source_page"]: page for page in pages}
    output = []
    for number in wanted:
        if number not in by_number:
            output.append(f"--- page {number}: not in this document (1 to {len(pages)}) ---")
        else:
            output.append(format_page(by_number[number]))
    return "\n\n".join(output)


def search_pages(pages, terms, context=1, max_page=None):
    wanted = [fold(term) for term in terms]
    results = []
    for page in pages:
        if max_page is not None and page["source_page"] > max_page:
            continue
        lines = page["text"].splitlines()
        hits = [i for i, line in enumerate(lines) if any(term in fold(line) for term in wanted)]
        if not hits:
            continue
        shown = sorted({j for i in hits for j in range(max(0, i - context), min(len(lines), i + context + 1))})
        results.append((page["source_page"], [(j + 1, lines[j]) for j in shown]))
    return results


def format_search(results, limit=15):
    if not results:
        return "No page contains those words."
    out = [f"{len(results)} pages match (showing up to {limit})"]
    for page_number, lines in results[:limit]:
        out.append(f"--- page {page_number} ---")
        previous = None
        for number, text in lines:
            if previous is not None and number != previous + 1:
                out.append("   ...")
            out.append(f"{number:3}| {text}")
            previous = number
    return "\n".join(out)


def parse_search_args(argv):
    context = 1
    max_page = None
    rest = list(argv)
    for flag in ("--context", "--max-page"):
        if flag in rest:
            position = rest.index(flag)
            try:
                value = int(rest[position + 1])
            except (IndexError, ValueError):
                raise SystemExit(f"{flag} needs a whole number")
            rest = rest[:position] + rest[position + 2:]
            if flag == "--context":
                context = value
            else:
                max_page = value
    if not rest:
        raise SystemExit("Give at least one word to search for.")
    return rest, context, max_page


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in {"sparse", "page", "search"}:
        raise SystemExit(
            "Usage:\n"
            "  python -m wika_pipeline.inspect_cli sparse DOC_ID\n"
            "  python -m wika_pipeline.inspect_cli page DOC_ID PAGE [PAGE ...]\n"
            "  python -m wika_pipeline.inspect_cli search DOC_ID WORD [WORD ...] [--context N] [--max-page N]"
        )
    command, document_id = argv[0], argv[1]
    pages = load_document_pages(document_id)
    if command == "search":
        terms, context, max_page = parse_search_args(argv[2:])
        print(format_search(search_pages(pages, terms, context, max_page)))
        return
    if command == "sparse":
        numbers = sparse_pages(pages)
        print(f"{document_id}: {len(numbers)} of {len(pages)} pages have little text")
        print("Pages:", ", ".join(str(n) for n in numbers) or "none")
        return
    try:
        wanted = [int(value) for value in argv[2:]]
    except ValueError:
        raise SystemExit("Page numbers must be whole numbers.")
    if not wanted:
        raise SystemExit("Give at least one page number.")
    print(show_pages(pages, wanted))


if __name__ == "__main__":
    main(sys.argv[1:])
