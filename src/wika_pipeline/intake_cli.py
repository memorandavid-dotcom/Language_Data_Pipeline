import sys

from wika_pipeline.intake import ingest_directory


def describe(entry):
    detection = entry.get("language_detection") or {}
    confidence = detection.get("confidence", "not run")
    parts = [
        entry["document_id"],
        entry["source_file"],
        f"pages={entry['page_count']}",
        f"lang={entry['language_code']} ({entry['language_source']}, detection={confidence})",
        f"little_text_pages={entry['pages_with_little_text']}",
    ]
    text = "  ".join(parts)
    if entry["needs_license_review"]:
        text += "  [LICENSE NEEDS REVIEW]"
    if not entry["language_confirmed"]:
        text += "  [LANGUAGE UNCONFIRMED]"
    return text


def main():
    manifest, errors = ingest_directory(
        "data/raw",
        "config/sources.yml",
        "data/interim/document_manifest.json",
        languages_path="config/languages.yml",
        pages_dir="data/interim/pages",
    )
    print(f"Registered documents: {len(manifest)}")
    for entry in manifest:
        print("  " + describe(entry))

    unconfirmed = [e for e in manifest if not e["registered_in_sources"]]
    if unconfirmed:
        print()
        print("Add these to config/sources.yml to confirm the language and license:")
        for entry in unconfirmed:
            print(f'  "{entry["source_file"]}":')
            print(f"    language_code: {entry['language_code']}")
            print(f"    language_name: {entry['language_name']}")
            print("    document_type: unclassified")
            print("    license_status: unknown")

    if errors:
        print()
        print(f"Problems: {len(errors)}")
        for message in errors:
            print(f"  - {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()