from __future__ import annotations

from typing import Any

from api.domain.graph import EdgeType

from ..registry import cleaners
from ..state import GraphBuildState


@cleaners.register(
    "threshold_prune",
    summary="Drop edges below a weight threshold.",
    description=(
        "Removes weak edges to suppress LLM-extraction noise before "
        "clustering. Cheap, no model calls. Used as the first step of "
        "the default cleaner chain that EDA recommends for any corpus."
    ),
    params_schema={
        "weight_threshold": {
            "type": "number",
            "default": 0.0,
            "description": "Minimum edge weight to keep; edges with weight strictly below are dropped.",
        },
        "edge_types": {
            "type": "array",
            "items": {"type": "string"},
            "default": None,
            "description": "Restrict pruning to specific edge types; null means all types.",
        },
        "drop_unweighted": {
            "type": "boolean",
            "default": False,
            "description": "Treat edges with weight=null as below threshold (default: keep them).",
        },
    },
    cost_hint="cheap",
    references=("docs/raw/2410.05779v3.pdf",),
)
class ThresholdPruner:
    """Prune low-confidence edges by weight.

    Doesn't touch nodes — orphans survive. The plan's case study 2
    (gazeta news) shows weak relations spanning unrelated communities
    as the dominant noise source there; this is the first knob to turn.
    """

    async def clean(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState:
        threshold = float(params.get("weight_threshold", 0.0))
        type_filter_raw = params.get("edge_types")
        drop_unweighted = bool(params.get("drop_unweighted", False))

        type_filter: set[str] | None = None
        if type_filter_raw is not None:
            type_filter = {
                t.value if isinstance(t, EdgeType) else str(t)
                for t in type_filter_raw
            }

        kept = [e for e in state.edges if _keeps(e, threshold, type_filter, drop_unweighted)]
        return GraphBuildState(nodes=state.nodes, edges=kept, journal=list(state.journal))


def _keeps(
    edge,
    threshold: float,
    type_filter: set[str] | None,
    drop_unweighted: bool,
) -> bool:
    if type_filter is not None and edge.type.value not in type_filter:
        return True
    if edge.weight is None:
        return not drop_unweighted
    return edge.weight >= threshold
