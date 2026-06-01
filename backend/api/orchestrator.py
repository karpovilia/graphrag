"""Synchronous in-memory build pipeline.

Phase 1.5 ships a no-persistence preview path: registry → instantiate
→ run builder → cleaners → clusterer → return GraphBuildState. SSE,
async task tracking, and DB persistence land in 1.5.x once the
repository layer is in.
"""

from __future__ import annotations

from typing import Any

from api.domain.corpus import Document
from api.domain.types import Id, new_id
from api.eda.ner import NerProtocol
from api.llm import CompletionClient
from api.runtime import get_llm, get_ner
from api.strategies import (
    BuilderProtocol,
    CleanerProtocol,
    ClustererProtocol,
    GraphBuildState,
    ProjectorProtocol,
)
from api.strategies.registry import builders, cleaners, clusterers, projectors


class PipelineError(RuntimeError):
    """Build pipeline failed before any LLM call (validation) or during
    execution. Wraps the offending strategy name so the wizard can
    point the user at the right step.
    """

    def __init__(self, message: str, *, stage: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage


def _instantiate_builder(
    name: str,
    *,
    ner: NerProtocol | None,
    llm: CompletionClient | None,
) -> BuilderProtocol:
    cls = builders.get(name)
    # Plugins that need DI: NerExtractionBuilder takes a NerProtocol;
    # LightRAG/Microsoft take a CompletionClient; ToG3/FastRAG stubs take
    # nothing (they raise on call).
    if name == "ner_extraction":
        return cls(ner=ner or get_ner())  # type: ignore[call-arg]
    if name in {"lightrag", "microsoft"}:
        return cls(llm=llm or get_llm())  # type: ignore[call-arg]
    return cls()  # type: ignore[call-arg]


def _instantiate_cleaner(
    name: str, *, llm: CompletionClient | None
) -> CleanerProtocol:
    cls = cleaners.get(name)
    if name == "llm_dedup":
        return cls(llm=llm or get_llm())  # type: ignore[call-arg]
    return cls()  # type: ignore[call-arg]


def _instantiate_clusterer(name: str) -> ClustererProtocol:
    cls = clusterers.get(name)
    return cls()  # type: ignore[call-arg]


def _instantiate_projector(name: str) -> ProjectorProtocol:
    cls = projectors.get(name)
    return cls()  # type: ignore[call-arg]


def validate_pipeline(
    *,
    builder: str,
    cleaner_chain: list[str],
    clusterer: str | None,
    projector: str | None = None,
) -> None:
    """Cheap pre-flight: every name resolves in the registry. Layer
    compatibility (produces vs requires) is enforced post-build by the
    orchestrator; we don't pre-simulate it because cleaners can short-
    circuit on empty input and the layer-set is data-dependent.
    """

    if not builders.has(builder):
        raise PipelineError(
            f"unknown builder {builder!r}. Available: {builders.names()}",
            stage="builder",
        )
    for name in cleaner_chain:
        if not cleaners.has(name):
            raise PipelineError(
                f"unknown cleaner {name!r}. Available: {cleaners.names()}",
                stage="cleaner",
            )
    if clusterer and not clusterers.has(clusterer):
        raise PipelineError(
            f"unknown clusterer {clusterer!r}. Available: {clusterers.names()}",
            stage="clusterer",
        )
    if projector and not projectors.has(projector):
        raise PipelineError(
            f"unknown projector {projector!r}. Available: {projectors.names()}",
            stage="projector",
        )


async def run_build_pipeline(
    *,
    corpus_id: Id,
    documents: list[tuple[Document, str]],
    builder: str,
    cleaner_chain: list[str],
    clusterer: str | None,
    builder_params: dict[str, Any] | None = None,
    cleaner_params: dict[str, dict[str, Any]] | None = None,
    clusterer_params: dict[str, Any] | None = None,
    projector: str | None = None,
    projector_params: dict[str, Any] | None = None,
    graph_variant_id: Id | None = None,
    ner: NerProtocol | None = None,
    llm: CompletionClient | None = None,
) -> tuple[Id, GraphBuildState]:
    """Run builder → cleaners → clusterer in order, returning the
    pre-allocated graph_variant_id and the final state. Raises
    PipelineError for unknown strategy names.

    `ner` and `llm` override the runtime singletons — handy for tests
    and for callers that already have a NerProtocol or CompletionClient
    in hand. None falls back to the lazy singletons in api.runtime.
    """

    validate_pipeline(
        builder=builder,
        cleaner_chain=cleaner_chain,
        clusterer=clusterer,
        projector=projector,
    )

    variant_id = graph_variant_id or new_id()
    builder_inst = _instantiate_builder(builder, ner=ner, llm=llm)

    state = await builder_inst.build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=documents,
        params=builder_params or {},
    )

    for cleaner_name in cleaner_chain:
        cleaner_inst = _instantiate_cleaner(cleaner_name, llm=llm)
        params = (cleaner_params or {}).get(cleaner_name, {})
        state = await cleaner_inst.clean(state, params)

    if clusterer:
        clusterer_inst = _instantiate_clusterer(clusterer)
        state = await clusterer_inst.cluster(state, clusterer_params or {})

    if projector:
        projector_inst = _instantiate_projector(projector)
        state = await projector_inst.project(state, projector_params or {})

    return variant_id, state
