"""Similarity-based merge candidates.

Sister agent to `entity_dedup`: where dedup buckets by exact lemma+type,
this one ranks pairs by a soft similarity blend (name + summary +
neighbourhood Jaccard) and surfaces the top-K likeliest merges, even
when the lemmas don't match. Useful for entities the NER labelled
inconsistently across episodes.

Output: Suggestion(action=MERGE, target_node_ids=[a, b], payload={
    survivor_id, absorbed_ids: [other], score, components}). Confidence
mirrors the score so the SuggestionsSidebar sorts the strongest pairs
to the top.
"""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from api.domain.curation import Suggestion, SuggestionAction
from api.domain.graph import Layer, Node
from api.domain.types import Id
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState

from ._helpers import entity_nodes, lemma_key


@agents.register(
    "similarity_merge_candidates",
    summary=(
        "Rank entity pairs by name + summary + neighbourhood similarity "
        "and surface the most likely merges."
    ),
    description=(
        "Soft alternative to entity_dedup. For every pair of entity "
        "nodes that share at least the first letter of their lemma "
        "(O(n) bucket prefilter so the O(n²) scoring stays manageable), "
        "compute score = w_name·SequenceMatcher(name) + w_summary·"
        "SequenceMatcher(summary) + w_neighbors·Jaccard(neighbour ids). "
        "Sort descending, emit the top max_suggestions pairs as MERGE "
        "Suggestions with confidence = score. Survivor is the node with "
        "the longer summary, then the lexicographically smaller id."
    ),
    requires_layers=(Layer.ENTITY,),
    params_schema={
        "max_suggestions": {
            "type": "integer",
            "default": 30,
            "description": "Cap proposals per run.",
        },
        "min_score": {
            "type": "number",
            "default": 0.55,
            "description": "Drop pairs whose blended score is below this.",
        },
        "weight_name": {
            "type": "number",
            "default": 0.5,
            "description": "Weight for name similarity (SequenceMatcher).",
        },
        "weight_summary": {
            "type": "number",
            "default": 0.2,
            "description": "Weight for summary similarity.",
        },
        "weight_neighbors": {
            "type": "number",
            "default": 0.3,
            "description": "Weight for neighbour-set Jaccard.",
        },
        "skip_same_lemma": {
            "type": "boolean",
            "default": True,
            "description": (
                "If True, skip pairs that share an exact lemma — they're "
                "already in entity_dedup's territory."
            ),
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2410.05779v3.pdf",),
)
class SimilarityMergeCandidates:
    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        cap = int(params.get("max_suggestions", 30))
        min_score = float(params.get("min_score", 0.55))
        w_name = float(params.get("weight_name", 0.5))
        w_summary = float(params.get("weight_summary", 0.2))
        w_neighbors = float(params.get("weight_neighbors", 0.3))
        skip_same_lemma = bool(params.get("skip_same_lemma", True))

        nodes = entity_nodes(state.nodes)
        if len(nodes) < 2:
            return []

        # Build neighbour adjacency from the variant's edges.
        adj: dict[Id, set[Id]] = defaultdict(set)
        for e in state.edges:
            adj[e.source_node_id].add(e.target_node_id)
            adj[e.target_node_id].add(e.source_node_id)

        # Prefilter: bucket by first letter of the visible name (NOT the
        # lemma — "Apple Inc" / "Apple Incorporated" must share a bucket
        # even when their lemmas diverge). Cap O(n²) to within-type +
        # within-first-letter, which is small in practice.
        buckets: dict[tuple[str, str], list[Node]] = defaultdict(list)
        for n in nodes:
            stripped = (n.name or "").strip()
            if not stripped:
                continue
            buckets[(n.type, stripped[0].lower())].append(n)

        ranked: list[tuple[float, dict[str, float], Node, Node]] = []
        for bucket in buckets.values():
            for i, a in enumerate(bucket):
                a_lemma = lemma_key(a)
                a_neighbours = adj.get(a.id, set())
                for b in bucket[i + 1 :]:
                    if skip_same_lemma and a_lemma and a_lemma == lemma_key(b):
                        continue
                    name_sim = _ratio(a.name or "", b.name or "")
                    summary_sim = _ratio(a.summary or "", b.summary or "")
                    neigh_sim = _jaccard(a_neighbours, adj.get(b.id, set()))
                    score = (
                        w_name * name_sim
                        + w_summary * summary_sim
                        + w_neighbors * neigh_sim
                    )
                    if score < min_score:
                        continue
                    ranked.append(
                        (
                            score,
                            {
                                "name_similarity": round(name_sim, 3),
                                "summary_similarity": round(summary_sim, 3),
                                "neighbor_jaccard": round(neigh_sim, 3),
                            },
                            a,
                            b,
                        )
                    )

        ranked.sort(key=lambda r: (-r[0], str(r[2].id), str(r[3].id)))

        out: list[Suggestion] = []
        for score, components, a, b in ranked[:cap]:
            survivor, absorbed = _pick_survivor(a, b)
            out.append(
                Suggestion(
                    graph_variant_id=graph_variant_id,
                    agent="similarity_merge_candidates",
                    action=SuggestionAction.MERGE,
                    target_node_ids=[a.id, b.id],
                    payload={
                        "survivor_id": str(survivor.id),
                        "absorbed_ids": [str(absorbed.id)],
                        "score": round(score, 3),
                        "components": components,
                        "reason": (
                            f"name≈{components['name_similarity']}, "
                            f"summary≈{components['summary_similarity']}, "
                            f"neighbours≈{components['neighbor_jaccard']}"
                        ),
                    },
                    confidence=min(0.99, max(0.01, score)),
                    rationale=(
                        f"{a.name!r} ↔ {b.name!r}: blended similarity "
                        f"{score:.2f} (name {components['name_similarity']:.2f}, "
                        f"summary {components['summary_similarity']:.2f}, "
                        f"neighbours {components['neighbor_jaccard']:.2f})."
                    ),
                )
            )
        return out


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _jaccard(a: set[Id], b: set[Id]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _pick_survivor(a: Node, b: Node) -> tuple[Node, Node]:
    """Survivor = longer summary, tie-break by lexicographic id."""

    a_score = (len(a.summary or ""), str(b.id))
    b_score = (len(b.summary or ""), str(a.id))
    return (a, b) if a_score >= b_score else (b, a)
