import sys

from wika_pipeline.intake import ingest_directory


def main():
    manifest, errors = ingest_directory(
        "data/raw", "config/sources.yml", "data/interim/document_manifest.json"
    )
    print(f"Registered documents: {len(manifest)}")
    for entry in manifest:
        flag = "  [LICENSE NEEDS REVIEW]" if entry["needs_license_review"] else ""
        print(f"  {entry['document_id']}  {entry['source_file']}  pages={entry['page_count']}{flag}")
    if errors:
        print(f"Problems: {len(errors)}")
        for message in errors:
            print(f"  - {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()