from __future__ import annotations

from typing import Any

from api.domain.graph import Layer
from api.domain.types import Id

from ..protocols import GraphLoader, ReasonResult
from ..registry import reasoners


@reasoners.register(
    "microsoft_global",
    summary="Map-reduce over community summaries (Microsoft GraphRAG global search).",
    description=(
        "Adapter over the PyPI graphrag package's global_search. Walks "
        "every community report, asks the LLM to score relevance per "
        "shard, then reduces to a single answer. Handles broad questions "
        "well (e.g. «What are the main themes?»). Wiring lands in 1.4.x "
        "once the MicrosoftBuilder produces graphrag-compatible outputs."
    ),
    requires_layers=(Layer.COMMUNITY, Layer.TOPIC),
    params_schema={
        "max_data_tokens": {"type": "integer", "default": 12000},
        "min_community_rank": {"type": "integer", "default": 0},
    },
    cost_hint="expensive",
    references=("docs/raw/2509.21710v2.pdf",),
)
class MicrosoftGlobalSearch:
    """Stub. Real wiring depends on MicrosoftBuilder (1.2) producing a
    graphrag-compatible artifact directory; the adapter is then a thin
    `await graphrag.api.global_search(...)` call.
    """

    async def reason(
        self,
        query: str,
        graph_variant_ids: list[Id],
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> ReasonResult:
        raise NotImplementedError(
            "MicrosoftGlobalSearch not wired yet — pending MicrosoftBuilder (Phase 1.2.x)"
        )


@reasoners.register(
    "microsoft_local",
    summary="Entity-centric retrieval (Microsoft GraphRAG local search).",
    description=(
        "Adapter over the PyPI graphrag package's local_search. Picks "
        "entities by embedding similarity to the query, expands to their "
        "neighborhood, includes covering text units, and asks the LLM "
        "for a focused answer. Handles narrow questions about a specific "
        "entity. Was commented out in the legacy app; brought back as a "
        "first-class plugin here."
    ),
    requires_layers=(Layer.ENTITY,),
    params_schema={
        "top_k_entities": {"type": "integer", "default": 10},
        "top_k_relationships": {"type": "integer", "default": 10},
        "text_unit_prop": {"type": "number", "default": 0.5},
    },
    cost_hint="expensive",
    references=("docs/raw/2509.21710v2.pdf",),
)
class MicrosoftLocalSearch:
    """Stub. Same dependency story as MicrosoftGlobalSearch."""

    async def reason(
        self,
        query: str,
        graph_variant_ids: list[Id],
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> ReasonResult:
        raise NotImplementedError(
            "MicrosoftLocalSearch not wired yet — pending MicrosoftBuilder (Phase 1.2.x)"
        )
