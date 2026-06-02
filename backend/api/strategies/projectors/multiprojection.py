"""Batagelj multi-projection projector.

Materializes *latent* two-mode projections of the heterogeneous graph as
explicit **higher-order (2nd-order) edges** between same-layer node pairs.

A two-mode (bipartite) incidence — e.g. Entity—[MENTIONED_IN]—Chunk, or
Entity—[MEMBER_OF]—Community — has a one-mode projection N·Nᵀ onto the
target layer: two entities are linked when they share intermediaries
(chunks, communities, …). Raw co-occurrence rewards popular intermediaries
and produces the "megahub" pathology, so following Batagelj & Cerinšek,
*On bibliographic networks* (Scientometrics 2013, arXiv:1301.4655), we
emit the projection under a chosen **normalization**:

* ``raw``      — c_ij = number of shared intermediaries.
* ``newman``   — fractional (Newman 2001 / Batagelj fractional approach):
  each shared intermediary k of degree d_k contributes 1/(d_k−1), so a
  big chunk/community that links *everyone* barely contributes to any
  single pair. This is the default; it is the hub-deflating normalization
  Batagelj recommends for two-mode → one-mode derivation.
* ``cosine``   — Salton: c_ij / sqrt(d_i · d_j).
* ``jaccard``  — c_ij / (d_i + d_j − c_ij).
* ``min``      — Simpson overlap: c_ij / min(d_i, d_j).

Output: only new Edge rows with ``type=DERIVED`` (``attributes.order=2``,
plus the projection path, normalization and raw count). Existing edges are
left untouched; callers can show/hide derived edges by type at render time.
Density is bounded by ``min_weight`` and ``top_k_per_node``.

References:
- Batagelj, Cerinšek. "On bibliographic networks." Scientometrics 96(3),
  2013. arXiv:1301.4655.
- Newman. "Scientific collaboration networks. II." Phys. Rev. E 64, 2001.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge, EdgeType, Layer
from api.domain.types import Id, new_id

from ..registry import projectors
from ..state import GraphBuildState

_NORMALIZATIONS = ("raw", "newman", "cosine", "jaccard", "min")

# Default latent projections to materialize (target layer ← shared neighbor).
_DEFAULT_PROJECTIONS: list[dict[str, str]] = [
    {
        "name": "entity_co_chunk",
        "target_layer": "entity",
        "via": "mentioned_in",
        "neighbor_layer": "chunk",
    },
    {
        "name": "entity_co_community",
        "target_layer": "entity",
        "via": "member_of",
        "neighbor_layer": "community",
    },
]


@projectors.register(
    "multiprojection",
    summary="Materialize latent two-mode projections (Entity co-chunk / co-community …) as normalized higher-order edges (Batagelj).",
    description=(
        "Projects bipartite incidence onto a target layer (N·Nᵀ) and emits "
        "the result as 2nd-order DERIVED edges between node pairs, weighted "
        "by a hub-deflating normalization (newman/fractional by default, "
        "also cosine/jaccard/min/raw). Bounded by min_weight and "
        "top_k_per_node. No existing edge is removed."
    ),
    requires_layers=(),
    produces_layers=(),
    params_schema={
        "normalization": {
            "type": "string",
            "enum": list(_NORMALIZATIONS),
            "default": "newman",
            "description": "Two-mode projection normalization (Batagelj).",
        },
        "projections": {
            "type": "array",
            "default": _DEFAULT_PROJECTIONS,
            "description": "Latent projections to materialize: {name, target_layer, via, neighbor_layer}.",
        },
        "min_weight": {
            "type": "number",
            "default": 0.0,
            "description": "Drop derived edges whose normalized weight is <= this.",
        },
        "top_k_per_node": {
            "type": "integer",
            "default": 8,
            "description": "Keep at most this many strongest derived edges incident to each node (0 = unbounded).",
        },
        "max_edges": {
            "type": "integer",
            "default": 5000,
            "description": "Global safety cap on derived edges per projection.",
        },
    },
    cost_hint="cheap",
    references=(
        "Batagelj, Cerinšek. 'On bibliographic networks.' Scientometrics 96(3) 2013. arXiv:1301.4655.",
        "Newman. 'Scientific collaboration networks. II.' Phys. Rev. E 64 2001.",
    ),
)
class MultiProjection:
    descriptor: Any  # set by the decorator

    async def project(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState:
        normalization = str(params.get("normalization", "newman"))
        if normalization not in _NORMALIZATIONS:
            normalization = "newman"
        projections = params.get("projections") or _DEFAULT_PROJECTIONS
        min_weight = float(params.get("min_weight", 0.0))
        top_k = int(params.get("top_k_per_node", 8))
        max_edges = int(params.get("max_edges", 5000))

        variant_id = state.nodes[0].graph_variant_id if state.nodes else None
        if variant_id is None:
            return state

        layer_by_id: dict[Id, Layer] = {n.id: n.layer for n in state.nodes}

        new_edges: list[Edge] = []
        summary: dict[str, dict[str, int]] = {}

        for spec in projections:
            try:
                target_layer = Layer(spec["target_layer"])
                via = EdgeType(spec["via"])
                neighbor_layer = Layer(spec["neighbor_layer"])
            except (KeyError, ValueError):
                continue
            name = str(spec.get("name", f"{target_layer.value}_via_{neighbor_layer.value}"))

            pairs = _project(
                state=state,
                layer_by_id=layer_by_id,
                target_layer=target_layer,
                via=via,
                neighbor_layer=neighbor_layer,
                normalization=normalization,
            )
            if not pairs:
                continue

            kept = _sparsify(pairs, min_weight=min_weight, top_k=top_k, max_edges=max_edges)
            for (i, j), info in kept.items():
                new_edges.append(
                    Edge(
                        id=new_id(),
                        graph_variant_id=variant_id,
                        type=EdgeType.DERIVED,
                        source_node_id=i,
                        target_node_id=j,
                        weight=info["weight"],
                        relation=name,
                        attributes={
                            "order": 2,
                            "projection": name,
                            "via": via.value,
                            "neighbor_layer": neighbor_layer.value,
                            "normalization": normalization,
                            "raw_count": info["raw"],
                        },
                    )
                )
            summary[name] = {"candidates": len(pairs), "kept": len(kept)}

        if not new_edges:
            return state

        journal = JournalEntry(
            id=new_id(),
            graph_variant_id=variant_id,
            op=JournalOp.SET_SUMMARY,  # additive marker (see intra_layer_backbone)
            payload={
                "projector": "multiprojection",
                "summary": "Batagelj two-mode projections as higher-order edges",
                "normalization": normalization,
                "per_projection": summary,
            },
            actor="system:projector",
        )
        return GraphBuildState(
            nodes=list(state.nodes),
            edges=list(state.edges) + new_edges,
            journal=list(state.journal) + [journal],
        )


# ---- projection core ---------------------------------------------------


def _project(
    *,
    state: GraphBuildState,
    layer_by_id: dict[Id, Layer],
    target_layer: Layer,
    via: EdgeType,
    neighbor_layer: Layer,
    normalization: str,
) -> dict[tuple[Id, Id], dict[str, Any]]:
    """One-mode projection of the `via` bipartite incidence onto
    `target_layer`, normalized per Batagelj. Returns
    {(i, j): {"weight": float, "raw": int}} over unordered pairs."""

    # bipartite incidence from edges of `via_type` (either orientation)
    neighbor_targets: dict[Id, set[Id]] = defaultdict(set)
    target_neighbors: dict[Id, set[Id]] = defaultdict(set)
    for e in state.edges:
        if e.type != via:
            continue
        s, t = e.source_node_id, e.target_node_id
        if layer_by_id.get(s) == target_layer and layer_by_id.get(t) == neighbor_layer:
            tgt, nb = s, t
        elif layer_by_id.get(t) == target_layer and layer_by_id.get(s) == neighbor_layer:
            tgt, nb = t, s
        else:
            continue
        neighbor_targets[nb].add(tgt)
        target_neighbors[tgt].add(nb)

    if not neighbor_targets:
        return {}

    raw: dict[tuple[Id, Id], int] = defaultdict(int)
    newman: dict[tuple[Id, Id], float] = defaultdict(float)
    for nb, targets in neighbor_targets.items():
        deg = len(targets)
        if deg < 2:
            continue
        frac = 1.0 / (deg - 1)  # Newman / Batagelj fractional contribution
        ordered = sorted(targets, key=str)
        for a in range(len(ordered)):
            for b in range(a + 1, len(ordered)):
                key = (ordered[a], ordered[b])
                raw[key] += 1
                newman[key] += frac

    out: dict[tuple[Id, Id], dict[str, Any]] = {}
    for (i, j), c in raw.items():
        di, dj = len(target_neighbors[i]), len(target_neighbors[j])
        if normalization == "raw":
            w = float(c)
        elif normalization == "newman":
            w = newman[(i, j)]
        elif normalization == "cosine":
            w = c / math.sqrt(di * dj) if di > 0 and dj > 0 else 0.0
        elif normalization == "jaccard":
            denom = di + dj - c
            w = c / denom if denom > 0 else 0.0
        elif normalization == "min":
            m = min(di, dj)
            w = c / m if m > 0 else 0.0
        else:
            w = float(c)
        out[(i, j)] = {"weight": w, "raw": c}
    return out


def _sparsify(
    pairs: dict[tuple[Id, Id], dict[str, Any]],
    *,
    min_weight: float,
    top_k: int,
    max_edges: int,
) -> dict[tuple[Id, Id], dict[str, Any]]:
    """Drop pairs below `min_weight`; optionally keep only each node's
    `top_k` strongest incident edges (union — an edge survives if it is in
    the top-k of *either* endpoint); finally cap the total at `max_edges`."""

    cand = {p: info for p, info in pairs.items() if info["weight"] > min_weight}
    if not cand:
        return {}

    if top_k and top_k > 0:
        by_node: dict[Id, list[tuple[tuple[Id, Id], float]]] = defaultdict(list)
        for pair, info in cand.items():
            by_node[pair[0]].append((pair, info["weight"]))
            by_node[pair[1]].append((pair, info["weight"]))
        survivors: set[tuple[Id, Id]] = set()
        for edges in by_node.values():
            edges.sort(key=lambda t: t[1], reverse=True)
            for pair, _ in edges[:top_k]:
                survivors.add(pair)
        cand = {p: info for p, info in cand.items() if p in survivors}

    if max_edges and len(cand) > max_edges:
        ranked = sorted(cand.items(), key=lambda kv: kv[1]["weight"], reverse=True)
        cand = dict(ranked[:max_edges])
    return cand
