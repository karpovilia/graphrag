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


class ExpertResult(DomainModel):
    """One expert's contribution to a MoE run. Bundles which variant +
    reasoner produced the result so the aggregator can weight, attribute,
    or surface them in split-view UIs.
    """

    variant_id: Id
    reasoner: str
    result: ReasonResult
    error: str | None = None
    """Set when the expert failed; aggregators decide whether to ignore
    or surface the failure. Result is empty when error is set."""


class _Strategy(Protocol):
    descriptor: StrategyDescriptor


@runtime_checkable
class BuilderProtocol(_Strategy, Protocol):
    """Top-of-pipeline strategy: raw Documents → first GraphBuildState.

    Builders own chunking, entity/relation extraction, and initial
    edge creation. They MUST set `layer`/`granularity` on every Node and
    Edge and use the supplied `graph_variant_id` so downstream cleaners,
    the persistence layer, and the layered viewer (F7) all see a
    consistent variant identity. The orchestrator validates the produced
    layers against `descriptor.produces_layers` post-call.

    Documents arrive paired with their text content — the orchestrator
    is responsible for loading text from blob storage. Builders never
    touch the persistence layer directly.
    """

    async def build(
        self,
        graph_variant_id: Id,
        corpus_id: Id,
        documents: list[tuple[Document, str]],
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


@runtime_checkable
class AggregatorProtocol(_Strategy, Protocol):
    """Folds N ExpertResults into one ReasonResult.

    Plugins may consume an LLM (judge-style) or stay heuristic
    (weighted vote, evidence union). The MoE orchestrator passes the
    same query that drove every expert so judges have full context.
    """

    async def aggregate(
        self,
        query: str,
        expert_results: list[ExpertResult],
        params: dict[str, Any],
    ) -> ReasonResult: ...


@runtime_checkable
class AgentProtocol(_Strategy, Protocol):
    """Curation agent. Walks a GraphBuildState and proposes Suggestions
    that the user accepts or rejects. Agents NEVER mutate the graph
    directly — the orchestrator takes the proposal, the user picks, the
    repository converts accepted suggestions into JournalEntries via
    the Phase 2 applier.
    """

    async def propose(
        self,
        graph_variant_id: Id,
        state: "GraphBuildState",
        params: dict[str, Any],
    ) -> list[Any]: ...
    """Returns Suggestion instances. Avoid the cyclic import with
    api.domain.curation by typing as list[Any] — concrete
    implementations type their return as list[Suggestion]."""
