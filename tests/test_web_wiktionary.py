import json
from pathlib import Path

import pytest

from wika_pipeline.export import export_document, load_manifest
from wika_pipeline.web_wiktionary import (
    build_language,
    category_counts,
    clean_html,
    entries_from_record,
    fetch_language,
    list_members,
    load_web_sources,
    make_ssl_context,
)

SAMPLE = json.loads((Path(__file__).parent / "lapinig_sample.json").read_text(encoding="utf-8"))
SOURCE = {
    "language_code": "war",
    "language_name": "Waray",
    "wiktionary_languages": ["Waray-Waray"],
    "categories": ["Category:Waray-Waray_lemmas"],
}
LICENSE = {"license_status": "cleared", "license_name": "CC BY-SA 4.0", "origin": "Wiktionary", "owner": "Wiktionary contributors"}


def block(language, pos, *senses):
    return {"partOfSpeech": pos, "language": language, "definitions": [{"definition": s} for s in senses]}


def page(title, *blocks):
    return {"title": title, "status": "ok", "retrieved_at": "t", "definitions": {"war": list(blocks)}}


class FakeWiki:
    def __init__(self, members, pages):
        self.members = members
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if "list=categorymembers" in url:
            if "cmcontinue" in url:
                return {"query": {"categorymembers": [{"title": t} for t in self.members[2:]]}}
            body = {"query": {"categorymembers": [{"title": t} for t in self.members[:2]]}}
            if len(self.members) > 2:
                body["continue"] = {"cmcontinue": "page|x|1"}
            return body
        if "prop=categoryinfo" in url:
            return {"query": {"pages": {"1": {"title": "Category:Waray-Waray_lemmas", "categoryinfo": {"pages": 7}}, "2": {"title": "Category:Nope", "missing": ""}}}}
        title = url.rsplit("/", 1)[-1].replace("%20", " ").replace("_", " ")
        return self.pages.get(title)


def test_html_is_cleaned_and_category_links_removed():
    html = SAMPLE["ceb"][0]["definitions"][2]["definition"]
    assert clean_html(html) == "a hornet"
    assert clean_html('a <a href="/wiki/x">link</a>   and\n text') == "a link and text"
    assert clean_html(None) == ""


def test_real_sample_gives_one_waray_entry_and_ignores_other_languages():
    record = {"title": "lapinig", "status": "ok", "definitions": SAMPLE}
    entries = entries_from_record(record, SOURCE, "web_wikt_war_x", "2026-10-29T00:00:00+00:00")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["word"] == "lapinig" and entry["meaning"] == "wasp" and entry["part_of_speech"] == "Noun"
    assert entry["dialect_code"] == "war" and entry["review_flags"] == []
    assert entry["source_file"] == "https://en.wiktionary.org/wiki/lapinig"
    assert entry["validation_review_status"] == "extracted"


def test_flags_for_form_of_missing_and_multiple_entries():
    record = page("x", block("Waray-Waray", "Noun", "alternative form of y"), block("Waray-Waray", "Verb", "to go"), block("Waray-Waray", "Noun"))
    entries = entries_from_record(record, SOURCE, "d", "t")
    assert [e["review_flags"] for e in entries] == [["form_of", "multiple_entries"], ["multiple_entries"], ["no_definition", "multiple_entries"]]
    assert len({e["entry_id"] for e in entries}) == 3


def test_entry_ids_are_stable():
    record = page("x", block("Waray-Waray", "Noun", "a"))
    first = entries_from_record(record, SOURCE, "d", "t")[0]["entry_id"]
    assert first == entries_from_record(record, SOURCE, "d", "t2")[0]["entry_id"]


def test_listing_follows_the_continue_token_and_limit():
    wiki = FakeWiki(["a", "b", "c", "d"], {})
    assert list_members("Category:X", getter=wiki) == ["a", "b", "c", "d"]
    assert list_members("Category:X", getter=wiki, limit=2) == ["a", "b"]


def test_category_counts_report_missing_categories():
    counts = category_counts(["Category:Waray-Waray_lemmas", "Category:Nope"], getter=FakeWiki([], {}))
    assert counts == {"Category:Waray-Waray_lemmas": 7, "Category:Nope": None}


def test_fetch_is_resumable_and_records_missing_pages(tmp_path):
    wiki = FakeWiki(["a", "b", "c", "d"], {"a": SAMPLE, "b": SAMPLE, "c": SAMPLE})
    first = fetch_language("war", SOURCE, tmp_path, getter=wiki, limit=2, sleeper=lambda s: None, now="t")
    assert first["ok"] == 2
    second = fetch_language("war", SOURCE, tmp_path, getter=wiki, sleeper=lambda s: None, now="t")
    assert second["already_done"] == 2 and second["ok"] == 1 and second["missing"] == 1
    lines = [json.loads(line) for line in (tmp_path / "war" / "wiktionary.raw.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["title"] for r in lines] == ["a", "b", "c", "d"]
    assert [r["status"] for r in lines] == ["ok", "ok", "ok", "missing"]


def write_raw(tmp_path, records):
    path = tmp_path / "raw" / "war" / "wiktionary.raw.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def test_build_writes_sorted_staging_and_registers_the_source(tmp_path):
    write_raw(tmp_path, [page("sayod", block("Waray-Waray", "Verb", "to know")), page("agi", block("Waray-Waray", "Noun", "path")), {"title": "zz", "status": "missing", "definitions": None}])
    manifest = tmp_path / "web_manifest.json"
    result = build_language("war", SOURCE, LICENSE, tmp_path / "raw", tmp_path / "staging", manifest, now="2026-10-29T00:00:00+00:00")
    assert result["entries"] == 2 and result["pages"] == {"ok": 2, "missing": 1}
    rows = [json.loads(line) for line in Path(result["staging"]).read_text(encoding="utf-8").splitlines()]
    assert [r["word"] for r in rows] == ["agi", "sayod"]
    assert all(r["source_document_id"] == result["document_id"] for r in rows)
    document = json.loads(manifest.read_text(encoding="utf-8"))[0]
    assert document["license_status"] == "cleared" and document["language_confirmed"] is True
    assert document["sha256"] and result["document_id"].startswith("web_wikt_war_")


def test_build_explains_a_language_name_mismatch(tmp_path):
    write_raw(tmp_path, [page("x", block("Zamboanga Chavacano", "Noun", "a"))])
    with pytest.raises(ValueError, match="Zamboanga Chavacano"):
        build_language("war", SOURCE, LICENSE, tmp_path / "raw", tmp_path / "staging", tmp_path / "m.json")


def test_rebuilding_the_same_raw_file_keeps_one_manifest_entry(tmp_path):
    write_raw(tmp_path, [page("agi", block("Waray-Waray", "Noun", "path"))])
    manifest = tmp_path / "m.json"
    for _ in range(2):
        build_language("war", SOURCE, LICENSE, tmp_path / "raw", tmp_path / "staging", manifest)
    assert len(json.loads(manifest.read_text(encoding="utf-8"))) == 1


def test_manifests_from_several_files_are_merged(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text('[{"document_id": "x"}]', encoding="utf-8")
    b.write_text('[{"document_id": "y"}]', encoding="utf-8")
    assert [d["document_id"] for d in load_manifest([a, b, tmp_path / "missing.json"])] == ["x", "y"]


def test_web_documents_can_reach_the_export_gate_after_review(tmp_path):
    write_raw(tmp_path, [page("agi", block("Waray-Waray", "Noun", "path"))])
    manifest = tmp_path / "m.json"
    result = build_language("war", SOURCE, LICENSE, tmp_path / "raw", tmp_path / "staging", manifest)
    fmt = tmp_path / "fmt.yml"
    fmt.write_text("fields:\n  - entry_id\n  - word\n  - meaning\n", encoding="utf-8")
    from wika_pipeline.export import GateFailure

    with pytest.raises(GateFailure) as caught:
        export_document(result["staging"], [manifest], tmp_path / "none.jsonl", fmt, tmp_path / "out")
    failed = {g["gate"] for g in caught.value.gates if not g["passed"]}
    assert failed == {"has_approved_entries"}


def test_config_file_is_validated(tmp_path):
    path = tmp_path / "w.yml"
    path.write_text("sources:\n  war: {language_code: war, language_name: Waray, wiktionary_languages: [a], categories: [b]}\nlicense: {license_status: cleared}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="license"):
        load_web_sources(path)
    sources, license_info = load_web_sources(Path("config") / "web_sources.yml")
    assert set(sources) == {"war", "cbk"} and license_info["license_name"] == "CC BY-SA 4.0"


def test_the_ssl_context_verifies_certificates():
    import ssl

    context = make_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
