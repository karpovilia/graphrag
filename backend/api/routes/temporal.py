"""Bi-temporal routes (R2 §2): timeline scrubber, materialize, diff, revert.

  GET  /api/graphs/{variant_id}/timeline               — scrubber axis
  GET  /api/graphs/{variant_id}/at?t=&axis=            — facts live at t
  GET  /api/graphs/{variant_id}/diff?t_a=&t_b=&axis=   — §0 grammar diff
  POST /api/graphs/{variant_id}/invalidations/{edge_id}/revert — un-kill edge

All datetimes ISO-8601 UTC. axis ∈ {tx, valid}. Error contract: 404
unknown variant, 422 bad axis, 400 t_a>t_b.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from api.curation.ops import EditEdgePayload
from api.domain.curation import JournalEntry, JournalOp
from api.domain.temporal import IngestionEvent, TemporalDiff
from api.domain.types import DomainModel, Id
from api.repository import (
    ConcurrentEditError,
    NotFoundError,
    RepositoryError,
    RepositoryProtocol,
)
from api.repository.protocol import JournalAppendResult
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["temporal"])

_VALID_AXES = ("tx", "valid")


def _check_axis(axis: str) -> Literal["tx", "valid"]:
    if axis not in _VALID_AXES:
        raise HTTPException(
            status_code=422,
            detail=f"axis must be one of {_VALID_AXES}, got {axis!r}",
        )
    return axis  # type: ignore[return-value]


async def _require_variant(repo: RepositoryProtocol, variant_id: Id):
    try:
        return await repo.get_variant(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/graphs/{variant_id}/timeline", response_model=list[IngestionEvent])
async def get_timeline(
    variant_id: Id,
    axis: str = "tx",
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[IngestionEvent]:
    """The scrubber axis (§2.1). axis=tx sorts by ingested_at, axis=valid
    by event_time; both ascending."""

    axis = _check_axis(axis)
    variant = await _require_variant(repo, variant_id)
    events = await repo.list_ingestion_events(
        corpus_id=variant.corpus_id, variant_id=variant_id
    )
    key = (lambda e: e.ingested_at) if axis == "tx" else (lambda e: e.event_time)
    return sorted(events, key=key)


class MaterializedAt(DomainModel):
    variant_id: Id
    axis: Literal["tx", "valid"]
    t: datetime
    node_ids: list[Id] = Field(default_factory=list)
    edge_ids: list[Id] = Field(default_factory=list)


@router.get("/graphs/{variant_id}/at", response_model=MaterializedAt)
async def materialize_at_route(
    variant_id: Id,
    t: datetime = Query(...),
    axis: str = "tx",
    repo: RepositoryProtocol = Depends(get_repository),
) -> MaterializedAt:
    """The set of facts live at instant `t` under `axis` (§2.1 scrub)."""

    axis = _check_axis(axis)
    await _require_variant(repo, variant_id)
    try:
        state = await repo.materialize_state_at(variant_id, t, axis)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return MaterializedAt(
        variant_id=variant_id,
        axis=axis,
        t=t,
        node_ids=[n.id for n in state.nodes],
        edge_ids=[e.id for e in state.edges],
    )


@router.get("/graphs/{variant_id}/diff", response_model=TemporalDiff)
async def temporal_diff_route(
    variant_id: Id,
    t_a: datetime = Query(...),
    t_b: datetime = Query(...),
    axis: str = "tx",
    repo: RepositoryProtocol = Depends(get_repository),
) -> TemporalDiff:
    """§0 grammar diff between two materialized states."""

    axis = _check_axis(axis)
    if t_a > t_b:
        raise HTTPException(status_code=400, detail="t_a must be <= t_b")
    await _require_variant(repo, variant_id)
    try:
        return await repo.temporal_diff(variant_id, t_a, t_b, axis)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class RevertRequest(DomainModel):
    expected_version: int = Field(ge=0)
    actor: str = Field(min_length=1)


@router.post(
    "/graphs/{variant_id}/invalidations/{edge_id}/revert",
    response_model=JournalAppendResult,
)
async def revert_invalidation(
    variant_id: Id,
    edge_id: Id,
    body: RevertRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> JournalAppendResult:
    """Re-add an invalidated edge with its invalidation cleared (§2.4).

    Recorded as a normal journal entry (audit-preserving): an EDIT_EDGE
    op that nulls `invalidation` and `tx_to` so the edge is live again.
    """

    await _require_variant(repo, variant_id)
    try:
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    edge = next((e for e in state.edges if e.id == edge_id), None)
    if edge is None:
        raise HTTPException(
            status_code=404, detail=f"edge {edge_id} not found in variant {variant_id}"
        )
    if edge.invalidation is None and edge.tx_to is None:
        raise HTTPException(
            status_code=400, detail=f"edge {edge_id} was not invalidated"
        )

    entry = JournalEntry(
        graph_variant_id=variant_id,
        op=JournalOp.EDIT_EDGE,
        payload=EditEdgePayload(
            edge_id=edge_id,
            updates={"invalidation": None, "tx_to": None},
        ).model_dump(mode="json"),
        actor=body.actor,
    )
    try:
        return await repo.append_journal(
            variant_id,
            entry,
            expected_version=body.expected_version,
            actor=body.actor,
        )
    except ConcurrentEditError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "expected": e.expected, "actual": e.actual},
        ) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
