import pytest
from pydantic import ValidationError

from wika_pipeline.schema import DictionaryEntry, ValidationStatus


def make(**overrides):
    base = {"word": "abaka", "dialect_code": "pam", "dialect_name": "Kapampangan"}
    base.update(overrides)
    return DictionaryEntry(**base)


def test_minimal_entry_gets_defaults():
    entry = make()
    assert entry.validation_review_status == ValidationStatus.EXTRACTED
    assert entry.entry_id
    assert entry.created_at
    assert entry.review_flags == []
    assert entry.meaning is None


def test_empty_word_is_rejected():
    with pytest.raises(ValidationError):
        make(word="")


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        make(wrod="typo")


def test_page_must_be_positive():
    with pytest.raises(ValidationError):
        make(source_page=0)


def test_invalid_status_is_rejected():
    with pytest.raises(ValidationError):
        make(validation_review_status="maybe")


def test_legacy_unreviewed_becomes_extracted():
    assert make(validation_review_status="unreviewed").validation_review_status == ValidationStatus.EXTRACTED


def test_diacritics_are_kept_exactly():
    assert make(word="baliñgít").word == "baliñgít"