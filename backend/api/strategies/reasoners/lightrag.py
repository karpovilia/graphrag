from __future__ import annotations

from typing import Any

from api.domain.graph import Layer
from api.domain.types import Id

from ..protocols import GraphLoader, ReasonResult
from ..registry import reasoners


@reasoners.register(
    "lightrag_dual_keyword",
    summary="Dual-level keyword retrieval (low-level entities + high-level themes).",
    description=(
        "Reasoner that splits the query into local keywords (concrete "
        "entities) and global keywords (abstract themes), retrieves "
        "entity-layer and community-layer nodes separately, and composes "
        "a single answer. The dual-level pattern is the cheapest way "
        "to honor the low-/high-level distinction baked into the F2.4 "
        "data model. Wiring lands in 1.4.x once a vector-search-based "
        "GraphLoader is available."
    ),
    requires_layers=(Layer.ENTITY, Layer.COMMUNITY),
    params_schema={
        "top_k_local": {"type": "integer", "default": 10},
        "top_k_global": {"type": "integer", "default": 5},
    },
    cost_hint="moderate",
    references=("docs/raw/2410.05779v3.pdf",),
)
class LightRAGDualKeyword:
    """Stub. Real impl needs (a) embeddings on entity + community nodes
    via FaissAdapter, (b) an LLM to extract local/global keywords from
    the query and to compose the final answer. Both deps already exist;
    this lands in a follow-up so 1.4 can ship the protocol without
    bundling two LLM calls per request behind a stub.
    """

    async def reason(
        self,
        query: str,
        graph_variant_ids: list[Id],
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> ReasonResult:
        raise NotImplementedError(
            "LightRAGDualKeyword not wired yet — pending vector-aware GraphLoader (Phase 1.4.x)"
        )
