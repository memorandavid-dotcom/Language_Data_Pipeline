from wika_pipeline.flags_cli import count_flags, entries_with_flag, find_duplicates, format_line, pages_with_flag


def entry(word, meaning="m", page=1, flags=None, homograph=None, pos=None):
    return {
        "word": word,
        "meaning": meaning,
        "source_page": page,
        "review_flags": flags or [],
        "homograph_number": homograph,
        "part_of_speech": pos,
    }


def test_count_flags():
    entries = [entry("a", flags=["no_gloss"]), entry("b", flags=["no_gloss", "cross_reference"]), entry("c")]
    assert count_flags(entries) == {"no_gloss": 2, "cross_reference": 1}


def test_entries_with_flag():
    entries = [entry("a", flags=["no_gloss"]), entry("b")]
    assert [e["word"] for e in entries_with_flag(entries, "no_gloss")] == ["a"]


def test_duplicates_need_same_word_and_meaning():
    entries = [entry("a", "x"), entry("a", "x", page=5), entry("a", "y"), entry("b", "x")]
    groups = find_duplicates(entries)
    assert len(groups) == 1
    assert [e["source_page"] for e in groups[0]] == [1, 5]


def test_format_line_shows_page_homograph_and_truncates():
    line = format_line(entry("yókyok", "x" * 100, page=142, homograph=2), width=10)
    assert line.startswith("p 142 | yókyok [2] => xxxxxxxxxx...")


def test_format_line_marks_missing_meaning():
    assert "(none)" in format_line(entry("a", None))
    

def test_same_word_under_different_parents_is_not_a_duplicate():
    main_entry = entry("limamplo", "fifty", page=83)
    sub_entry = dict(entry("limamplo", "fifty", page=110), parent_headword="polo")
    assert find_duplicates([main_entry, sub_entry]) == []



def test_pages_with_flag_counts_entries_per_page():
    entries = [
        entry("a", page=63, flags=["suspect_page_layout"]),
        entry("b", page=63, flags=["suspect_page_layout"]),
        entry("c", page=5, flags=["suspect_page_layout"]),
        entry("d", page=7),
    ]
    assert pages_with_flag(entries, "suspect_page_layout") == [(5, 1), (63, 2)]    