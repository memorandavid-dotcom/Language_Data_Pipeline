import json
from pathlib import Path

import pymupdf

from wika_pipeline.io_utils import load_jsonl

EXTRACTOR_VERSION = "0.1.0"
EXTRACTION_METHOD = "pymupdf_text"
MIN_CHARS_FOR_TEXT_PAGE = 50


def extract_pages(pdf_path, document_id):
    pdf_path = Path(pdf_path)
    pages = []
    doc = pymupdf.open(pdf_path)
    try:
        for page_number, page in enumerate(doc, start=1):
            text = page.get_text("text")
            char_count = len(text.strip())
            pages.append(
                {
                    "document_id": document_id,
                    "source_file": pdf_path.name,
                    "source_page": page_number,
                    "text": text,
                    "char_count": char_count,
                    "needs_ocr": char_count < MIN_CHARS_FOR_TEXT_PAGE,
                    "extraction_method": EXTRACTION_METHOD,
                    "extractor_version": EXTRACTOR_VERSION,
                }
            )
    finally:
        doc.close()
    return pages


def write_pages(pages, pages_dir, document_id):
    path = Path(pages_dir) / f"{document_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".jsonl.tmp")
    with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
        for page in pages:
            f.write(json.dumps(page, ensure_ascii=False) + "\n")
    temp_path.replace(path)
    return path


def read_pages(path):
    return load_jsonl(path)