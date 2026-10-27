import pytest

from wika_pipeline.find_cli import format_matches, matching_numbers, parse_args


def rows(texts):
    return [{"x0": 54.0, "y0": float(n * 12), "text": text, "styles": ["F 10.0pt"]} for n, text in enumerate(texts)]


TEXTS = ["alpha", "beta", "arína, harína /arína/ flour", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]


def test_matching_ignores_accents_and_case():
    assert matching_numbers(rows(TEXTS), "ARINA", 0) == [2]


def test_context_adds_lines_before_and_after():
    assert matching_numbers(rows(TEXTS), "arina", 1) == [1, 2, 3]


def test_context_is_clipped_at_the_page_edges():
    assert matching_numbers(rows(TEXTS), "alpha", 2) == [0, 1, 2]


def test_gaps_between_matches_are_marked():
    text = format_matches(1, rows(TEXTS), "a", context=0)
    assert "   ..." in text


def test_output_has_real_line_numbers_and_positions():
    text = format_matches(27, rows(TEXTS), "arina", context=1)
    assert "  3| x=54.0   y=24.0" in text
    assert "arína, harína /arína/ flour" in text
    assert "alpha" not in text


def test_no_match_says_so():
    assert "no line contains 'zzz'" in format_matches(5, rows(TEXTS), "zzz")


def test_parse_args():
    assert parse_args(["a.pdf", "27", "arina"]) == ("a.pdf", 27, "arina", 4)
    assert parse_args(["a.pdf", "27", "arina", "--context", "7"]) == ("a.pdf", 27, "arina", 7)
    with pytest.raises(SystemExit, match="--context needs"):
        parse_args(["a.pdf", "27", "arina", "--context"])
    with pytest.raises(SystemExit, match="Usage"):
        parse_args(["a.pdf", "27"])
    with pytest.raises(SystemExit, match="PAGE"):
        parse_args(["a.pdf", "x", "arina"])