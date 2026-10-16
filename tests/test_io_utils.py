import pytest

from wika_pipeline.io_utils import load_jsonl


def write_file(tmp_path, text):
    path = tmp_path / "sample.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def test_nan_becomes_none(tmp_path):
    path = write_file(tmp_path, '{"word": "abaka", "etymology": NaN}\n')
    rows = load_jsonl(path)
    assert rows[0]["etymology"] is None


def test_diacritics_are_preserved(tmp_path):
    path = write_file(tmp_path, '{"word": "baliñgít á"}\n')
    rows = load_jsonl(path)
    assert rows[0]["word"] == "baliñgít á"


def test_blank_lines_are_skipped(tmp_path):
    path = write_file(tmp_path, '{"word": "a"}\n\n{"word": "b"}\n')
    assert len(load_jsonl(path)) == 2


def test_bad_json_reports_line_number(tmp_path):
    path = write_file(tmp_path, '{"word": "a"}\n{bad json}\n')
    with pytest.raises(ValueError, match="line 2"):
        load_jsonl(path)