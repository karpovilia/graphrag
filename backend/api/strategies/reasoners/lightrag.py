from __future__ import annotations

from typing import Any

from api.domain.graph import Layer
from api.domain.types import Id

from ..protocols import GraphLoader, ReasonResult
from ..registry import reasoners

# Drop function words so matches are carried by content tokens, not "и/the".
_STOP_TOKENS = {
    "и", "в", "на", "с", "о", "у", "по", "из", "для", "что", "как", "кто",
    "где", "когда", "почему", "the", "a", "an", "of", "in", "to", "and", "or",
}


@reasoners.register(
    "lightrag_dual_keyword",
    summary="Dual-level keyword retrieval (low-level entities + high-level themes).",
    description=(
        "Splits retrieval into two levels (LightRAG's local/global pattern): "
        "low-level — entity-layer nodes matching the query's content tokens; "
        "high-level — community-layer nodes (themes) matching tokens in their "
        "name + summary. Composes both into one answer. Keyword-based (no "
        "vector search) so it runs on any built graph; a vector-aware "
        "GraphLoader can later sharpen retrieval without changing the shape."
    ),
    requires_layers=(Layer.ENTITY, Layer.COMMUNITY),
    params_schema={
        "top_k_local": {
            "type": "integer",
            "default": 10,
            "description": "Entity-layer (low-level) nodes to surface.",
        },
        "top_k_global": {
            "type": "integer",
            "default": 5,
            "description": "Community-layer (high-level / theme) nodes to surface.",
        },
        "min_token_length": {
            "type": "integer",
            "default": 3,
            "description": "Drop query tokens shorter than this.",
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2410.05779v3.pdf",),
)
class LightRAGDualKeyword:
    """Stateless. Loader is injected per call. Dual-level keyword retrieval:
    the local level grounds the answer in concrete entities, the global level
    in community themes — the low-/high-level distinction from the F2.4 data
    model, without requiring embeddings or two LLM calls.
    """

    async def reason(
        self,
        query: str,
        graph_variant_ids: list[Id],
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> ReasonResult:
        top_k_local = int(params.get("top_k_local", 10))
        top_k_global = int(params.get("top_k_global", 5))
        min_len = int(params.get("min_token_length", 3))
        tokens = _tokenize(query, min_len)

        local: list[tuple[int, Any]] = []
        global_: list[tuple[int, Any]] = []
        for variant_id in graph_variant_ids:
            for node in await loader.load_nodes(variant_id):
                layer = getattr(node, "layer", None)
                if layer == Layer.ENTITY:
                    score = _score(node, tokens, with_summary=False)
                    if score > 0:
                        local.append((score, node))
                elif layer == Layer.COMMUNITY:
                    # themes live in the summary → match name + summary
                    score = _score(node, tokens, with_summary=True)
                    if score > 0:
                        global_.append((score, node))

        local.sort(key=lambda kv: (-kv[0], str(kv[1].id)))
        global_.sort(key=lambda kv: (-kv[0], str(kv[1].id)))
        top_local = local[:top_k_local]
        top_global = global_[:top_k_global]

        if not top_local and not top_global:
            return ReasonResult(
                text=f"По запросу «{query}» ничего не найдено ни на уровне сущностей, ни на уровне тем.",
                evidence_node_ids=[],
                confidence=0.0,
                metadata={"matched_tokens": sorted(tokens)},
            )

        sections: list[str] = []
        if top_global:
            sections.append(
                "Высокоуровневые темы (communities):\n"
                + "\n".join(
                    f"- {n.name}"
                    + (
                        f": {(getattr(n, 'summary', '') or '')[:160]}"
                        if getattr(n, "summary", None)
                        else ""
                    )
                    for _, n in top_global
                )
            )
        if top_local:
            sections.append(
                "Низкоуровневые сущности:\n"
                + "\n".join(
                    f"- {n.name} (совпадений: {s})"
                    + (
                        f": {(getattr(n, 'summary', '') or '')[:120]}"
                        if getattr(n, "summary", None)
                        else ""
                    )
                    for s, n in top_local
                )
            )

        text = f"По запросу «{query}»:\n\n" + "\n\n".join(sections)
        scores = [s for s, _ in top_local] + [s for s, _ in top_global]
        best = max(scores) if scores else 0
        return ReasonResult(
            text=text,
            evidence_node_ids=[n.id for _, n in top_global]
            + [n.id for _, n in top_local],
            confidence=min(1.0, best / max(len(tokens), 1)),
            metadata={
                "matched_tokens": sorted(tokens),
                "local_count": len(top_local),
                "global_count": len(top_global),
            },
        )


def _tokenize(query: str, min_len: int) -> set[str]:
    return {
        tok
        for tok in (t.lower().strip(".,!?\"'()[]") for t in query.split())
        if len(tok) >= min_len and tok not in _STOP_TOKENS
    }


def _score(node, tokens: set[str], *, with_summary: bool) -> int:
    hay = (node.name or "").lower() if getattr(node, "name", None) else ""
    if with_summary and getattr(node, "summary", None):
        hay = hay + " " + node.summary.lower()
    return sum(1 for tok in tokens if tok in hay)
