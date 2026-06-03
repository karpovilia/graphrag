from __future__ import annotations

from datetime import datetime, timezone
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
        "recency_boost": {
            "type": "number",
            "default": 0.0,
            "description": (
                "Temporal mode: weight recently-changed nodes higher. 0 = off. "
                "A node's score is multiplied by (1 + boost·0.5^(age/half_life)) "
                "where age = as_of − tx_from."
            ),
        },
        "half_life_days": {
            "type": "number",
            "default": 30.0,
            "description": "Recency half-life in days (smaller = sharper recency preference).",
        },
        "as_of": {
            "type": "string",
            "default": "",
            "description": (
                "ISO instant the recency is measured against (the selected "
                "period's end). Empty → the latest tx_from in the graph."
            ),
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
        recency_boost = float(params.get("recency_boost", 0.0))
        half_life = max(0.5, float(params.get("half_life_days", 30.0)))
        as_of = _parse_dt(str(params.get("as_of") or ""))
        tokens = _tokenize(query, min_len)

        # Pass 1: collect matches with their raw token-overlap count.
        local_raw: list[tuple[int, Any]] = []
        global_raw: list[tuple[int, Any]] = []
        for variant_id in graph_variant_ids:
            for node in await loader.load_nodes(variant_id):
                layer = getattr(node, "layer", None)
                if layer == Layer.ENTITY:
                    s = _score(node, tokens, with_summary=False)
                    if s > 0:
                        local_raw.append((s, node))
                elif layer == Layer.COMMUNITY:
                    s = _score(node, tokens, with_summary=True)
                    if s > 0:
                        global_raw.append((s, node))

        # Temporal mode: reference = explicit as_of, else the latest tx_from
        # among the matches (recency relative to what the graph knows).
        if recency_boost > 0 and as_of is None:
            stamps = [
                getattr(n, "tx_from", None)
                for _, n in (local_raw + global_raw)
                if getattr(n, "tx_from", None) is not None
            ]
            as_of = max(stamps) if stamps else None

        def effective(raw: int, node: Any) -> float:
            return raw * _recency_mult(node, as_of, recency_boost, half_life)

        # (effective_score, raw_count, node) — sort by effective, show raw.
        local = [(effective(s, n), s, n) for s, n in local_raw]
        global_ = [(effective(s, n), s, n) for s, n in global_raw]
        local.sort(key=lambda kv: (-kv[0], str(kv[2].id)))
        global_.sort(key=lambda kv: (-kv[0], str(kv[2].id)))
        top_local = [(s, n) for _, s, n in local[:top_k_local]]
        top_global = [(s, n) for _, s, n in global_[:top_k_global]]

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


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _recency_mult(
    node: Any, as_of: datetime | None, boost: float, half_life_days: float
) -> float:
    """1 + boost · 0.5^(age/half_life). age = as_of − node.tx_from (days).
    Recently-changed nodes (small age) get the full boost; old ones decay to 1.
    No boost / no anchor / no stamp → neutral 1.0."""
    if boost <= 0 or as_of is None:
        return 1.0
    tx = getattr(node, "tx_from", None)
    if tx is None:
        return 1.0
    if tx.tzinfo is None:
        tx = tx.replace(tzinfo=timezone.utc)
    age_days = (as_of - tx).total_seconds() / 86400.0
    if age_days <= 0:
        return 1.0 + boost
    return 1.0 + boost * (0.5 ** (age_days / half_life_days))
