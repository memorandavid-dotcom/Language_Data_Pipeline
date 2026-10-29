import sys
from pathlib import Path

from wika_pipeline.web_wiktionary import (
    WebSourceError,
    build_language,
    category_counts,
    fetch_language,
    load_web_sources,
)

CONFIG = Path("config") / "web_sources.yml"
RAW_DIR = Path("data") / "raw_web"
STAGING_DIR = Path("data") / "staging"
WEB_MANIFEST = Path("data") / "interim" / "web_manifest.json"

USAGE = (
    "Usage:\n"
    "  python -m wika_pipeline.web_cli count\n"
    "  python -m wika_pipeline.web_cli fetch war|cbk [--limit N] [--delay SECONDS]\n"
    "  python -m wika_pipeline.web_cli build war|cbk"
)


def take_number(argv, flag, kind):
    if flag not in argv:
        return argv, None
    position = argv.index(flag)
    try:
        value = kind(argv[position + 1])
    except (IndexError, ValueError):
        raise SystemExit(f"{flag} needs a number")
    return argv[:position] + argv[position + 2:], value


def pick(sources, key):
    if key not in sources:
        raise SystemExit(f"Unknown language '{key}'. Choose from: {', '.join(sources)}")
    return sources[key]


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] not in ("count", "fetch", "build"):
        raise SystemExit(USAGE)
    try:
        sources, license_info = load_web_sources(CONFIG)
        if argv[0] == "count":
            for key, source in sources.items():
                print(f"{key} ({source['language_name']}):")
                for title, count in category_counts(source["categories"]).items():
                    print(f"  {title}: {'category not found' if count is None else str(count) + ' pages'}")
            return
        rest, limit = take_number(argv[1:], "--limit", int)
        rest, delay = take_number(rest, "--delay", float)
        if len(rest) != 1:
            raise SystemExit(USAGE)
        source = pick(sources, rest[0])
        if argv[0] == "fetch":
            def progress(done, total):
                print(f"  {done} of {total} pages downloaded", flush=True)

            stats = fetch_language(rest[0], source, RAW_DIR, limit=limit, delay=0.15 if delay is None else delay, progress=progress)
            print(f"Pages listed: {stats.get('listed', 0)}, already downloaded before: {stats.get('already_done', 0)}")
            print(f"Downloaded now: {stats.get('ok', 0)}, missing on the server: {stats.get('missing', 0)}")
            print("Run it again to continue if it stopped early. Then run the build step.")
            return
        result = build_language(rest[0], source, license_info, RAW_DIR, STAGING_DIR, WEB_MANIFEST)
        print(f"Document id: {result['document_id']}")
        print(f"Pages read: {result['pages']}")
        print(f"Entries: {result['entries']} ({result['unique_words']} different words), flagged for review: {result['flagged']}")
        print(f"Language names seen in the pages: {result['languages_seen']}")
        print(f"Wrote {result['staging']}")
    except (ValueError, WebSourceError, FileNotFoundError) as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main(sys.argv[1:])
