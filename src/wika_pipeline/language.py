import re
import unicodedata

import yaml

FRONT_MATTER_PAGES = 10
MAX_SAMPLED_PAGES = 50
FRONT_WEIGHT = 3
PER_PAGE_MENTION_CAP = 3
MIN_SCORE = 5
DOMINANCE_RATIO = 3
MIN_PAGES_WITH_MENTIONS = 2


def fold(text):
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def load_languages(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    languages = data.get("languages") or {}
    for code, info in languages.items():
        if not info.get("name") or not info.get("aliases"):
            raise ValueError(f"languages.yml: '{code}' needs a name and at least one alias")
    return languages


def _compile_patterns(languages):
    patterns = {}
    for code, info in languages.items():
        names = [fold(alias) for alias in info["aliases"]]
        patterns[code] = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
    return patterns


def _choose_pages(pages):
    front = [(page, FRONT_WEIGHT) for page in pages[:FRONT_MATTER_PAGES]]
    rest = pages[FRONT_MATTER_PAGES:]
    step = max(1, len(rest) // MAX_SAMPLED_PAGES)
    sampled = [(page, 1) for page in rest[::step][:MAX_SAMPLED_PAGES]]
    return front + sampled


def detect_language(pages, languages):
    patterns = _compile_patterns(languages)
    chosen = _choose_pages(pages)
    stats = {code: {"score": 0, "mentions": 0, "pages": []} for code in languages}

    for page, weight in chosen:
        folded = fold(page["text"])
        for code, pattern in patterns.items():
            count = len(pattern.findall(folded))
            if count:
                stats[code]["score"] += min(count, PER_PAGE_MENTION_CAP) * weight
                stats[code]["mentions"] += count
                stats[code]["pages"].append(page["source_page"])

    found = {code: s for code, s in stats.items() if s["score"] > 0}
    result = {
        "suggested_code": None,
        "suggested_name": None,
        "confidence": "none",
        "pages_scanned": len(chosen),
        "evidence": {
            code: {
                "score": s["score"],
                "mentions": s["mentions"],
                "page_count": len(s["pages"]),
                "first_pages": s["pages"][:10],
            }
            for code, s in found.items()
        },
    }
    if not found:
        return result

    ranked = sorted(found.items(), key=lambda item: item[1]["score"], reverse=True)
    top_code, top = ranked[0]
    second_score = ranked[1][1]["score"] if len(ranked) > 1 else 0

    result["suggested_code"] = top_code
    result["suggested_name"] = languages[top_code]["name"]
    is_clear = (
        top["score"] >= MIN_SCORE
        and top["score"] >= DOMINANCE_RATIO * second_score
        and len(top["pages"]) >= MIN_PAGES_WITH_MENTIONS
    )
    result["confidence"] = "high" if is_clear else "low"
    return result