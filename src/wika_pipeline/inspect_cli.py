import sys
from pathlib import Path

from wika_pipeline.extract import read_pages

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


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in {"sparse", "page"}:
        raise SystemExit(
            "Usage:\n"
            "  python -m wika_pipeline.inspect_cli sparse DOC_ID\n"
            "  python -m wika_pipeline.inspect_cli page DOC_ID PAGE [PAGE ...]"
        )
    command, document_id = argv[0], argv[1]
    pages = load_document_pages(document_id)
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