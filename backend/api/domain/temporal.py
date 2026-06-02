"""Bi-temporal domain models (§0–§2).

The graph carries two time axes:
  - T  (event / valid time): when a fact is true in the world.
  - T' (transaction / ingestion time): when the system learned the fact.

`IngestionEvent` is one unit on the scrubber axis (one episode ingest).
`Snapshot` is a named, persisted point on either axis. The `Temporal*`
response models are the wire shapes consumed by the §0 grammar frontend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .graph import EdgeInvalidation
from .types import DomainModel, Id, new_id, utcnow


class IngestionEvent(DomainModel):
    """One unit on the timeline scrubber (§2.1).

    Typically emitted once per podcast episode: `event_time` is the
    episode/publication date (T), `ingested_at` is the build time (T').
    """

    id: Id = Field(default_factory=new_id)
    corpus_id: Id
    graph_variant_id: Id | None = None
    label: str
    event_time: datetime
    """T — episode/publication date."""
    ingested_at: datetime = Field(default_factory=utcnow)
    """T' — when this batch of facts was ingested."""
    source_uri: str | None = None
    kind: str = "episode"
    event_count: int = 0
    """How many underlying source events (messages/utterances) fell in this
    bucket — drives the activity histogram on the scrubber (§2.1)."""
    metadata: dict = Field(default_factory=dict)


class Snapshot(DomainModel):
    """A named point on the temporal axis for a variant."""

    id: Id = Field(default_factory=new_id)
    graph_variant_id: Id
    label: str
    as_of_tx: datetime | None = None
    as_of_valid: datetime | None = None
    ingestion_event_id: Id | None = None
    created_at: datetime = Field(default_factory=utcnow)


TemporalState = Literal["born", "dead", "persisted", "moved_community", "invalidated"]


class TemporalDiffEntry(DomainModel):
    """One node or edge classified into the §0 grammar at a diff."""

    id: Id
    kind: Literal["node", "edge"]
    state: TemporalState
    from_community_id: Id | None = None
    to_community_id: Id | None = None
    invalidation: EdgeInvalidation | None = None


class TemporalDiff(DomainModel):
    """The full §0 grammar bucketing between two materialized states."""

    variant_id: Id
    axis: Literal["tx", "valid"]
    t_a: datetime
    t_b: datetime
    born: list[TemporalDiffEntry] = Field(default_factory=list)
    dead: list[TemporalDiffEntry] = Field(default_factory=list)
    persisted: list[TemporalDiffEntry] = Field(default_factory=list)
    moved_community: list[TemporalDiffEntry] = Field(default_factory=list)
    invalidated: list[TemporalDiffEntry] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class RecomputeTiming(DomainModel):
    """Wall-clock + size after a curation op — powers the §2.3 badge."""

    recompute_ms: float
    node_count_after: int
    edge_count_after: int


class QueryDeltaResponse(DomainModel):
    """Wraps a MoE answer with the lit/dimmed subgraph (§2.2 query-delta).

    `moe` is the unchanged MoEResult; the *_ids lists let the frontend
    light the evidence (alpha 1.0) and dim the complement.
    """

    moe: dict
    """Serialized MoEResult — kept as dict to avoid an import cycle with
    api.moe at the domain layer."""

    variant_id: Id
    evidence_node_ids: list[Id] = Field(default_factory=list)
    evidence_edge_ids: list[Id] = Field(default_factory=list)
    total_node_ids: list[Id] = Field(default_factory=list)
    total_edge_ids: list[Id] = Field(default_factory=list)
