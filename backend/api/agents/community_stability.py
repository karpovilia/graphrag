from __future__ import annotations

from typing import Any

from api.domain.curation import Suggestion
from api.domain.graph import Layer
from api.domain.types import Id
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState


@agents.register(
    "community_stability",
    summary="Flag entities that hop between communities across variants.",
    description=(
        "Cross-variant heuristic: if the same canonical_id ends up in "
        "different communities across two variants of the same corpus, "
        "the entity is on a community boundary and the user may want to "
        "review. Wiring lands once the orchestrator can fan out a "
        "comparison pass over multiple variants (Phase 4 dependency)."
    ),
    requires_layers=(Layer.ENTITY, Layer.COMMUNITY),
    cost_hint="moderate",
)
class CommunityStabilityScout:
    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        raise NotImplementedError(
            "CommunityStabilityScout not wired yet — needs cross-variant comparison (Phase 4 dep)"
        )
