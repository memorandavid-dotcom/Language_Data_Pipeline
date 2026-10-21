import pytest

from wika_pipeline.language import detect_language, fold, load_languages

LANGUAGES = {
    "pag": {"name": "Pangasinan", "aliases": ["Pangasinan", "Pangasinense"]},
    "tgl": {"name": "Tagalog", "aliases": ["Tagalog"]},
    "cbk": {"name": "Chavacano", "aliases": ["Chavacano", "Zamboangueño"]},
}


def make_pages(texts):
    return [{"source_page": i, "text": text} for i, text in enumerate(texts, start=1)]


def test_clear_language_is_high_confidence():
    pages = make_pages(["Pangasinan Dictionary", "About the Pangasinan language"] + ["entry"] * 20)
    result = detect_language(pages, LANGUAGES)
    assert result["suggested_code"] == "pag"
    assert result["confidence"] == "high"
    assert result["evidence"]["pag"]["first_pages"] == [1, 2]


def test_two_close_languages_are_not_high_confidence():
    pages = make_pages(["Pangasinan and Tagalog", "Tagalog and Pangasinan", "entry"])
    assert detect_language(pages, LANGUAGES)["confidence"] == "low"


def test_no_mentions_gives_none():
    result = detect_language(make_pages(["just some words", "more words"]), LANGUAGES)
    assert result["confidence"] == "none"
    assert result["suggested_code"] is None


def test_single_mention_is_not_enough():
    pages = make_pages(["Pangasinan", "entry", "entry"])
    assert detect_language(pages, LANGUAGES)["confidence"] != "high"


def test_matching_ignores_case_and_diacritics():
    pages = make_pages(["CHAVACANO guide", "Zamboangueno or zamboangueño", "chavacano"])
    result = detect_language(pages, LANGUAGES)
    assert result["suggested_code"] == "cbk"
    assert result["confidence"] == "high"


def test_whole_words_only():
    pages = make_pages(["Tagalogs Tagalogish", "Tagalogs"])
    assert detect_language(pages, LANGUAGES)["confidence"] == "none"


def test_language_file_needs_aliases(tmp_path):
    path = tmp_path / "languages.yml"
    path.write_text("languages:\n  pag:\n    name: Pangasinan\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_languages(path)


def test_fold_removes_accents_for_matching_only():
    assert fold("Zamboangueño") == "zamboangueno"