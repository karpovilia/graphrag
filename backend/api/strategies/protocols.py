from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from api.domain.corpus import Document
from api.domain.types import DomainModel, Id

from .descriptor import StrategyDescriptor
from .state import GraphBuildState


class ReasonResult(DomainModel):
    """Per-Reasoner output. The MoE aggregator (Phase 4) composes one of
    these per expert into a final answer.
    """

    text: str
    evidence_node_ids: list[Id] = Field(default_factory=list)
    evidence_edge_ids: list[Id] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cost_tokens: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class _Strategy(Protocol):
    descriptor: StrategyDescriptor


@runtime_checkable
class BuilderProtocol(_Strategy, Protocol):
    """Top-of-pipeline strategy: raw Documents → first GraphBuildState.

    Builders own LLM extraction, span chunking, and initial entity/edge
    creation. They MUST set `layer`/`granularity` on every Node and Edge
    they produce so downstream cleaners and the layered viewer (F7)
    work correctly. Validated post-call by the orchestrator against
    `descriptor.produces_layers`.
    """

    async def build(
        self,
        corpus_id: Id,
        documents: list[Document],
        params: dict[str, Any],
    ) -> GraphBuildState: ...


@runtime_checkable
class CleanerProtocol(_Strategy, Protocol):
    """Mid-pipeline mutator. Pure-ish: state in, state out, no I/O.

    Operations performed are appended to `state.journal` so the variant
    that lands in the DB carries a replay-able trace of how it was
    built. Cleaners may not invent layers — they refine what builders
    produced.
    """

    async def clean(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState: ...


@runtime_checkable
class ClustererProtocol(_Strategy, Protocol):
    """Specialized cleaner that produces community-layer nodes plus
    MEMBER_OF edges from entity-layer nodes. Sequencing is the
    orchestrator's job: cluster after cleaners, before summarizers.
    """

    async def cluster(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState: ...


@runtime_checkable
class ReasonerProtocol(_Strategy, Protocol):
    """Read-side strategy. Takes a query and one or more graph variants;
    returns text + an evidence subgraph. The variants are loaded by id —
    Reasoners get a `loader` callable from the orchestrator so they
    don't depend on the persistence layer directly.
    """

    async def reason(
        self,
        query: str,
        graph_variant_ids: list[Id],
        params: dict[str, Any],
        loader: "GraphLoader",
    ) -> ReasonResult: ...


class GraphLoader(Protocol):
    """Minimal contract for loading a variant's nodes/edges from any
    persistence backend. Concrete implementation lands with the
    repository layer in Phase 1.5.
    """

    async def load_nodes(self, graph_variant_id: Id) -> list[Any]: ...
    async def load_edges(self, graph_variant_id: Id) -> list[Any]: ...
