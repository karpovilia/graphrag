"""Read-only analytical routes over a built graph variant.

GET /api/graphs/{variant_id}/projection-importance — rank the latent
two-mode projections (DERIVED edges from the multiprojection projector)
by non-redundant structure (structural reducibility + overlap).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.analysis import ProjectionImportanceResult, compute_projection_importance
from api.domain.graph import EdgeType, Layer
from api.domain.types import DomainModel, Id
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository
from api.strategies.projectors.multiprojection import _project, _sparsify

router = APIRouter(prefix="/api", tags=["analysis"])


class ProjectionOption(DomainModel):
    target_layer: str
    via: str
    neighbor_layer: str
    label: str
    edge_count: int


class ProjectionEdge(DomainModel):
    source_node_id: Id
    target_node_id: Id
    weight: float
    raw_count: int


class ProjectionResult(DomainModel):
    target_layer: str
    via: str
    neighbor_layer: str
    normalization: str
    edges: list[ProjectionEdge]


def _discover_bridges(state) -> list[ProjectionOption]:
    """Bipartite relations present in the graph: edge types connecting two
    DISTINCT layers. Each becomes two projection options (project either
    endpoint layer onto itself via the shared one)."""
    layer_by_id = {n.id: n.layer for n in state.nodes}
    # (via, frozenset{la, lb}) -> count
    bridges: dict[tuple[str, frozenset], int] = {}
    for e in state.edges:
        la = layer_by_id.get(e.source_node_id)
        lb = layer_by_id.get(e.target_node_id)
        if la is None or lb is None or la == lb:
            continue
        key = (e.type.value, frozenset({la.value, lb.value}))
        bridges[key] = bridges.get(key, 0) + 1

    out: list[ProjectionOption] = []
    for (via, pair), count in sorted(bridges.items(), key=lambda kv: -kv[1]):
        layers = sorted(pair)
        for target, neighbor in ((layers[0], layers[1]), (layers[1], layers[0])):
            out.append(
                ProjectionOption(
                    target_layer=target,
                    via=via,
                    neighbor_layer=neighbor,
                    label=f"{target.title()} ↔ {target.title()} (via {neighbor})",
                    edge_count=count,
                )
            )
    return out


@router.get(
    "/graphs/{variant_id}/projection-importance",
    response_model=ProjectionImportanceResult,
)
async def projection_importance(
    variant_id: Id,
    include_direct: bool = True,
    repo: RepositoryProtocol = Depends(get_repository),
) -> ProjectionImportanceResult:
    try:
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return compute_projection_importance(
        state, variant_id, include_direct=include_direct
    )


@router.get(
    "/graphs/{variant_id}/projection/available",
    response_model=list[ProjectionOption],
)
async def projection_available(
    variant_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[ProjectionOption]:
    """Which layer-pair projections this graph supports (discovered from the
    bipartite edge types present) — populates the selector."""
    try:
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _discover_bridges(state)


@router.get(
    "/graphs/{variant_id}/projection",
    response_model=ProjectionResult,
)
async def graph_projection(
    variant_id: Id,
    target_layer: str,
    via: str,
    neighbor_layer: str,
    normalization: str = "newman",
    top_k: int = 8,
    min_weight: float = 0.0,
    max_edges: int = 2000,
    repo: RepositoryProtocol = Depends(get_repository),
) -> ProjectionResult:
    """Compute a two-mode projection on-the-fly: project `target_layer` nodes
    onto each other through their shared `neighbor_layer` neighbours linked by
    `via`, under `normalization` (Batagelj). Returns the derived edges without
    persisting anything — the viewer overlays them."""
    try:
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        tl, v, nl = Layer(target_layer), EdgeType(via), Layer(neighbor_layer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bad layer/edge: {e}") from e

    layer_by_id = {n.id: n.layer for n in state.nodes}
    pairs = _project(
        state=state,
        layer_by_id=layer_by_id,
        target_layer=tl,
        via=v,
        neighbor_layer=nl,
        normalization=normalization,
    )
    kept = _sparsify(pairs, min_weight=min_weight, top_k=top_k, max_edges=max_edges)
    edges = [
        ProjectionEdge(
            source_node_id=i,
            target_node_id=j,
            weight=info["weight"],
            raw_count=int(info["raw"]),
        )
        for (i, j), info in kept.items()
    ]
    return ProjectionResult(
        target_layer=target_layer,
        via=via,
        neighbor_layer=neighbor_layer,
        normalization=normalization,
        edges=edges,
    )
