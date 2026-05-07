from __future__ import annotations

from collections import defaultdict
from typing import Any

from api.domain.curation import Suggestion, SuggestionAction
from api.domain.graph import EdgeType, Layer
from api.domain.types import Id
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState


@agents.register(
    "orphan_rescuer",
    summary="Flag isolated entities that look misplaced relative to neighbors.",
    description=(
        "Heuristic. An ENTITY-layer node is an orphan if it has no "
        "ENTITY_RELATION edges to other entity-layer nodes. The agent "
        "DELETES nothing — it surfaces orphans so the user can either "
        "merge them into an existing entity (manual MERGE) or accept "
        "the auto-suggested DELETE if no neighbor is a plausible "
        "match. This is the simplest version; lemma-based candidate "
        "matching ships in 3.x."
    ),
    requires_layers=(Layer.ENTITY,),
    params_schema={
        "min_total_degree_to_skip": {
            "type": "integer",
            "default": 1,
            "description": "Nodes with this many or more entity-layer edges are not orphans.",
        },
    },
    cost_hint="cheap",
)
class OrphanRescuer:
    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        threshold = int(params.get("min_total_degree_to_skip", 1))

        entity_ids = {n.id for n in state.nodes if n.layer == Layer.ENTITY}
        degree: dict[Id, int] = defaultdict(int)
        for edge in state.edges:
            if edge.type != EdgeType.ENTITY_RELATION:
                continue
            if edge.source_node_id in entity_ids:
                degree[edge.source_node_id] += 1
            if edge.target_node_id in entity_ids:
                degree[edge.target_node_id] += 1

        suggestions: list[Suggestion] = []
        for node in state.nodes:
            if node.layer != Layer.ENTITY:
                continue
            if degree[node.id] >= threshold:
                continue
            suggestions.append(
                Suggestion(
                    graph_variant_id=graph_variant_id,
                    agent="orphan_rescuer",
                    action=SuggestionAction.DELETE,
                    target_node_ids=[node.id],
                    payload={"node_id": str(node.id)},
                    confidence=0.5,
                    rationale=(
                        f"Entity {node.name!r} has zero ENTITY_RELATION "
                        f"edges to other entity-layer nodes. Likely "
                        f"extraction noise."
                    ),
                )
            )
        return suggestions
