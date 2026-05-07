from __future__ import annotations

from collections import defaultdict
from typing import Any

from api.domain.curation import Suggestion, SuggestionAction
from api.domain.graph import Layer
from api.domain.types import Id
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState

from ._helpers import entity_nodes, lemma_key


@agents.register(
    "entity_dedup",
    summary="Propose merges for entity-layer nodes that share a lemma + type.",
    description=(
        "Russian-first heuristic dedup. Buckets entity-layer nodes by "
        "(type, lemma) — preferring the lemma stored in attributes by "
        "NerExtractionBuilder, falling back to the lowercased first "
        "token. For every bucket with ≥2 nodes, proposes a MERGE "
        "Suggestion with a survivor picked deterministically (longest "
        "summary, then id-stable)."
    ),
    requires_layers=(Layer.ENTITY,),
    params_schema={
        "min_bucket_size": {
            "type": "integer",
            "default": 2,
            "description": "Skip buckets smaller than this.",
        },
        "max_suggestions": {
            "type": "integer",
            "default": 100,
            "description": "Cap proposals per run; the rest land on the next run.",
        },
    },
    cost_hint="cheap",
    references=("docs/raw/2410.05779v3.pdf",),
)
class EntityDeduplicator:
    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        min_bucket = int(params.get("min_bucket_size", 2))
        cap = int(params.get("max_suggestions", 100))

        buckets: dict[tuple[str, str], list] = defaultdict(list)
        for node in entity_nodes(state.nodes):
            key = lemma_key(node)
            if not key:
                continue
            buckets[(node.type, key)].append(node)

        suggestions: list[Suggestion] = []
        for (type_, lemma), bucket in sorted(
            buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])
        ):
            if len(bucket) < min_bucket:
                continue
            bucket.sort(key=lambda n: (-len(n.summary or ""), str(n.id)))
            survivor = bucket[0]
            absorbed = bucket[1:]
            suggestions.append(
                Suggestion(
                    graph_variant_id=graph_variant_id,
                    agent="entity_dedup",
                    action=SuggestionAction.MERGE,
                    target_node_ids=[n.id for n in bucket],
                    payload={
                        "survivor_id": str(survivor.id),
                        "absorbed_ids": [str(n.id) for n in absorbed],
                        "reason": f"shared lemma '{lemma}' under type {type_}",
                    },
                    confidence=_confidence(bucket),
                    rationale=(
                        f"{len(bucket)} entity-layer nodes share lemma '{lemma}' "
                        f"and type '{type_}'. Proposed survivor: {survivor.name!r}."
                    ),
                )
            )
            if len(suggestions) >= cap:
                break
        return suggestions


def _confidence(bucket: list) -> float:
    """Deterministic confidence: 0.95 for bucket of 2 (high signal),
    declining slowly for larger buckets where one of the matches might
    be a false positive across morphologically distinct mentions.
    """

    n = len(bucket)
    if n <= 2:
        return 0.95
    return max(0.6, 1.0 - 0.05 * (n - 2))
