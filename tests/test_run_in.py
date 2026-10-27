import pymupdf

from wika_pipeline.parsers.column_dictionary import parse_pdf, split_run_in

PROFILE = {
    "profile_id": "test_profile",
    "profile_version": "0.0.1",
    "running_title": "TEST DICTIONARY",
    "main_headword_x": 54.0,
    "subentry_indent": 18.0,
    "x_tolerance": 3.0,
    "gloss_min_x": 120.0,
    "y_tolerance": 2.0,
    "min_gloss_share": 0.2,
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


def parse_placed(tmp_path, placed):
    doc = pymupdf.open()
    page = doc.new_page()
    for x, y, text in placed:
        page.insert_text((x, y), text, fontname="helv", fontsize=10)
    page.insert_text((144, 760), "TEST DICTIONARY", fontname="helv", fontsize=10)
    page.insert_text((206, 772), "1", fontname="helv", fontsize=10)
    path = tmp_path / "test.pdf"
    doc.save(path)
    doc.close()
    entries, _ = parse_pdf(path, PROFILE, DOCUMENT, NOW)
    return entries


def test_split_run_in_separates_word_respelling_and_gloss():
    assert split_run_in("arina, harina /arina/ flour") == ("arina, harina", "/arina/", "flour")
    assert split_run_in("dolyar /dolyar/dollar (plural: dolyares)") == (
        "dolyar",
        "/dolyar/",
        "dollar (plural: dolyares)",
    )
    assert split_run_in("gin /hin/") == ("gin", "/hin/", "")


def test_split_run_in_leaves_other_text_alone():
    assert split_run_in("alpha") is None
    assert split_run_in("and/or") is None
    assert split_run_in("alpha / beta") is None
    assert split_run_in("/alone/") is None


def test_whole_entry_on_one_row_is_split(tmp_path):
    entries = parse_placed(
        tmp_path,
        [
            (54, 80, "arina, harina /arina/ flour"),
            (54, 92, "next"),
            (180, 92, "other"),
        ],
    )
    assert [entry["word"] for entry in entries] == ["arina, harina", "next"]
    first = entries[0]
    assert first["pronunciation_guide"] == "/arina/"
    assert first["meaning"] == "flour"
    assert "run_in_gloss" in first["review_flags"]
    assert "no_gloss" not in first["review_flags"]
    assert "arina, harina /arina/ flour" in first["original_text"]


def test_gloss_without_a_space_after_the_slash(tmp_path):
    entries = parse_placed(tmp_path, [(54, 80, "dolyar /dolyar/dollar"), (54, 92, "x"), (180, 92, "y")])
    assert entries[0]["word"] == "dolyar"
    assert entries[0]["meaning"] == "dollar"


def test_respelling_without_gloss_leaves_the_gloss_to_the_gloss_column(tmp_path):
    entries = parse_placed(tmp_path, [(54, 80, "gin /hin/"), (180, 80, "a drink")])
    assert entries[0]["word"] == "gin"
    assert entries[0]["pronunciation_guide"] == "/hin/"
    assert entries[0]["meaning"] == "a drink"
    assert "run_in_gloss" not in entries[0]["review_flags"]


def test_run_in_gloss_continues_on_the_gloss_column(tmp_path):
    entries = parse_placed(
        tmp_path,
        [
            (54, 80, "word /wrd/ first part"),
            (180, 92, "second part"),
        ],
    )
    assert entries[0]["meaning"] == "first part second part"


def test_sub_entry_run_in_keeps_its_parent(tmp_path):
    entries = parse_placed(
        tmp_path,
        [
            (54, 80, "main"),
            (180, 80, "g"),
            (72, 92, "sub /sb/ meaning"),
        ],
    )
    assert entries[1]["word"] == "sub"
    assert entries[1]["parent_headword"] == "main"
    assert entries[1]["meaning"] == "meaning"


def test_parent_headword_for_later_sub_entries_is_the_word_without_the_respelling(tmp_path):
    entries = parse_placed(
        tmp_path,
        [
            (54, 80, "main /mn/ meaning"),
            (72, 92, "sub"),
            (198, 92, "g"),
        ],
    )
    assert entries[1]["parent_headword"] == "main"


def test_a_run_in_entry_inside_a_reading_order_break_is_still_flagged(tmp_path):
    entries = parse_placed(
        tmp_path,
        [
            (54, 80, "alpha"),
            (180, 80, "first"),
            (54, 92, "beta /bt/ gloss"),
            (54, 104, "gamma"),
            (180, 92, "stray"),
        ],
    )
    by_word = {entry["word"]: entry for entry in entries}
    assert "reading_order_break" in by_word["beta"]["review_flags"]
    assert "reading_order_break" in by_word["gamma"]["review_flags"]
    assert "reading_order_break" not in by_word["alpha"]["review_flags"]