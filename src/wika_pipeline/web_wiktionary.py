import hashlib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import yaml

from wika_pipeline.schema import DictionaryEntry

API = "https://en.wiktionary.org/w/api.php"
REST = "https://en.wiktionary.org/api/rest_v1/page/definition/"
PAGE_URL = "https://en.wiktionary.org/wiki/"
USER_AGENT = "WIKA-pipeline/0.1 (language data research; contact: project maintainer)"
EXTRACTION_METHOD = "wiktionary_rest_definition"
PARSER_VERSION = "wiktionary-web/0.1.0"
VOID_TAGS = {"link", "br", "img", "meta", "hr", "input"}
FORM_OF = re.compile(r"\b(alternative|alternate|obsolete|nonstandard|dialectal|informal)?\s*(form|spelling|plural|variant|misspelling) of\b", re.I)


class WebSourceError(Exception):
    pass


def load_web_sources(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    sources = data.get("sources")
    license_info = data.get("license")
    if not isinstance(sources, dict) or not sources:
        raise ValueError(f"{path}: needs a 'sources' section")
    if not isinstance(license_info, dict):
        raise ValueError(f"{path}: needs a 'license' section")
    for key in ("license_status", "license_name", "origin", "owner"):
        if not license_info.get(key):
            raise ValueError(f"{path}: license.{key} is missing")
    for code, source in sources.items():
        for key in ("language_code", "language_name"):
            if not source.get(key):
                raise ValueError(f"{path}: {code}.{key} is missing")
        for key in ("wiktionary_languages", "categories"):
            if not isinstance(source.get(key), list) or not source[key]:
                raise ValueError(f"{path}: {code}.{key} must be a non-empty list")
    return sources, license_info


def make_ssl_context():
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def http_get_json(url, retries=5, pause=2.0):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30, context=make_ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(pause * (attempt + 1) * (3 if error.code == 429 else 1))
                continue
            raise WebSourceError(f"{url}: HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if isinstance(getattr(error, "reason", None), ssl.SSLCertVerificationError):
                raise WebSourceError(
                    f"{url}: the certificate could not be verified ({error.reason}). "
                    "Run: pip install --upgrade certifi   Certificate checking was not turned off."
                ) from error
            if attempt < retries - 1:
                time.sleep(pause * (attempt + 1))
                continue
            raise WebSourceError(f"{url}: {error}") from error


def category_counts(categories, getter=http_get_json):
    titles = "|".join(categories)
    data = getter(f"{API}?action=query&prop=categoryinfo&format=json&titles={urllib.parse.quote(titles, safe='|:_')}")
    result = {}
    for page in (data or {}).get("query", {}).get("pages", {}).values():
        info = page.get("categoryinfo")
        result[page.get("title")] = None if "missing" in page and not info else (info or {}).get("pages", 0)
    return result


def list_members(category, getter=http_get_json, limit=None):
    titles = []
    token = None
    while True:
        url = (
            f"{API}?action=query&list=categorymembers&cmnamespace=0&cmtype=page&cmlimit=500&format=json"
            f"&cmtitle={urllib.parse.quote(category, safe=':_')}"
        )
        if token:
            url += f"&cmcontinue={urllib.parse.quote(token, safe='')}"
        data = getter(url) or {}
        titles += [member["title"] for member in data.get("query", {}).get("categorymembers", [])]
        token = data.get("continue", {}).get("cmcontinue")
        if not token or (limit and len(titles) >= limit):
            break
    return titles[:limit] if limit else titles


def raw_path(raw_dir, language_key):
    return Path(raw_dir) / language_key / "wiktionary.raw.jsonl"


def done_titles(path):
    done = set()
    if Path(path).exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["title"])
    return done


def fetch_language(language_key, source, raw_dir, getter=http_get_json, limit=None, delay=0.15, sleeper=time.sleep, progress=None, now=None):
    path = raw_path(raw_dir, language_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    titles = []
    seen = set()
    for category in source["categories"]:
        for title in list_members(category, getter=getter, limit=limit):
            if title not in seen:
                seen.add(title)
                titles.append(title)
    if limit:
        titles = titles[:limit]
    done = done_titles(path)
    todo = [title for title in titles if title not in done]
    stats = Counter(listed=len(titles), already_done=len(titles) - len(todo))
    with open(path, "a", encoding="utf-8") as out:
        for index, title in enumerate(todo, start=1):
            data = getter(REST + urllib.parse.quote(title.replace(" ", "_"), safe=""))
            record = {
                "title": title,
                "status": "ok" if data is not None else "missing",
                "retrieved_at": now or datetime.now(timezone.utc).isoformat(),
                "definitions": data,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            stats[record["status"]] += 1
            if progress and index % 100 == 0:
                progress(index, len(todo))
            sleeper(delay)
    return dict(stats)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        if self.skip:
            self.skip += 1
        elif "mw-empty-elt" in (dict(attrs).get("class") or "") or tag in ("style", "script"):
            self.skip = 1

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def clean_html(html):
    extractor = TextExtractor()
    extractor.feed(html or "")
    extractor.close()
    return re.sub(r"\s+", " ", "".join(extractor.parts)).strip()


def language_blocks(definitions, names):
    wanted = {name.casefold() for name in names}
    blocks = []
    for key in sorted((definitions or {}).keys()):
        for block in definitions[key]:
            if str(block.get("language", "")).casefold() in wanted:
                blocks.append(block)
    return blocks


def entries_from_record(record, source, document_id, created_at):
    blocks = language_blocks(record.get("definitions"), source["wiktionary_languages"])
    title = record["title"]
    entries = []
    for index, block in enumerate(blocks):
        senses = [clean_html(item.get("definition", "")) for item in block.get("definitions", [])]
        senses = [sense for sense in senses if sense]
        flags = []
        if not senses:
            flags.append("no_definition")
        if any(FORM_OF.search(sense) for sense in senses):
            flags.append("form_of")
        if len(blocks) > 1:
            flags.append("multiple_entries")
        if len(senses) > 6:
            flags.append("many_senses")
        entry = DictionaryEntry(
            entry_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"wika:{document_id}:{title}:{index}")),
            word=title,
            dialect_code=source["language_code"],
            dialect_name=source["language_name"],
            part_of_speech=block.get("partOfSpeech"),
            meaning="; ".join(senses) if senses else None,
            original_text="\n".join(senses) if senses else None,
            source_document_id=document_id,
            source_file=PAGE_URL + urllib.parse.quote(title.replace(" ", "_"), safe=""),
            extraction_method=EXTRACTION_METHOD,
            parser_version=PARSER_VERSION,
            review_flags=flags,
            created_at=created_at,
        )
        entries.append(entry.model_dump(mode="json"))
    return entries


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(path) + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def build_language(language_key, source, license_info, raw_dir, staging_dir, web_manifest_path, now=None):
    path = raw_path(raw_dir, language_key)
    if not path.exists():
        raise ValueError(f"{path} does not exist. Run the fetch step first.")
    now = now or datetime.now(timezone.utc).isoformat()
    digest = sha256_file(path)
    document_id = f"web_wikt_{language_key}_{digest[:8]}"

    pages = Counter()
    seen_languages = Counter()
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            pages[record["status"]] += 1
            for key, group in (record.get("definitions") or {}).items():
                for block in group:
                    seen_languages[block.get("language")] += 1
            entries += entries_from_record(record, source, document_id, now)
    if not entries:
        top = ", ".join(f"{name} ({count})" for name, count in seen_languages.most_common(8)) or "none"
        raise ValueError(
            f"No entries found for the names {source['wiktionary_languages']}. Language names seen in the downloaded pages: {top}. "
            "Fix wiktionary_languages in config/web_sources.yml."
        )
    entries.sort(key=lambda e: (e["word"].casefold(), e["entry_id"]))

    staging = Path(staging_dir) / f"{document_id}.entries.jsonl"
    write_text_atomic(staging, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))

    document = {
        "document_id": document_id,
        "source_file": f"English Wiktionary ({source['language_name']} lemma snapshot)",
        "sha256": digest,
        "language_code": source["language_code"],
        "language_name": source["language_name"],
        "language_source": "wiktionary_language_section",
        "language_confirmed": True,
        "document_type": "dictionary",
        "license_status": license_info["license_status"],
        "license_name": license_info["license_name"],
        "origin": license_info["origin"],
        "owner": license_info["owner"],
        "needs_license_review": license_info["license_status"] != "cleared",
        "retrieved_from": REST,
        "registered_at": now,
    }
    manifest_path = Path(web_manifest_path)
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    existing = [item for item in existing if item.get("document_id") != document_id]
    write_text_atomic(manifest_path, json.dumps(existing + [document], ensure_ascii=False, indent=2) + "\n")
    flagged = sum(1 for e in entries if e["review_flags"])
    return {
        "document_id": document_id,
        "staging": str(staging),
        "pages": dict(pages),
        "entries": len(entries),
        "flagged": flagged,
        "unique_words": len({e["word"] for e in entries}),
        "languages_seen": seen_languages.most_common(6),
    }
