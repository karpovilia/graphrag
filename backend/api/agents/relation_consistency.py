from __future__ import annotations

from typing import Any

from api.domain.curation import Suggestion
from api.domain.graph import Layer
from api.domain.types import Id
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState


@agents.register(
    "relation_consistency",
    summary="Flag entity relations whose endpoints have no shared chunk evidence.",
    description=(
        "Heuristic that flags ENTITY_RELATION edges whose endpoints are "
        "never co-mentioned in the same CHUNK-layer node — strong "
        "indicator of an LLM hallucinated relation. Wiring lands in "
        "3.x once a chunk-co-mention index is materialized."
    ),
    requires_layers=(Layer.CHUNK, Layer.ENTITY),
    cost_hint="cheap",
)
class RelationConsistencyChecker:
    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        raise NotImplementedError(
            "RelationConsistencyChecker not wired yet — pending chunk co-mention index (Phase 3.x)"
        )
