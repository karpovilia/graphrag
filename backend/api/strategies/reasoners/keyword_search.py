from __future__ import annotations

from typing import Any

from api.domain.types import Id

from ..protocols import GraphLoader, ReasonResult
from ..registry import reasoners

_STOP_TOKENS = {
    "и",
    "в",
    "на",
    "с",
    "о",
    "у",
    "по",
    "из",
    "для",
    "что",
    "как",
    "кто",
    "где",
    "когда",
    "почему",
    "the",
    "a",
    "an",
    "of",
    "in",
    "to",
    "and",
    "or",
}


@reasoners.register(
    "keyword_search",
    summary="Cheap baseline: rank graph nodes by keyword match in name.",
    description=(
        "No LLM — tokenizes the query, lowercases, drops stopwords, "
        "scores each node by the number of distinct query tokens "
        "appearing in `name`. Useful as a sanity floor for MoE and as "
        "a fast smoke test of the Reasoner pipeline."
    ),
    params_schema={
        "top_k": {
            "type": "integer",
            "default": 10,
            "description": "How many nodes to surface as evidence.",
        },
        "min_token_length": {
            "type": "integer",
            "default": 3,
            "description": "Drop query tokens shorter than this.",
        },
    },
    cost_hint="cheap",
)
class KeywordSearchReasoner:
    """Stateless. Loader is injected per call so the orchestrator owns
    persistence-layer wiring and the strategy stays pure.
    """

    async def reason(
        self,
        query: str,
        graph_variant_ids: list[Id],
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> ReasonResult:
        top_k = int(params.get("top_k", 10))
        min_len = int(params.get("min_token_length", 3))
        tokens = _tokenize(query, min_len)

        scored: list[tuple[int, Any]] = []
        for variant_id in graph_variant_ids:
            for node in await loader.load_nodes(variant_id):
                score = _score(node, tokens)
                if score > 0:
                    scored.append((score, node))

        scored.sort(key=lambda kv: (-kv[0], str(kv[1].id)))
        top = scored[:top_k]

        if not top:
            return ReasonResult(
                text=f"По запросу «{query}» ничего не найдено.",
                evidence_node_ids=[],
                confidence=0.0,
            )

        lines = [
            f"- {n.name} (score={s})"
            + (f": {(n.summary or '')[:120]}" if getattr(n, "summary", None) else "")
            for s, n in top
        ]
        text = (
            f"По запросу «{query}» найдено {len(top)} узел(ов) с совпадением:\n"
            + "\n".join(lines)
        )
        max_score = top[0][0] if top else 0
        return ReasonResult(
            text=text,
            evidence_node_ids=[n.id for _, n in top],
            confidence=min(1.0, max_score / max(len(tokens), 1)),
            metadata={"matched_tokens": list(tokens)},
        )


def _tokenize(query: str, min_len: int) -> set[str]:
    return {
        tok
        for tok in (t.lower().strip(".,!?\"'()[]") for t in query.split())
        if len(tok) >= min_len and tok not in _STOP_TOKENS
    }


def _score(node, tokens: set[str]) -> int:
    name_lower = node.name.lower() if node.name else ""
    return sum(1 for tok in tokens if tok in name_lower)
