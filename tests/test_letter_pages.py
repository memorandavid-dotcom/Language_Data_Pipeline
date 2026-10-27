from wika_pipeline.parsers.column_dictionary import is_letter_heading, kind_of, split_footer

PROFILE = {
    "running_title": "PANGASINAN DICTIONARY",
    "main_headword_x": 54.0,
    "subentry_indent": 18.0,
    "x_tolerance": 3.0,
    "gloss_min_x": 100.0,
}


def row(text, x0):
    return {"text": text, "x0": x0}


def test_letter_opening_page_without_running_title_is_accepted():
    rows = [row("CH", 207.8), row("chá", 54.0), row("tea", 118.8), row("29", 209.6)]
    body, found = split_footer(rows, PROFILE)
    assert found is True
    assert [r["text"] for r in body] == ["chá", "tea"]


def test_normal_page_still_needs_its_running_title():
    rows = [row("chá", 54.0), row("tea", 118.8), row("29", 209.6)]
    body, found = split_footer(rows, PROFILE)
    assert found is False
    assert len(body) == 3


def test_heading_must_be_short_uppercase_and_indented():
    assert is_letter_heading(row("B", 212.3), PROFILE)
    assert is_letter_heading(row("CH", 207.8), PROFILE)
    assert not is_letter_heading(row("baág", 212.3), PROFILE)
    assert not is_letter_heading(row("B", 54.0), PROFILE)
    assert not is_letter_heading(row("b", 212.3), PROFILE)


def test_last_line_must_be_a_page_number():
    rows = [row("B", 212.3), row("baág", 54.0), row("cooked", 180.3)]
    body, found = split_footer(rows, PROFILE)
    assert found is False


def test_gloss_at_x_118_8_is_a_gloss_with_the_new_threshold():
    assert kind_of(118.8, PROFILE) == "gloss"
    assert kind_of(72.0, PROFILE) == "subheadword"
    assert kind_of(54.0, PROFILE) == "headword"
    
def test_combined_letter_heading_with_slash_is_accepted():
    rows = [row("H/J", 208.0), row("jardín", 54.0), row("garden", 146.2), row("45", 209.6)]
    body, found = split_footer(rows, PROFILE)
    assert found is True
    assert [r["text"] for r in body] == ["jardín", "garden"]


def test_a_lone_slash_is_not_a_heading():
    assert not is_letter_heading(row("/", 208.0), PROFILE)