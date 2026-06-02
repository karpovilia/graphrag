"""Read-only analytical routes over a built graph variant.

GET /api/graphs/{variant_id}/projection-importance — rank the latent
two-mode projections (DERIVED edges from the multiprojection projector)
by non-redundant structure (structural reducibility + overlap).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.analysis import ProjectionImportanceResult, compute_projection_importance
from api.domain.types import Id
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["analysis"])


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
