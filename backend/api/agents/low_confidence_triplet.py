from __future__ import annotations

from typing import Any

from api.domain.curation import Suggestion, SuggestionAction
from api.domain.graph import EdgeType
from api.domain.types import Id
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState


@agents.register(
    "low_confidence_triplet",
    summary="Flag low-weight ENTITY_RELATION edges as candidates for deletion.",
    description=(
        "Heuristic. Surfaces entity-relation edges whose weight is below "
        "a threshold — typically these are spurious extractions or weak "
        "co-occurrences. Each flagged edge becomes a DELETE Suggestion. "
        "Pairs naturally with the ThresholdPruner cleaner: agents flag, "
        "user reviews, edits land in the journal. ThresholdPruner is "
        "fire-and-forget at build time; this is the post-hoc curation "
        "knob."
    ),
    params_schema={
        "weight_threshold": {
            "type": "number",
            "default": 0.3,
            "description": "Edges strictly below this weight are flagged.",
        },
        "max_suggestions": {
            "type": "integer",
            "default": 200,
        },
    },
    cost_hint="cheap",
)
class LowConfidenceTriplet:
    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        threshold = float(params.get("weight_threshold", 0.3))
        cap = int(params.get("max_suggestions", 200))

        suggestions: list[Suggestion] = []
        # Sort weakest-first so the cap surfaces the most suspect edges.
        candidates = [
            e
            for e in state.edges
            if e.type == EdgeType.ENTITY_RELATION
            and e.weight is not None
            and e.weight < threshold
        ]
        candidates.sort(key=lambda e: (e.weight or 0.0, str(e.id)))

        node_by_id = {n.id: n for n in state.nodes}
        for edge in candidates[:cap]:
            src = node_by_id.get(edge.source_node_id)
            tgt = node_by_id.get(edge.target_node_id)
            src_name = src.name if src else str(edge.source_node_id)
            tgt_name = tgt.name if tgt else str(edge.target_node_id)
            suggestions.append(
                Suggestion(
                    graph_variant_id=graph_variant_id,
                    agent="low_confidence_triplet",
                    action=SuggestionAction.DELETE,
                    target_edge_ids=[edge.id],
                    payload={"edge_id": str(edge.id)},
                    confidence=_confidence_from_weight(edge.weight or 0.0, threshold),
                    rationale=(
                        f"Edge {src_name!r} → {tgt_name!r} "
                        f"(relation={edge.relation or 'unspecified'}) has "
                        f"weight {edge.weight:.3f} < {threshold:.2f}."
                    ),
                )
            )
        return suggestions


def _confidence_from_weight(weight: float, threshold: float) -> float:
    """Lower weight → higher confidence the edge should die. 0.5 at the
    threshold, asymptoting toward 0.95 at zero weight.
    """

    if threshold <= 0:
        return 0.5
    ratio = max(0.0, 1.0 - (weight / threshold))
    return min(0.95, 0.5 + 0.45 * ratio)
