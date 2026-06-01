from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .types import DomainModel, EmbeddingRef, Id, Provenance, new_id, utcnow


class Layer(StrEnum):
    """The four canonical strata of a heterogeneous GraphRAG graph.

    Granularity grows from chunk (most concrete) to topic (most abstract).
    """

    CHUNK = "chunk"
    ENTITY = "entity"
    COMMUNITY = "community"
    TOPIC = "topic"


class NodeType(DomainModel):
    """Open-set entity type. EDA proposes a starting set per corpus
    (PERSON / ORG / EVENT / PLACE / CONCEPT / MISC), the user can extend.
    Unknown types are valid — they just don't get type-bound NodeTools.
    """

    name: str
    label: str | None = None
    color_hint: str | None = None


class EdgeType(StrEnum):
    """Inter-layer edges plus generic intra-layer relations.

    Specific semantic relations between entities (works_at, mentioned_with,
    ...) live as the `relation` attribute on a generic ENTITY_RELATION edge.
    """

    MENTIONED_IN = "mentioned_in"
    MEMBER_OF = "member_of"
    SUMMARY_OF = "summary_of"
    ENTITY_RELATION = "entity_relation"
    BACKBONE = "backbone"
    """Intra-layer co-occurrence backbone edge produced by a projector.

    Source and target live on the SAME layer; weight is an NPMI-style
    aggregate across all channels (direct edges + projections through
    adjacent layers) that survived the disparity filter. `attributes`
    carries `layer`, `channels` (per-channel contributions), and
    `alpha` (the disparity p-value on the keep side) for inspection."""


class GraphVariantStatus(StrEnum):
    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class EdgeInvalidation(DomainModel):
    """Why and when an edge was killed (bi-temporal §1.4 provenance).

    Attached to Edge.invalidation when an ingestion event (or a manual
    curation delete carrying a `reason`) retires an edge instead of
    plainly deleting it. The §2.4 revert flow re-adds the edge and clears
    this record, preserving the audit trail.
    """

    ingestion_event_id: Id | None = None
    at: datetime
    reason: str
    superseded_by_edge_id: Id | None = None
    auto: bool = True


class Node(DomainModel):
    id: Id = Field(default_factory=new_id)
    graph_variant_id: Id
    canonical_id: Id | None = None
    """Stable identity across GraphVariants of the same Corpus.

    Two nodes with the same canonical_id in different GraphVariants are
    the same real-world entity — used by the layered viewer for
    cross-variant selection in MoE split-view.
    """

    layer: Layer
    type: str
    """Free-form type. EDA-suggested values match NodeType registry; novel
    values are accepted but won't get type-bound tools.
    """

    granularity: int = Field(ge=0)
    """Higher = more abstract. CHUNK ≈ 0, ENTITY ≈ 1, COMMUNITY ≈ 2,
    TOPIC ≈ 3. Per-layer numeric scale lets EDA suggest finer steps.
    """

    name: str
    summary: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)
    embedding: EmbeddingRef | None = None

    # ---- bi-temporal stamps (§0/§1) ----
    # All nullable so existing JSON/preview states deserialize unchanged.
    valid_from: datetime | None = None
    """event time T start — when the fact became true in the world."""
    valid_to: datetime | None = None
    """event time T end (None = still valid)."""
    tx_from: datetime | None = None
    """ingestion/transaction time T' start — when we learned the fact."""
    tx_to: datetime | None = None
    """ingestion time T' end (None = still current)."""


class Edge(DomainModel):
    id: Id = Field(default_factory=new_id)
    graph_variant_id: Id
    type: EdgeType
    source_node_id: Id
    target_node_id: Id
    weight: float | None = None
    relation: str | None = None
    """For ENTITY_RELATION edges — the textual predicate (e.g. "works_at"
    in Russian morphology-aware form). None for inter-layer edges.
    """

    explanation: str | None = None
    provenance: list[Provenance] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    # ---- bi-temporal stamps (§0/§1), identical semantics to Node ----
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    tx_from: datetime | None = None
    tx_to: datetime | None = None

    invalidation: EdgeInvalidation | None = None
    """Why/when/by-which-event this edge died (§1.4). None = live edge."""


class GraphVariant(DomainModel):
    """One materialized graph for a Corpus under a specific build recipe.

    The recipe (builder/cleaner/clusterer/summarizer + their params + LLM
    versions + seeds) is what makes a variant reproducible. Multiple
    variants per Corpus are the substrate of MoE reasoning.
    """

    id: Id = Field(default_factory=new_id)
    corpus_id: Id
    name: str
    status: GraphVariantStatus = GraphVariantStatus.PENDING
    builder: str
    cleaner_chain: list[str] = Field(default_factory=list)
    clusterer: str | None = None
    summarizer: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    """Resolved parameters of every stage: enough to rebuild from scratch."""

    llm_models: dict[str, str] = Field(default_factory=dict)
    seed: int | None = None
    node_count: int = Field(default=0, ge=0)
    edge_count: int = Field(default=0, ge=0)
    layers_present: list[Layer] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    parent_variant_id: Id | None = None
    """If this variant was forked from another (e.g. cleaner re-run), the
    parent is recorded so the journal can be replayed.
    """

    version: int = Field(default=0, ge=0)
    """Optimistic-lock counter. Incremented on every persisted curation op
    via the journal. Concurrent edits with stale `expected_version`
    return 409 from the API."""


class GraphLayout(DomainModel):
    """Cached force-layout positions for a variant.

    Re-running d3-force on every page load for a 1.5k-node graph is the
    main "долго укладывается" UX complaint. We persist `(node_id → (x,y))`
    per (variant_id, user_id) so a returning visitor sees their last
    arrangement instantly. user_id is nullable: anonymous writes feed the
    shared pool that any first-time visitor falls back to.
    """

    graph_variant_id: Id
    user_id: Id | None = None
    positions: dict[str, tuple[float, float]] = Field(default_factory=dict)
    """Mapping from node id (str-UUID) → (x, y). Nodes missing from the
    map fall through to the lib's random init at load time; nodes in the
    map but absent from the graph are silently ignored."""

    updated_at: datetime = Field(default_factory=utcnow)
