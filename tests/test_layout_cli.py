import pytest

from wika_pipeline.layout import format_report
from wika_pipeline.layout_cli import parse_args


def rows(count):
    return [{"x0": 54.0, "y0": float(n), "text": f"line{n}", "styles": ["F 10.0pt"]} for n in range(1, count + 1)]


def test_parse_args_reads_pages_and_tail():
    assert parse_args(["a.pdf", "41", "143", "--tail", "6"]) == ("a.pdf", [41, 143], 6)
    assert parse_args(["a.pdf", "41"]) == ("a.pdf", [41], 0)


def test_parse_args_rejects_bad_tail():
    with pytest.raises(SystemExit, match="--tail needs"):
        parse_args(["a.pdf", "41", "--tail"])
    with pytest.raises(SystemExit, match="--tail needs"):
        parse_args(["a.pdf", "41", "--tail", "x"])


def test_tail_shows_the_last_lines_with_real_line_numbers():
    text = format_report(1, rows(50), max_lines=10, tail=3)
    assert "Last 3 lines:" in text
    assert " 48| x=54.0" in text and " 50| x=54.0" in text
    assert "line47" not in text


def test_tail_is_skipped_when_it_would_repeat_lines():
    text = format_report(1, rows(8), max_lines=10, tail=3)
    assert "Last" not in text


def test_tail_does_not_repeat_the_first_lines():
    text = format_report(1, rows(12), max_lines=10, tail=6)
    assert "Last 2 lines:" in text