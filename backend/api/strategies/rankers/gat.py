from __future__ import annotations

from typing import Any

from api.domain.graph import Node
from api.strategies.registry import rankers


@rankers.register(
    "gat",
    summary="2-layer GAT relevance ranker over the retrieval shortlist.",
    description=(
        "F5 GNN ranker. Architecture: 2-layer Graph Attention Network "
        "(PyG-flavored) over the kNN+2-hop subgraph the reasoner surfaced. "
        "Node features = embedding ⊕ degree ⊕ layer-one-hot; edge features "
        "= type ⊕ weight. Training in 5.x — synthetic queries from "
        "community reports (positive=community members, negative=random "
        "nodes), feedback-loop seeded by 'irrelevant' marks from the UI. "
        "Inference falls back to TfIdfCosineRanker until weights are "
        "trained and shipped."
    ),
    params_schema={
        "weights_path": {
            "type": "string",
            "default": "",
            "description": "Path to a trained GAT checkpoint. Empty triggers fallback.",
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2405.16506v3.pdf", "docs/raw/2509.21710v2.pdf"),
)
class GATRanker:
    async def rank(
        self,
        query: str,
        candidates: list[Node],
        params: dict[str, Any],
    ) -> list[Node]:
        raise NotImplementedError(
            "GATRanker not wired yet — pending PyTorch+PyG dependency and "
            "training script (Phase 5.x). Use 'tfidf_cosine' as fallback."
        )
