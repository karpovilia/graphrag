"""POST /api/reason — single-graph or MoE inference.

Phase 4.4. The single-mode shortcut is just MoE with one variant and a
no-op aggregator (`evidence_union` over a single expert) — the route
handler builds that wrapper rather than duplicating reasoner-call logic.

Two flavors:
  POST /api/reason         — synchronous, one JSON response
  POST /api/reason/stream  — SSE: per-expert events as they finish, then
                             the aggregated answer, then 'done'.
"""

from __future__ import annotations

import json
from typing import Literal

import api.strategies.aggregators  # noqa: F401  — trigger @register
import api.strategies.reasoners  # noqa: F401
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import Field

from api.domain.types import DomainModel, Id
from api.llm import CompletionClient
from api.moe import MoEError, MoEResult, run_moe, stream_moe
from api.repository import RepositoryGraphLoader, RepositoryProtocol
from api.routes.graphs import _maybe_llm
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["reason"])


class ReasonRequest(DomainModel):
    mode: Literal["single", "moe"] = "single"
    query: str = Field(min_length=1)
    variant_ids: list[Id] = Field(min_length=1)
    reasoner: str = "keyword_search"
    reasoner_params: dict = Field(default_factory=dict)
    aggregator: str = "evidence_union"
    """Ignored in single mode (single just unwraps the lone expert),
    required in MoE mode."""

    aggregator_params: dict = Field(default_factory=dict)


def _validate_mode(req: ReasonRequest) -> None:
    if req.mode == "single" and len(req.variant_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail=f"single mode requires exactly one variant_id, got {len(req.variant_ids)}",
        )
    if req.mode == "moe" and len(req.variant_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="moe mode requires at least two variant_ids",
        )


@router.post("/reason", response_model=MoEResult)
async def reason(
    request: ReasonRequest,
    repo: RepositoryProtocol = Depends(get_repository),
    llm: CompletionClient | None = Depends(_maybe_llm),
) -> MoEResult:
    _validate_mode(request)
    loader = RepositoryGraphLoader(repo)
    try:
        return await run_moe(
            query=request.query,
            variant_ids=request.variant_ids,
            reasoner_name=request.reasoner,
            aggregator_name=request.aggregator,
            loader=loader,
            reasoner_params=request.reasoner_params,
            aggregator_params=request.aggregator_params,
            llm=llm,
        )
    except MoEError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/reason/stream")
async def reason_stream(
    request: ReasonRequest,
    repo: RepositoryProtocol = Depends(get_repository),
    llm: CompletionClient | None = Depends(_maybe_llm),
) -> StreamingResponse:
    """SSE: per-expert events as they finish, then 'answer', then 'done'.

    SSE frames look like `event: expert\\ndata: {...}\\n\\n`. The wizard's
    chat-affordance and the split-view UI consume the same stream.
    """

    _validate_mode(request)
    loader = RepositoryGraphLoader(repo)

    queue = await stream_moe(
        query=request.query,
        variant_ids=request.variant_ids,
        reasoner_name=request.reasoner,
        aggregator_name=request.aggregator,
        loader=loader,
        reasoner_params=request.reasoner_params,
        aggregator_params=request.aggregator_params,
        llm=llm,
    )

    async def _gen():
        while True:
            event_type, payload = await queue.get()
            if event_type == "done":
                yield "event: done\ndata: {}\n\n"
                return
            if event_type == "error":
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'message': str(payload)}, ensure_ascii=False)}\n\n"
                )
                continue
            try:
                if hasattr(payload, "model_dump_json"):
                    body = payload.model_dump_json()
                else:
                    body = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception as e:
                body = json.dumps({"serialize_error": str(e)})
            yield f"event: {event_type}\ndata: {body}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
