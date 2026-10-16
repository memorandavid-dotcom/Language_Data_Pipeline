from wika_pipeline.audit import audit_rows


def row(**overrides):
    base = {"word": "abaka", "dialect_code": "pam", "dialect_name": "Kapampangan",
            "part_of_speech": "n.", "meaning": "abaca plant"}
    base.update(overrides)
    return base


def test_counts_clean_rows():
    report = audit_rows([row(word="a"), row(word="b")])
    assert report["total_rows"] == 2
    assert report["schema_invalid"] == 0
    assert report["exact_duplicates"] == 0


def test_detects_missing_word_with_line_number():
    report = audit_rows([row(), row(word=None)])
    assert report["schema_invalid"] == 1
    assert report["invalid_line_numbers"] == [2]


def test_detects_empty_meaning():
    report = audit_rows([row(meaning=None), row(word="b", meaning="  ")])
    assert report["empty_meaning"] == 2


def test_detects_exact_duplicates():
    report = audit_rows([row(), row()])
    assert report["exact_duplicates"] == 1


def test_same_word_different_meaning_is_not_duplicate():
    report = audit_rows([row(meaning="one"), row(meaning="two")])
    assert report["exact_duplicates"] == 0


def test_legacy_unreviewed_is_counted_as_extracted():
    report = audit_rows([row(validation_review_status="unreviewed")])
    assert report["status_counts"]["extracted"] == 1