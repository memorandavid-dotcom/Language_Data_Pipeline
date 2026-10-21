import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
import yaml

from wika_pipeline.extract import extract_pages, write_pages
from wika_pipeline.language import detect_language, load_languages

ALLOWED_LICENSE_STATUS = {"cleared", "restricted", "unknown"}
REQUIRED_SOURCE_FIELDS = {"language_code", "language_name", "document_type", "license_status"}


class IntakeError(Exception):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sources(config_path):
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources") or {}


def inspect_pdf(path):
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            raise IntakeError(f"{path.name}: not a PDF file")
    try:
        doc = pymupdf.open(path)
    except Exception as error:
        raise IntakeError(f"{path.name}: cannot be opened ({error})") from error
    try:
        if doc.needs_pass:
            raise IntakeError(f"{path.name}: PDF is password protected")
        if doc.page_count < 1:
            raise IntakeError(f"{path.name}: PDF has no pages")
        return doc.page_count
    finally:
        doc.close()


def stub_source(detection):
    return {
        "language_code": detection["suggested_code"],
        "language_name": detection["suggested_name"],
        "document_type": "unclassified",
        "license_status": "unknown",
        "license_notes": "Auto-registered from detected language. Not yet checked.",
        "origin": None,
        "owner": None,
        "_auto_registered": True,
    }


def build_manifest_entry(pdf_path, source, detection=None, pages=None):
    pdf_path = Path(pdf_path)
    missing = REQUIRED_SOURCE_FIELDS - set(source or {})
    if missing:
        raise IntakeError(f"{pdf_path.name}: sources.yml is missing {sorted(missing)}")
    if source["license_status"] not in ALLOWED_LICENSE_STATUS:
        raise IntakeError(
            f"{pdf_path.name}: license_status must be one of {sorted(ALLOWED_LICENSE_STATUS)}"
        )

    auto_registered = bool(source.get("_auto_registered"))
    if (
        detection
        and detection["confidence"] == "high"
        and not auto_registered
        and detection["suggested_code"] != source["language_code"]
    ):
        raise IntakeError(
            f"{pdf_path.name}: sources.yml says '{source['language_code']}' but the text "
            f"suggests '{detection['suggested_code']}'. Check which one is right."
        )

    page_count = inspect_pdf(pdf_path)
    sha256 = sha256_file(pdf_path)
    return {
        "document_id": "doc_" + sha256[:12],
        "source_file": pdf_path.name,
        "sha256": sha256,
        "size_bytes": pdf_path.stat().st_size,
        "page_count": page_count,
        "language_code": source["language_code"],
        "language_name": source["language_name"],
        "language_source": "detected" if auto_registered else "declared",
        "language_confirmed": not auto_registered,
        "registered_in_sources": not auto_registered,
        "language_detection": detection,
        "pages_with_little_text": (
            sum(1 for page in pages if page["needs_ocr"]) if pages is not None else None
        ),
        "document_type": source["document_type"],
        "license_status": source["license_status"],
        "license_notes": source.get("license_notes"),
        "origin": source.get("origin"),
        "owner": source.get("owner"),
        "needs_license_review": source["license_status"] != "cleared",
        "intake_at": datetime.now(timezone.utc).isoformat(),
    }


def ingest_directory(raw_dir, config_path, manifest_path, languages_path=None, pages_dir=None):
    raw_dir = Path(raw_dir)
    manifest_path = Path(manifest_path)
    sources = load_sources(config_path)
    languages = load_languages(languages_path) if languages_path else None

    existing = {}
    if manifest_path.exists():
        for entry in json.loads(manifest_path.read_text(encoding="utf-8")):
            existing[entry["source_file"]] = entry

    errors = []
    for pdf_path in sorted(raw_dir.glob("*.pdf")):
        try:
            inspect_pdf(pdf_path)
            document_id = "doc_" + sha256_file(pdf_path)[:12]
            pages = detection = None
            if languages is not None:
                pages = extract_pages(pdf_path, document_id)
                detection = detect_language(pages, languages)
        except IntakeError as error:
            errors.append(str(error))
            continue
        except Exception as error:
            errors.append(f"{pdf_path.name}: extraction failed ({error})")
            continue

        source = sources.get(pdf_path.name)
        if source is None:
            if detection is not None and detection["confidence"] == "high":
                source = stub_source(detection)
            elif languages is None:
                errors.append(f"{pdf_path.name}: not registered in sources.yml")
                continue
            else:
                errors.append(
                    f"{pdf_path.name}: not registered in sources.yml and the language "
                    f"could not be detected confidently"
                )
                continue

        try:
            entry = build_manifest_entry(pdf_path, source, detection, pages)
        except IntakeError as error:
            errors.append(str(error))
            continue

        previous = existing.get(pdf_path.name)
        if previous and previous["sha256"] != entry["sha256"]:
            errors.append(f"{pdf_path.name}: file content changed since last intake")
            continue
        if previous:
            entry["intake_at"] = previous["intake_at"]
        if pages is not None and pages_dir is not None:
            write_pages(pages, pages_dir, entry["document_id"])
        existing[pdf_path.name] = entry

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [existing[name] for name in sorted(existing)]
    manifest_path.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return ordered, errors