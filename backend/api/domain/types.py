from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

Id = NewType("Id", UUID)


def new_id() -> Id:
    return Id(uuid4())


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class DomainModel(BaseModel):
    """Base for all domain entities. Strict by default, JSON-serializable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        populate_by_name=True,
        validate_assignment=True,
    )


class Provenance(DomainModel):
    """Where a piece of graph data came from in the source corpus.

    A node or an edge attribution always points back to one or more
    document spans plus the run that produced it.
    """

    document_id: Id
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    extracted_by_run_id: Id | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class EmbeddingRef(DomainModel):
    """Pointer to a vector kept in FAISS (or any other store implementing
    VectorStoreProtocol). The vector itself never lives in PG.
    """

    model: str
    dim: Annotated[int, Field(gt=0)]
    collection: str
    vector_id: str
