import json

import pymupdf
import pytest

from wika_pipeline.parsers.column_dictionary import (
    check_page,
    has_unusual_capital,
    kind_of,
    load_profile,
    parse_pdf,
    split_footer,
    write_outputs,
)

FILLER = [(54, f"word{n}") if i == 0 else (180, f"meaning {n}") for n in range(6) for i in range(2)]

PROFILE = {
    "profile_id": "test_profile",
    "profile_version": "0.0.1",
    "running_title": "TEST DICTIONARY",
    "main_headword_x": 54.0,
    "subentry_indent": 18.0,
    "x_tolerance": 3.0,
    "gloss_min_x": 120.0,
    "y_tolerance": 2.0,
    "min_gloss_share": 0.35,
    "min_headword_share": 0.1,
    "max_unexpected_share": 0.1,
}
DOCUMENT = {
    "document_id": "doc_test",
    "source_file": "test.pdf",
    "language_code": "pag",
    "language_name": "Pangasinan",
    "language_confirmed": True,
}
NOW = "2026-01-01T00:00:00+00:00"


def entry_page(doc, items, footer=True, number="1"):
    page = doc.new_page()
    y = 80
    for x, text in items:
        page.insert_text((x, y), text, fontname="helv", fontsize=10)
        y += 12
    if footer:
        page.insert_text((144, 760), "TEST DICTIONARY", fontname="helv", fontsize=10)
        page.insert_text((206, 772), number, fontname="helv", fontsize=10)
    return page


def make_pdf(path, pages):
    doc = pymupdf.open()
    for index, spec in enumerate(pages, start=1):
        if isinstance(spec, dict):
            entry_page(doc, spec["items"], spec.get("footer", True), str(index))
        else:
            entry_page(doc, spec, True, str(index))
    doc.save(path)
    doc.close()
    return path


def parse(tmp_path, pages):
    pdf = make_pdf(tmp_path / "test.pdf", pages)
    return parse_pdf(pdf, PROFILE, DOCUMENT, NOW)


def test_headword_and_multiline_gloss_are_paired(tmp_path):
    entries, _ = parse(tmp_path, [[
        (54, "bilín"), (180, "education, advice, counsel; to advise,"), (180, "counsel (man-)"),
        (54, "biní"), (180, "seeds"),
    ]])
    assert [e["word"] for e in entries] == ["bilín", "biní"]
    assert entries[0]["meaning"] == "education, advice, counsel; to advise, counsel (man-)"
    assert entries[0]["original_text"].count("\n") == 2
    assert entries[1]["meaning"] == "seeds"


def test_diacritics_and_provenance_are_kept(tmp_path):
    entries, _ = parse(tmp_path, [[(54, "biloñgét"), (180, "darkness")]])
    entry = entries[0]
    assert entry["word"] == "biloñgét"
    assert entry["source_page"] == 1
    assert entry["source_document_id"] == "doc_test"
    assert entry["dialect_code"] == "pag"
    assert entry["part_of_speech"] is None
    assert entry["validation_review_status"] == "extracted"


def test_footer_is_not_part_of_any_entry(tmp_path):
    entries, _ = parse(tmp_path, [[(54, "sebég"), (180, "to quarrel")]])
    text = json.dumps(entries)
    assert "TEST DICTIONARY" not in text
    assert entries[0]["meaning"] == "to quarrel"


def test_subentry_gets_parent_headword(tmp_path):
    entries, _ = parse(tmp_path, [[
        (54, "binyág"), (180, "baptism"), (72, "kabinyág"), (198, "one who was baptized"),
    ]])
    assert entries[0]["parent_headword"] is None
    assert entries[1]["parent_headword"] == "binyág"


def test_subentry_at_page_top_uses_parent_from_previous_page(tmp_path):
    entries, _ = parse(tmp_path, [
        [(54, "biskég"), (180, "strength")],
        [(72, "mabiskég"), (198, "strong")],
    ])
    assert entries[1]["parent_headword"] == "biskég"
    assert "subentry_without_parent" not in entries[1]["review_flags"]


def test_subentry_without_parent_is_flagged(tmp_path):
    entries, _ = parse(tmp_path, [[(72, "mabiskég"), (198, "strong")]])
    assert "subentry_without_parent" in entries[0]["review_flags"]


def test_gloss_continuing_onto_next_page_is_attached_and_flagged(tmp_path):
    entries, _ = parse(tmp_path, [
        [(54, "sawáli"), (180, "flattened bamboo made into mat-like")],
        [(180, "panels for walls"), (54, "sawsáw"), (180, "to dip")],
    ])
    assert entries[0]["meaning"] == "flattened bamboo made into mat-like panels for walls"
    assert "continued_from_previous_page" in entries[0]["review_flags"]
    assert entries[0]["source_page"] == 1
    assert entries[1]["word"] == "sawsáw"


def test_headword_without_gloss_is_flagged_not_guessed(tmp_path):
    entries, _ = parse(tmp_path, [[(54, "sebég"), (54, "sebél"), (180, "to prohibit")] + FILLER])
    assert entries[0]["meaning"] is None
    assert "no_gloss" in entries[0]["review_flags"]
    assert entries[1]["meaning"] == "to prohibit"


def test_review_flags_for_complex_cross_reference_and_capitals(tmp_path):
    entries, _ = parse(tmp_path, [[
        (54, "birhÉn, virgÉn"), (180, "(statue of) the Virgin Mary"),
        (54, "bínti"), (180, "= baíntE, q.v."),
    ]])
    assert "complex_headword" in entries[0]["review_flags"]
    assert "unusual_capital" in entries[0]["review_flags"]
    assert "cross_reference" in entries[1]["review_flags"]
    assert entries[0]["word"] == "birhÉn, virgÉn"


def test_unexpected_position_is_kept_in_original_text_and_flagged(tmp_path):
    entries, _ = parse(tmp_path, [[(54, "sarí"), (180, "breaking through"), (100, "stray text")] + FILLER * 2])
    assert "unexpected_indent" in entries[0]["review_flags"]
    assert "stray text" in entries[0]["original_text"]
    assert "stray text" not in entries[0]["meaning"]


def test_page_without_footer_is_skipped_with_reason(tmp_path):
    entries, report = parse(tmp_path, [
        {"items": [(54, "prose paragraph line"), (54, "another prose line")], "footer": False},
        [(54, "sarí"), (180, "breaking through")],
    ])
    assert [item["page"] for item in report["pages_skipped"]] == [1]
    assert "footer" in report["pages_skipped"][0]["reason"]
    assert [e["word"] for e in entries] == ["sarí"]


def test_prose_page_with_footer_is_skipped_by_layout(tmp_path):
    entries, report = parse(tmp_path, [[(54, "paragraph one"), (54, "paragraph two")]])
    assert entries == []
    assert "gloss column" in report["pages_skipped"][0]["reason"]


def test_gap_between_entry_pages_does_not_join_entries(tmp_path):
    entries, report = parse(tmp_path, [
        [(54, "sarí"), (180, "breaking")],
        [(54, "intro page text")],
        [(180, "orphan line"), (54, "sasá"), (180, "puss")],
    ])
    assert entries[0]["meaning"] == "breaking"
    assert any("before any headword" in issue["issue"] for issue in report["page_issues"])


def test_headwords_out_of_order_are_flagged(tmp_path):
    pdf = tmp_path / "test.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((54, 300), "second", fontname="helv", fontsize=10)
    page.insert_text((180, 312), "gloss b", fontname="helv", fontsize=10)
    page.insert_text((54, 100), "first", fontname="helv", fontsize=10)
    page.insert_text((180, 112), "gloss a", fontname="helv", fontsize=10)
    page.insert_text((144, 760), "TEST DICTIONARY", fontname="helv", fontsize=10)
    page.insert_text((206, 772), "1", fontname="helv", fontsize=10)
    doc.save(pdf)
    doc.close()
    entries, report = parse_pdf(pdf, PROFILE, DOCUMENT, NOW)
    assert "order_check_failed" in entries[1]["review_flags"]
    assert report["page_issues"][0]["page"] == 1


def test_ids_are_stable_across_runs_and_unique(tmp_path):
    pages = [[(54, "sarí"), (180, "breaking"), (54, "sasá"), (180, "puss")]]
    first, _ = parse(tmp_path, pages)
    second, _ = parse(tmp_path, pages)
    assert [e["entry_id"] for e in first] == [e["entry_id"] for e in second]
    assert len({e["entry_id"] for e in first}) == 2
    assert first == second


def test_report_counts(tmp_path):
    _, report = parse(tmp_path, [[(54, "sebég"), (54, "sebél"), (180, "to prohibit")] + FILLER])
    assert report["entries_total"] == 8
    assert report["entries_with_flags"] == 1
    assert report["flag_counts"] == {"no_gloss": 1}
    assert report["pages_parsed"] == 1


def test_outputs_round_trip_and_leave_no_temp_files(tmp_path):
    entries, report = parse(tmp_path, [[(54, "sarí"), (180, "breaking")]])
    entries_path, report_path = write_outputs(entries, report, tmp_path / "staging")
    lines = entries_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == entries
    assert json.loads(report_path.read_text(encoding="utf-8"))["entries_total"] == 1
    assert not list((tmp_path / "staging").glob("*.tmp"))


def test_every_entry_is_valid_for_the_schema(tmp_path):
    from wika_pipeline.schema import DictionaryEntry

    entries, _ = parse(tmp_path, [[(54, "sarí"), (180, "breaking"), (54, "x"), (180, "y")]])
    for entry in entries:
        DictionaryEntry(**entry)


def test_kind_of_uses_tolerance_and_columns():
    assert kind_of(54.0, PROFILE) == "headword"
    assert kind_of(55.9, PROFILE) == "headword"
    assert kind_of(72.0, PROFILE) == "subheadword"
    assert kind_of(178.5, PROFILE) == "gloss"
    assert kind_of(100.0, PROFILE) == "unexpected"


def test_split_footer_needs_title_and_number():
    rows = [{"text": "a"}, {"text": "test dictionary"}, {"text": "24"}]
    body, found = split_footer(rows, PROFILE)
    assert found and body == [{"text": "a"}]
    body, found = split_footer([{"text": "a"}, {"text": "b"}], PROFILE)
    assert not found and len(body) == 2


def test_check_page_requires_footer():
    ok, reason = check_page(["headword", "gloss"], False, PROFILE)
    assert not ok and "footer" in reason


def test_unusual_capital_detection():
    assert has_unusual_capital("baíntE")
    assert has_unusual_capital("birhÉn")
    assert not has_unusual_capital("PANGASINAN")
    assert not has_unusual_capital("Virgin")


def test_profile_must_have_required_keys(tmp_path):
    path = tmp_path / "p.yml"
    path.write_text("profile_id: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        load_profile(path)


def test_page_with_too_many_unexpected_positions_is_skipped(tmp_path):
    strays = [(100, "stray one"), (100, "stray two"), (100, "stray three")]
    entries, report = parse(tmp_path, [[(54, "sarí"), (180, "breaking through")] + strays + FILLER])
    assert entries == []
    assert "unexpected positions" in report["pages_skipped"][0]["reason"]
    

def make_superscript_pdf(path, marked=True):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 80
    for number, word, gloss in [("1", "yókyok", "to bow the head"), ("2", "yókyok", "to wash something")]:
        if marked:
            page.insert_text((54, y), number, fontname="helv", fontsize=8.3)
            page.insert_text((59, y), word, fontname="helv", fontsize=10)
        else:
            page.insert_text((54, y), number + word, fontname="helv", fontsize=10)
        page.insert_text((180, y), gloss, fontname="helv", fontsize=10)
        y += 14
    for n in range(4):
        page.insert_text((54, y), f"word{n}", fontname="helv", fontsize=10)
        page.insert_text((180, y), f"meaning {n}", fontname="helv", fontsize=10)
        y += 14
    page.insert_text((144, 760), "TEST DICTIONARY", fontname="helv", fontsize=10)
    page.insert_text((206, 772), "1", fontname="helv", fontsize=10)
    doc.save(path)
    doc.close()
    return path


def test_small_leading_number_is_a_homograph_marker_not_part_of_the_word(tmp_path):
    entries, _ = parse_pdf(make_superscript_pdf(tmp_path / "a.pdf"), PROFILE, DOCUMENT, NOW)
    assert [e["word"] for e in entries[:2]] == ["yókyok", "yókyok"]
    assert [e["homograph_number"] for e in entries[:2]] == [1, 2]
    assert entries[0]["original_text"].startswith("1yókyok")
    assert entries[2]["homograph_number"] is None
    assert entries[0]["entry_id"] != entries[1]["entry_id"]


def test_full_size_leading_digit_is_left_alone(tmp_path):
    entries, _ = parse_pdf(make_superscript_pdf(tmp_path / "a.pdf", marked=False), PROFILE, DOCUMENT, NOW)
    assert entries[0]["word"] == "1yókyok"
    assert entries[0]["homograph_number"] is None


def test_sub_entry_parent_ignores_the_homograph_number(tmp_path):
    from wika_pipeline.parsers.column_dictionary import split_homograph

    row = {"text": "1yókyok", "spans": [{"text": "1", "size": 8.3}, {"text": "yókyok", "size": 10.0}]}
    assert split_homograph(row) == (1, "yókyok")
    assert split_homograph({"text": "yókyok"}) == (None, "yókyok")


def test_odd_and_even_page_running_titles_with_a_dash_are_both_recognised():
    profile = dict(PROFILE, running_titles=["TEST-ENGLISH DICTIONARY"])
    odd = [{"text": "x"}, {"text": "TEST\u2013ENGLISH DICTIONARY"}, {"text": "25"}]
    even = [{"text": "x"}, {"text": "TEST DICTIONARY"}, {"text": "26"}]
    other = [{"text": "x"}, {"text": "SOMETHING ELSE"}, {"text": "27"}]
    assert split_footer(odd, profile)[1] is True
    assert split_footer(even, profile)[1] is True
    assert split_footer(other, profile)[1] is False


def test_entries_on_a_page_with_the_alternate_title_are_parsed(tmp_path):
    profile = dict(PROFILE, running_titles=["TEST-ENGLISH DICTIONARY"])
    doc = pymupdf.open()
    page = doc.new_page()
    for n in range(4):
        page.insert_text((54, 80 + 14 * n), f"word{n}", fontname="helv", fontsize=10)
        page.insert_text((180, 80 + 14 * n), f"meaning {n}", fontname="helv", fontsize=10)
    page.insert_text((116, 760), "TEST-ENGLISH DICTIONARY", fontname="helv", fontsize=10)
    page.insert_text((210, 772), "25", fontname="helv", fontsize=10)
    pdf = tmp_path / "a.pdf"
    doc.save(pdf)
    doc.close()
    entries, report = parse_pdf(pdf, profile, DOCUMENT, NOW)
    assert len(entries) == 4
    assert report["pages_skipped"] == []


def test_pages_outside_the_profile_range_are_skipped(tmp_path):
    profile = dict(PROFILE, first_page=2, last_page=2)
    pdf = make_pdf(tmp_path / "test.pdf", [
        [(54, "one"), (180, "first page")],
        [(54, "two"), (180, "second page")],
        [(54, "three"), (180, "third page")],
    ])
    entries, report = parse_pdf(pdf, profile, DOCUMENT, NOW)
    assert [e["word"] for e in entries] == ["two"]
    assert [item["page"] for item in report["pages_skipped"]] == [1, 3]
    assert report["pages_skipped"][0]["reason"] == "outside the profile's page range"