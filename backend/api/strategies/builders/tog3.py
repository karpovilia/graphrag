from __future__ import annotations

from typing import Any

from api.domain.corpus import Document
from api.domain.graph import Layer
from api.domain.types import Id

from ..registry import builders
from ..state import GraphBuildState


@builders.register(
    "tog3",
    summary="ToG-3 heterogeneous Chunk-Triplet-Community graph.",
    description=(
        "Heterogeneous builder that materializes Chunk, Triplet, and "
        "Community node types under a single 1024-d embedding space. "
        "Pairs with the MACER multi-agent reasoner. Heavy; reserved "
        "for cases where MoE diversity benefits from a structurally "
        "different graph variant alongside Microsoft/LightRAG."
    ),
    produces_layers=(Layer.CHUNK, Layer.ENTITY, Layer.COMMUNITY, Layer.TOPIC),
    params_schema={
        "embedding_model": {"type": "string", "default": "intfloat/multilingual-e5-large"},
        "triplet_extractor": {"type": "string", "default": "lightweight_llm"},
    },
    cost_hint="expensive",
    references=("docs/raw/2509.21710v2.pdf",),
)
class ToG3Builder:
    async def build(
        self,
        graph_variant_id: Id,
        corpus_id: Id,
        documents: list[tuple[Document, str]],
        params: dict[str, Any],
    ) -> GraphBuildState:
        raise NotImplementedError(
            "ToG3Builder not wired yet — pending heterogeneous extractor (Phase 1.2.x)"
        )
