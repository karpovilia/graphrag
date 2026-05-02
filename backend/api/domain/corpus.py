from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .types import DomainModel, Id, new_id, utcnow


class DocumentSpan(DomainModel):
    """Stable byte-range identifier inside a Document.

    Spans persist across pipeline reruns so attribution stays valid even
    when the entity that referenced them is recomputed.
    """

    span_id: Id = Field(default_factory=new_id)
    document_id: Id
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text_hash: str


class Document(DomainModel):
    id: Id = Field(default_factory=new_id)
    corpus_id: Id
    title: str
    source_uri: str | None = None
    language: str = "ru"
    char_length: int = Field(ge=0)
    sha256: str
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Corpus(DomainModel):
    """A logical collection of documents that share extraction settings.

    A Corpus has zero or more GraphVariant rebuilt from it under different
    builder/cleaner/clusterer choices.
    """

    id: Id = Field(default_factory=new_id)
    name: str
    description: str | None = None
    language: str = "ru"
    created_at: datetime = Field(default_factory=utcnow)
    document_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
