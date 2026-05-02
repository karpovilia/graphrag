from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field

from api.domain.types import DomainModel

Metric = Literal["cosine", "ip", "l2"]


class VecItem(DomainModel):
    id: str
    vector: list[float]
    payload: dict[str, Any] = Field(default_factory=dict)
    """Free-form metadata for filtering. Keep it small — for FAISS this
    lives in a sidecar file on disk and gets loaded with the index.
    """


class SearchHit(DomainModel):
    id: str
    score: float
    payload: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Eq:
    field: str
    value: Any


@dataclass(frozen=True, slots=True)
class In:
    field: str
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class And:
    clauses: tuple["Filter", ...]


@dataclass(frozen=True, slots=True)
class Or:
    clauses: tuple["Filter", ...]


@dataclass(frozen=True, slots=True)
class Not:
    clause: "Filter"


Filter = Eq | In | And | Or | Not
"""Algebraic ADT.

R-02 §6 explains the choice over raw dict / SQL fragments: it's
typeable, backend-agnostic, and small enough that every adapter can
translate it without dragging in a query DSL.
"""


def matches(f: Filter, payload: dict[str, Any]) -> bool:
    """Evaluate a Filter against a metadata dict. Used by the FAISS
    adapter to post-filter search candidates; other adapters may
    translate the same ADT to native filter syntax instead.
    """

    match f:
        case Eq(field, value):
            return payload.get(field) == value
        case In(field, values):
            return payload.get(field) in values
        case And(clauses):
            return all(matches(c, payload) for c in clauses)
        case Or(clauses):
            return any(matches(c, payload) for c in clauses)
        case Not(clause):
            return not matches(clause, payload)


class VectorStoreError(RuntimeError):
    """Backend-agnostic vector store failure."""


@runtime_checkable
class VectorStoreProtocol(Protocol):
    backend: str

    async def create_collection(
        self,
        name: str,
        dim: int,
        metric: Metric = "cosine",
    ) -> None: ...

    async def upsert(self, collection: str, items: list[VecItem]) -> None: ...

    async def delete(self, collection: str, ids: list[str]) -> None: ...

    async def search(
        self,
        collection: str,
        vector: list[float],
        k: int,
        filter: Filter | None = None,
    ) -> list[SearchHit]: ...

    async def drop_collection(self, name: str) -> None: ...
