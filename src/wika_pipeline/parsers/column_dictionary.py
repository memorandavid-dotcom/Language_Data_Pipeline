import json
import uuid
from collections import Counter
from pathlib import Path

import yaml

from wika_pipeline.layout import iter_page_lines
from wika_pipeline.schema import DictionaryEntry

PARSER_VERSION = "column-dictionary-0.1.0"
EXTRACTION_METHOD = "pymupdf_layout_columns"
REQUIRED_PROFILE_KEYS = {
    "profile_id",
    "profile_version",
    "running_title",
    "main_headword_x",
    "subentry_indent",
    "x_tolerance",
    "gloss_min_x",
    "min_gloss_share",
    "min_headword_share",
    "max_unexpected_share",
}


def load_profile(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    missing = REQUIRED_PROFILE_KEYS - set(data)
    if missing:
        raise ValueError(f"profile {path}: missing {sorted(missing)}")
    return data


def normalize_title(text):
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(text.split()).casefold()


def running_titles(profile):
    titles = [profile["running_title"]] + list(profile.get("running_titles") or [])
    return {normalize_title(title) for title in titles}


def split_footer(rows, profile):
    if len(rows) >= 2:
        last_two = [rows[-2]["text"].strip(), rows[-1]["text"].strip()]
        titles = running_titles(profile)
        has_title = any(normalize_title(text) in titles for text in last_two)
        has_number = any(text.isdigit() for text in last_two)
        if has_title and has_number:
                    return rows[:-2], True
    if len(rows) >= 3 and is_letter_heading(rows[0], profile) and rows[-1]["text"].strip().isdigit():
        return rows[1:-1], True
    return rows, False


def is_letter_heading(row, profile):
    text = row["text"].strip()
    min_x = profile.get("letter_heading_min_x", 150.0)
    max_chars = profile.get("letter_heading_max_chars", 3)
    return (
        0 < len(text) <= max_chars
        and text.replace("/", "").isalpha()
        and text.isupper()
        and row["x0"] >= min_x
    )

def split_homograph(row):
    spans = row.get("spans") or []
    if len(spans) >= 2:
        first = spans[0]["text"].strip()
        rest = spans[1:]
        rest_size = max(span["size"] for span in rest)
        if first.isdigit() and spans[0]["size"] < 0.9 * rest_size:
            word = "".join(span["text"] for span in rest).strip()
            if word:
                return int(first), word
    return None, row["text"]


def kind_of(x, profile):
    if x >= profile["gloss_min_x"]:
        return "gloss"
    main = profile["main_headword_x"]
    tolerance = profile["x_tolerance"]
    if abs(x - main) <= tolerance:
        return "headword"
    if abs(x - (main + profile["subentry_indent"])) <= tolerance:
        return "subheadword"
    return "unexpected"


def check_page(kinds, footer_found, profile):
    if not footer_found:
        return False, "no running footer found"
    total = len(kinds)
    if total == 0:
        return False, "no lines besides the footer"
    counts = Counter(kinds)
    gloss_share = counts["gloss"] / total
    headword_share = (counts["headword"] + counts["subheadword"]) / total
    unexpected_share = counts["unexpected"] / total
    if gloss_share < profile["min_gloss_share"]:
        return False, f"only {gloss_share:.0%} of lines are in the gloss column"
    if headword_share < profile["min_headword_share"]:
        return False, f"only {headword_share:.0%} of lines are headwords"
    if unexpected_share > profile["max_unexpected_share"]:
        return False, f"{unexpected_share:.0%} of lines are at unexpected positions"
    return True, ""

def is_pronunciation_row(text):
    text = text.strip()
    return len(text) > 2 and text.startswith("/") and text.endswith("/")


def needs_continuation(line_text, linkers=()):
    text = line_text.rstrip()
    if text.endswith(",") or text.count("(") > text.count(")"):
        return True
    words = text.split()
    return len(words) >= 2 and words[-1] in linkers

def has_unusual_capital(text):
    return any(text[i].isupper() and text[i - 1].islower() for i in range(1, len(text)))


def build_entry(item, document, profile, created_at):
    word = item["word"]
    glosses = item["glosses"]
    meaning = " ".join(glosses) if glosses else None
    flags = list(item["flags"])

    if not glosses:
        flags.append("no_gloss")
    if any(ch in word for ch in ",( "):
        flags.append("complex_headword")
    if meaning and (meaning.startswith("=") or "q.v." in meaning):
        flags.append("cross_reference")
    if has_unusual_capital(word) or (meaning and has_unusual_capital(meaning)):
        flags.append("unusual_capital")

    entry_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"wika:{document['document_id']}:{item['page']}:{item['index']}:{word}",
        )
    )
    entry = DictionaryEntry(
        entry_id=entry_id,
        word=word,
        dialect_code=document["language_code"],
        dialect_name=document["language_name"],
        meaning=meaning,
        original_text="\n".join(item["lines"]),
        parent_headword=item["parent"],
        homograph_number=item["homograph"],
        pronunciation_guide=item.get("pronunciation"),
        source_document_id=document["document_id"],
        source_file=document["source_file"],
        source_page=item["page"],
        extraction_method=EXTRACTION_METHOD,
        parser_version=f"{PARSER_VERSION}/{profile['profile_id']}-{profile['profile_version']}",
        review_flags=flags,
        created_at=created_at,
    )
    return entry.model_dump(mode="json")


def parse_pdf(pdf_path, profile, document, created_at):
    items = []
    skipped = []
    page_issues = []
    pages_total = 0
    per_page_index = Counter()
    state = {"current": None, "last_main": None, "last_page": None}

    def finish():
        if state["current"] is not None:
            items.append(state["current"])
            state["current"] = None

    first_page = profile.get("first_page")
    last_page = profile.get("last_page")
    y_tolerance = profile.get("y_tolerance", 2.0)
    linkers = tuple(profile.get("wrap_linkers") or ())

    for page_number, rows in iter_page_lines(pdf_path):
        pages_total += 1
        if (first_page and page_number < first_page) or (last_page and page_number > last_page):
            skipped.append({"page": page_number, "reason": "outside the profile's page range"})
            finish()
            state["last_main"] = None
            state["last_page"] = None
            continue
        body, footer_found = split_footer(rows, profile)
        kinds = [kind_of(row["x0"], profile) for row in body]
        ok, reason = check_page(kinds, footer_found, profile)
        if not ok:
            skipped.append({"page": page_number, "reason": reason})
            finish()
            state["last_main"] = None
            state["last_page"] = None
            continue

        if state["last_page"] is not None and page_number != state["last_page"] + 1:
            finish()
            state["last_main"] = None
        state["last_page"] = page_number

        previous_head_y = None
        order_reported = False
        previous_row_y = None
        break_reported = False
        page_start = len(items)
        for row, kind in zip(body, kinds):
            if previous_row_y is not None and row["y0"] < previous_row_y - y_tolerance:
                candidates = items[page_start:]
                if state["current"] is not None:
                    candidates = candidates + [state["current"]]
                flagged_any = False
                for item in candidates:
                    inside_group = item["page"] == page_number and item["y"] >= row["y0"] - y_tolerance
                    explained = "headword_continued" in item["flags"] or item.get("pronunciation") is not None
                    if inside_group and not explained:
                        if "reading_order_break" not in item["flags"]:
                            item["flags"].append("reading_order_break")
                        flagged_any = True
                if flagged_any and not break_reported:
                    page_issues.append(
                        {
                            "page": page_number,
                            "issue": "reading order break: a line sits higher on the page than the line before it",
                        }
                    )
                    break_reported = True
            previous_row_y = row["y0"]
            current = state["current"]
            if (
                kind in ("headword", "subheadword")
                and current is not None
                and not current["glosses"]
                and current["kind"] == kind
                and current.get("pronunciation") is None
                and is_pronunciation_row(row["text"])
            ):
                current["pronunciation"] = row["text"].strip()
                current["lines"].append(row["text"])
            elif (
                kind in ("headword", "subheadword")
                and current is not None
                and not current["glosses"]
                and current["kind"] == kind
                and needs_continuation(current["lines"][-1], linkers)
            ):
                current["word"] = f"{current['word']} {split_homograph(row)[1]}"
                current["lines"].append(row["text"])
                if "headword_continued" not in current["flags"]:
                    current["flags"].append("headword_continued")
                if kind == "headword":
                    state["last_main"] = current["word"]
            elif kind in ("headword", "subheadword"):
                finish()
                flags = []
                if previous_head_y is not None and row["y0"] < previous_head_y - y_tolerance:
                    flags.append("order_check_failed")
                    if not order_reported:
                        page_issues.append(
                            {"page": page_number, "issue": "headwords are not in top-to-bottom order"}
                        )
                        order_reported = True
                previous_head_y = row["y0"]
                parent = None
                if kind == "subheadword":
                    parent = state["last_main"]
                    if parent is None:
                        flags.append("subentry_without_parent")
                else:
                    state["last_main"] = split_homograph(row)[1]
                index = per_page_index[page_number]
                per_page_index[page_number] += 1
                homograph, word = split_homograph(row)
                state["current"] = {
                    "word": word,
                    "homograph": homograph,
                    "page": page_number,
                    "index": index,
                    "parent": parent,
                    "kind": kind,
                    "y": row["y0"],
                    "glosses": [],
                    "lines": [row["text"]],
                    "flags": flags,
                }
            elif current is None:
                page_issues.append(
                    {
                        "page": page_number,
                        "issue": "a line appears before any headword and was not attached to an entry",
                    }
                )
            elif kind == "gloss":
                current["glosses"].append(row["text"])
                current["lines"].append(row["text"])
                if current["page"] != page_number and "continued_from_previous_page" not in current["flags"]:
                    current["flags"].append("continued_from_previous_page")
            else:
                current["lines"].append(row["text"])
                if "unexpected_indent" not in current["flags"]:
                    current["flags"].append("unexpected_indent")
    finish()
    entries = [build_entry(item, document, profile, created_at) for item in items]

    flag_counts = Counter(flag for entry in entries for flag in entry["review_flags"])
    report = {
        "parser_version": PARSER_VERSION,
        "profile_id": profile["profile_id"],
        "profile_version": profile["profile_version"],
        "document_id": document["document_id"],
        "source_file": document["source_file"],
        "language_code": document["language_code"],
        "language_confirmed": document.get("language_confirmed"),
        "pages_total": pages_total,
        "pages_parsed": pages_total - len(skipped),
        "pages_skipped": skipped,
        "page_issues": page_issues,
        "entries_total": len(entries),
        "entries_with_flags": sum(1 for entry in entries if entry["review_flags"]),
        "flag_counts": dict(sorted(flag_counts.items())),
        "created_at": created_at,
    }
    return entries, report

def write_outputs(entries, report, staging_dir):
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    document_id = report["document_id"]
    entries_path = staging_dir / f"{document_id}.entries.jsonl"
    report_path = staging_dir / f"{document_id}.parse_report.json"

    temp_entries = entries_path.with_suffix(".jsonl.tmp")
    with open(temp_entries, "w", encoding="utf-8", newline="\n") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    temp_entries.replace(entries_path)

    temp_report = report_path.with_suffix(".json.tmp")
    temp_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_report.replace(report_path)
    return entries_path, report_path