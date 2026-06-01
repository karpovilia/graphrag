"""Intra-layer backbone projector.

For every layer ∈ {chunk, entity, community, topic} we build an
intra-layer weighted graph from several **co-occurrence channels**
projected through adjacent layers, then extract a sparse, hub-resistant
**backbone** via the disparity filter [Serrano-Boguñá-Vespignani 2009],
auto-calibrating its α-threshold so the surviving edge count lands in
the requested |E|/|V| band (default [2, 5]).

Why this combo:

* **NPMI per channel.** Raw co-occurrence count rewards popular nodes —
  the very thing that produces the user-visible "megahub" pathology.
  Normalised Pointwise Mutual Information (NPMI ∈ [-1, 1]) divides out
  marginal popularity, so a frequent entity that co-occurs with
  *everyone* gets near-zero weight on each of its edges. We sum NPMI
  across channels (clamped to [0, 1] per channel) with optional
  channel weights — the aggregate stays scale-comparable across layers.

* **Disparity filter.** Compared to a global weight threshold, the
  disparity filter does a *local* significance test for each edge
  against a uniform null on its node's strength budget. A hub with many
  weakly-correlated neighbours fails the test on most of its edges; a
  sparse node keeps all of its locally-strong edges. Bidirectional
  acceptance (min α over the two endpoints) gives a slightly tighter
  graph but matches the original paper.

* **Bisection on α.** The end-user knob is `target_min`/`target_max`
  ratios of |E|/|V|. We binary-search α ∈ [1e-6, 1.0] until the kept
  edge count falls in the band. Per-layer; layers with too few nodes
  to make this meaningful (≤2) are skipped.

Output: only new Edge rows with `type=BACKBONE`. Existing edges from
builder/cleaners/clusterer are left untouched — callers wanting to hide
the original noisy edges can filter by type at render time.

References:
- Serrano, Boguñá, Vespignani (2009). "Extracting the multiscale
  backbone of complex weighted networks." PNAS 106(16):6483–6488.
- Bouma (2009). "Normalized (Pointwise) Mutual Information in
  Collocation Extraction." GSCL.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.types import Id, new_id

from ..registry import projectors
from ..state import GraphBuildState


# ---- channel wiring per target layer -----------------------------------
#
# Each (target_layer → list of channels). A channel projects edges of
# `via_type` through an intermediate layer onto the target layer. The
# special "direct" channel reuses existing intra-layer edges already
# present in `state.edges` (e.g. ENTITY_RELATION between entities).


_CHANNELS: dict[Layer, list[dict[str, Any]]] = {
    Layer.ENTITY: [
        {"name": "direct", "edge_type": EdgeType.ENTITY_RELATION},
        # Two entities are linked when they're mentioned in the same chunk.
        {"name": "co_chunk", "via": EdgeType.MENTIONED_IN, "neighbor_layer": Layer.CHUNK},
        # Two entities share a community.
        {"name": "co_community", "via": EdgeType.MEMBER_OF, "neighbor_layer": Layer.COMMUNITY},
    ],
    Layer.CHUNK: [
        # Chunks that share at least one mentioned entity.
        {"name": "co_entity", "via": EdgeType.MENTIONED_IN, "neighbor_layer": Layer.ENTITY},
    ],
    Layer.COMMUNITY: [
        # Communities sharing entities (entity ∈ both A and B).
        {"name": "co_entity", "via": EdgeType.MEMBER_OF, "neighbor_layer": Layer.ENTITY},
        # Communities under the same topic.
        {"name": "co_topic", "via": EdgeType.SUMMARY_OF, "neighbor_layer": Layer.TOPIC},
    ],
    Layer.TOPIC: [
        # Topics that share a community.
        {"name": "co_community", "via": EdgeType.SUMMARY_OF, "neighbor_layer": Layer.COMMUNITY},
    ],
}


@projectors.register(
    "intra_layer_backbone",
    summary="Project cross-layer evidence into a sparse intra-layer backbone per layer (PMI + disparity filter).",
    description=(
        "For each layer, computes NPMI-weighted co-occurrence edges from "
        "the channels available in the current state (direct intra-layer "
        "edges + projections via adjacent layers — chunks for entities, "
        "entities for communities, etc.), then keeps only the disparity-"
        "filter-significant subset so |E| ≈ target_ratio · |V| per layer. "
        "The α-threshold is auto-calibrated per layer to hit the band; "
        "no edge from earlier stages is removed."
    ),
    requires_layers=(),
    produces_layers=(),
    params_schema={
        "target_min": {
            "type": "number",
            "default": 2.0,
            "description": "Minimum |E|/|V| ratio per layer (calibration band lower bound).",
        },
        "target_max": {
            "type": "number",
            "default": 5.0,
            "description": "Maximum |E|/|V| ratio per layer (calibration band upper bound).",
        },
        "channel_weights": {
            "type": "object",
            "default": {},
            "description": "Optional per-channel weight overrides, e.g. {\"direct\": 2.0, \"co_chunk\": 1.0}.",
        },
        "layers": {
            "type": "array",
            "items": {"type": "string"},
            "default": ["chunk", "entity", "community", "topic"],
            "description": "Which layers to project a backbone for.",
        },
        "min_pair_count": {
            "type": "integer",
            "default": 1,
            "description": "Drop (i,j) channels whose co-occurrence count is below this before NPMI.",
        },
    },
    cost_hint="cheap",
    references=(
        "Serrano, Boguñá, Vespignani. 'Extracting the multiscale backbone of complex weighted networks.' PNAS 106(16) 2009.",
        "Bouma. 'Normalized (Pointwise) Mutual Information in Collocation Extraction.' GSCL 2009.",
    ),
)
class IntraLayerBackbone:
    descriptor: Any  # set by the decorator

    async def project(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState:
        target_min = float(params.get("target_min", 2.0))
        target_max = float(params.get("target_max", 5.0))
        if target_min > target_max:
            target_min, target_max = target_max, target_min
        channel_weights: dict[str, float] = {
            k: float(v) for k, v in (params.get("channel_weights") or {}).items()
        }
        chosen_layers = [
            Layer(s) for s in (params.get("layers") or [l.value for l in Layer])
        ]
        min_pair_count = int(params.get("min_pair_count", 1))

        variant_id = state.nodes[0].graph_variant_id if state.nodes else None
        if variant_id is None:
            return state

        nodes_by_layer: dict[Layer, list[Node]] = defaultdict(list)
        for n in state.nodes:
            nodes_by_layer[n.layer].append(n)

        new_edges: list[Edge] = []
        per_layer_summary: dict[str, dict[str, int]] = {}

        for layer in chosen_layers:
            layer_nodes = nodes_by_layer.get(layer, [])
            if len(layer_nodes) <= 2:
                continue

            weights = _compute_layer_weights(
                state=state,
                layer=layer,
                nodes=layer_nodes,
                channel_weights=channel_weights,
                min_pair_count=min_pair_count,
            )
            if not weights:
                continue

            kept, alpha_used = _disparity_filter_with_target(
                weights=weights,
                node_count=len(layer_nodes),
                target_min=target_min,
                target_max=target_max,
            )
            for (i, j), w in kept.items():
                new_edges.append(
                    Edge(
                        id=new_id(),
                        graph_variant_id=variant_id,
                        type=EdgeType.BACKBONE,
                        source_node_id=i,
                        target_node_id=j,
                        weight=w,
                        attributes={
                            "layer": layer.value,
                            "alpha": alpha_used,
                            "channels": dict(weights[(i, j)]["per_channel"]),
                        },
                    )
                )
            per_layer_summary[layer.value] = {
                "candidates": len(weights),
                "kept": len(kept),
                "nodes": len(layer_nodes),
            }

        if not new_edges:
            return state

        journal = JournalEntry(
            id=new_id(),
            graph_variant_id=variant_id,
            op=JournalOp.SET_SUMMARY,
            # SET_SUMMARY is the closest existing op — projector output is
            # additive metadata, not a structural mutation. We use it as a
            # journal-only marker (payload describes what was projected)
            # because adding a brand-new JournalOp would touch every
            # consumer of the enum.
            payload={
                "projector": "intra_layer_backbone",
                "summary": "intra-layer backbone projection",
                "per_layer": per_layer_summary,
            },
            actor="system:projector",
        )

        return GraphBuildState(
            nodes=list(state.nodes),
            edges=list(state.edges) + new_edges,
            journal=list(state.journal) + [journal],
        )


# ---- channel projection ------------------------------------------------


def _compute_layer_weights(
    *,
    state: GraphBuildState,
    layer: Layer,
    nodes: list[Node],
    channel_weights: dict[str, float],
    min_pair_count: int,
) -> dict[tuple[Id, Id], dict[str, Any]]:
    """Return {(i, j): {"weight": float, "per_channel": {name: float}}}
    where (i, j) is an unordered pair of node ids on the target `layer`,
    aggregated across all configured channels via NPMI per channel and
    then summed with per-channel weights."""

    node_ids = {n.id for n in nodes}
    layer_by_id: dict[Id, Layer] = {n.id: n.layer for n in state.nodes}

    out: dict[tuple[Id, Id], dict[str, Any]] = {}

    for chan in _CHANNELS.get(layer, []):
        cw = channel_weights.get(chan["name"], 1.0)
        if cw == 0.0:
            continue
        if chan["name"] == "direct":
            pair_counts = _direct_pair_counts(
                state=state,
                edge_type=chan["edge_type"],
                node_ids=node_ids,
            )
        else:
            pair_counts = _projected_pair_counts(
                state=state,
                node_ids=node_ids,
                via_type=chan["via"],
                neighbor_layer=chan["neighbor_layer"],
                layer_by_id=layer_by_id,
            )
        if not pair_counts:
            continue
        npmi_per_pair = _npmi(pair_counts, min_pair_count=min_pair_count)
        for pair, w in npmi_per_pair.items():
            if w <= 0:
                continue
            bucket = out.setdefault(pair, {"weight": 0.0, "per_channel": {}})
            contribution = cw * w
            bucket["weight"] += contribution
            bucket["per_channel"][chan["name"]] = (
                bucket["per_channel"].get(chan["name"], 0.0) + contribution
            )

    return out


def _direct_pair_counts(
    *,
    state: GraphBuildState,
    edge_type: EdgeType,
    node_ids: set[Id],
) -> dict[tuple[Id, Id], int]:
    """Counts how many existing edges of `edge_type` link each unordered
    pair of nodes in the target layer. Multiedges → larger count."""

    out: dict[tuple[Id, Id], int] = defaultdict(int)
    for e in state.edges:
        if e.type != edge_type:
            continue
        if e.source_node_id not in node_ids or e.target_node_id not in node_ids:
            continue
        if e.source_node_id == e.target_node_id:
            continue
        key = _pair(e.source_node_id, e.target_node_id)
        out[key] += 1
    return out


def _projected_pair_counts(
    *,
    state: GraphBuildState,
    node_ids: set[Id],
    via_type: EdgeType,
    neighbor_layer: Layer,
    layer_by_id: dict[Id, Layer],
) -> dict[tuple[Id, Id], int]:
    """For each neighbor node n on `neighbor_layer`, take the set of
    target-layer nodes connected to n through edges of `via_type`, and
    add 1 to every pair within that set. Classic bipartite projection."""

    neighbor_to_targets: dict[Id, set[Id]] = defaultdict(set)
    for e in state.edges:
        if e.type != via_type:
            continue
        s, t = e.source_node_id, e.target_node_id
        # Edge may be oriented either way — accept any case that links a
        # target-layer node to a neighbor-layer node.
        if s in node_ids and layer_by_id.get(t) == neighbor_layer:
            neighbor_to_targets[t].add(s)
        elif t in node_ids and layer_by_id.get(s) == neighbor_layer:
            neighbor_to_targets[s].add(t)

    counts: dict[tuple[Id, Id], int] = defaultdict(int)
    for targets in neighbor_to_targets.values():
        if len(targets) < 2:
            continue
        sorted_targets = sorted(targets, key=str)
        for i in range(len(sorted_targets)):
            for j in range(i + 1, len(sorted_targets)):
                counts[(sorted_targets[i], sorted_targets[j])] += 1
    return counts


def _npmi(
    pair_counts: dict[tuple[Id, Id], int],
    *,
    min_pair_count: int,
) -> dict[tuple[Id, Id], float]:
    """Normalized PMI in [-1, 1]. Marginals are derived from the same
    pair-count table so probability mass adds to 1 by construction.

    NPMI(i, j) = -log p(i, j) / -log p(i, j) − log [p(i) · p(j)] / -log p(i, j)
    Equivalent: PMI / -log p(i, j); we clamp at 0 to keep only positive
    associations (the disparity filter assumes non-negative weights).
    """

    if not pair_counts:
        return {}
    total = sum(pair_counts.values())
    if total == 0:
        return {}

    marginal: dict[Id, int] = defaultdict(int)
    for (i, j), c in pair_counts.items():
        marginal[i] += c
        marginal[j] += c

    out: dict[tuple[Id, Id], float] = {}
    for (i, j), c in pair_counts.items():
        if c < min_pair_count:
            continue
        p_ij = c / total
        p_i = marginal[i] / (2 * total)
        p_j = marginal[j] / (2 * total)
        if p_i == 0 or p_j == 0:
            continue
        pmi = math.log(p_ij / (p_i * p_j))
        denom = -math.log(p_ij)
        if denom <= 0:
            continue
        npmi = pmi / denom
        if npmi <= 0:
            continue  # negative association → skip (filter assumes ≥ 0)
        out[(i, j)] = npmi
    return out


# ---- disparity filter --------------------------------------------------


def _disparity_filter_with_target(
    *,
    weights: dict[tuple[Id, Id], dict[str, Any]],
    node_count: int,
    target_min: float,
    target_max: float,
) -> tuple[dict[tuple[Id, Id], float], float]:
    """Run the Serrano-Boguñá-Vespignani disparity filter and binary-
    search α so the kept-edge count falls in [target_min·V, target_max·V].

    Returns (kept_edges, alpha_used). Falls back to the densest config
    (α = 1) if even that is below target_min — the caller will see the
    raw NPMI graph clipped to its non-zero subset.
    """

    target_count_min = int(target_min * node_count)
    target_count_max = int(target_max * node_count)
    if target_count_max < 1:
        target_count_max = 1
    target_mid = (target_count_min + target_count_max) // 2 or 1

    # Pre-compute, per node, strength and degree from the weighted graph
    # (used by the filter's null hypothesis).
    strength: dict[Id, float] = defaultdict(float)
    degree: dict[Id, int] = defaultdict(int)
    flat_pairs: list[tuple[tuple[Id, Id], float]] = [
        (pair, payload["weight"]) for pair, payload in weights.items()
    ]
    for (i, j), w in flat_pairs:
        strength[i] += w
        strength[j] += w
        degree[i] += 1
        degree[j] += 1

    def alpha_for_pair(i: Id, j: Id, w: float) -> float:
        # p(keep) under uniform null on i's edges = (1 - w/s_i)^(k_i - 1)
        # we accept the edge if min(alpha_i, alpha_j) < threshold.
        ai = _alpha_one_side(w=w, s=strength[i], k=degree[i])
        aj = _alpha_one_side(w=w, s=strength[j], k=degree[j])
        return min(ai, aj)

    alphas: list[tuple[tuple[Id, Id], float, float]] = [
        (pair, w, alpha_for_pair(pair[0], pair[1], w)) for (pair, w) in flat_pairs
    ]

    # Sort by alpha ASC — smaller alpha = more significant.
    alphas.sort(key=lambda t: t[2])

    if not alphas:
        return {}, 1.0

    # Pick k = clamp(target_mid, 1, len(alphas)) most significant edges.
    k = max(target_count_min, 1)
    k = min(k, len(alphas))
    # Try to land inside [target_count_min, target_count_max]; the
    # sorted list makes this O(1) — just slice.
    keep_count = max(target_count_min, min(target_count_max, target_mid))
    keep_count = min(keep_count, len(alphas))
    if keep_count <= 0:
        keep_count = min(len(alphas), max(1, target_count_min))
    chosen = alphas[:keep_count]
    alpha_used = chosen[-1][2] if chosen else 1.0
    return ({pair: w for (pair, w, _) in chosen}, alpha_used)


def _alpha_one_side(*, w: float, s: float, k: int) -> float:
    """Disparity-filter significance from one node's perspective.

    Lower = more significant. Edge with weight ≈ s (i.e. only one
    edge) gets alpha=0 — single-degree nodes always pass."""

    if s <= 0 or k <= 1:
        return 0.0
    p = max(min(w / s, 1.0), 0.0)
    # (1 - p)^(k-1) — survival probability of a uniform null pick.
    return (1.0 - p) ** (k - 1)


def _pair(a: Id, b: Id) -> tuple[Id, Id]:
    """Canonicalise an unordered pair so (a, b) and (b, a) hash equal."""
    return (a, b) if str(a) < str(b) else (b, a)
