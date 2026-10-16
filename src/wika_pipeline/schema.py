from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ValidationStatus(str, Enum):
    EXTRACTED = "extracted"
    PENDING_REVIEW = "pending_review"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CORRECTION = "needs_correction"


LEGACY_STATUS_MAP = {"unreviewed": "extracted"}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class DictionaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    word: str = Field(min_length=1)
    dialect_code: str = Field(min_length=1)
    dialect_name: str = Field(min_length=1)
    part_of_speech: Optional[str] = None
    speech_register: Optional[str] = None
    meaning: Optional[str] = None
    etymology: Optional[str] = None
    phonetic: Optional[str] = None
    synonyms: Optional[str] = None
    tags: Optional[str] = None
    hyphenation: Optional[str] = None
    canonical_form: Optional[str] = None
    pronunciation_guide: Optional[str] = None

    validation_review_status: ValidationStatus = ValidationStatus.EXTRACTED

    source_document_id: Optional[str] = None
    source_file: Optional[str] = None
    source_page: Optional[int] = Field(default=None, ge=1)
    extraction_method: Optional[str] = None
    parser_version: Optional[str] = None
    review_flags: List[str] = Field(default_factory=list)
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)

    @field_validator("validation_review_status", mode="before")
    @classmethod
    def map_legacy_status(cls, value):
        if value is None:
            return ValidationStatus.EXTRACTED
        return LEGACY_STATUS_MAP.get(value, value)