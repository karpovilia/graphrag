"""Conversational curation assistant route.

`POST /graphs/{variant_id}/assistant` takes a free-text instruction, asks the
LLM to plan curation ops, and applies them through the normal journal path
(journalled + undoable). Returns the assistant's reply, what it applied, and
the updated variant so the canvas can refresh.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.assistant import CurationAssistant
from api.domain.curation import JournalEntry
from api.domain.graph import GraphVariant
from api.domain.types import DomainModel, Id
from api.llm import CompletionClient
from api.llm.registry import get_completion_client
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository

router = APIRouter(prefix="/api", tags=["assistant"])


def _assistant_llm() -> CompletionClient | None:
    """Default completion provider (Deepseek in dev). None if none registered
    — surfaced as a 503 so the UI can tell the user to configure a key."""
    try:
        return get_completion_client()
    except (RuntimeError, KeyError):
        return None


class ChatMessage(DomainModel):
    role: str
    content: str


class AssistantRequest(DomainModel):
    message: str = Field(min_length=1)
    selected_node_ids: list[str] = Field(default_factory=list)
    slice_node_ids: list[str] = Field(default_factory=list)
    """Ids of the nodes currently visible (the "текущий срез") — scopes
    find/highlight. Empty = whole graph."""
    highlighted_node_ids: list[str] = Field(default_factory=list)
    """Ids the assistant highlighted on the previous turn — carried back so a
    follow-up ("слей их всех", "удали этих") resolves «их»/«эти»."""
    history: list[ChatMessage] = Field(default_factory=list)
    expected_version: int = Field(ge=0)
    actor: str = Field(default="user:ui", min_length=1)


class AppliedOp(DomainModel):
    op: str
    payload: dict
    ok: bool
    error: str | None = None


class AssistantResponse(DomainModel):
    message: str
    applied: list[AppliedOp]
    highlight: list[str] = []
    """Node ids to light up on the graph (read-only, from highlight_nodes)."""
    variant: GraphVariant
    recompute_ms: float = 0.0


@router.post(
    "/graphs/{variant_id}/assistant",
    response_model=AssistantResponse,
)
async def assistant_chat(
    variant_id: Id,
    body: AssistantRequest,
    repo: RepositoryProtocol = Depends(get_repository),
    llm: CompletionClient | None = Depends(_assistant_llm),
) -> AssistantResponse:
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="no completion provider configured (set DEEPSEEK__API_KEY)",
        )
    try:
        variant = await repo.get_variant(variant_id)
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    plan = await CurationAssistant(llm).plan(
        state,
        message=body.message,
        selected_node_ids=body.selected_node_ids,
        slice_node_ids=body.slice_node_ids,
        highlighted_node_ids=body.highlighted_node_ids,
        history=[m.model_dump() for m in body.history],
    )

    applied: list[AppliedOp] = []
    version = body.expected_version
    total_ms = 0.0
    for planned in plan.ops:
        entry = JournalEntry(
            graph_variant_id=variant_id,
            op=planned.op,
            payload=planned.payload,
            actor=body.actor,
        )
        try:
            result = await repo.append_journal(
                variant_id, entry, expected_version=version, actor=body.actor
            )
            variant = result.variant
            version = variant.version
            total_ms += result.recompute_ms
            applied.append(
                AppliedOp(op=planned.op.value, payload=planned.payload, ok=True)
            )
        except Exception as e:  # noqa: BLE001
            # One bad op shouldn't sink the rest — record and move on. The
            # version isn't advanced by a failed apply, so the loop stays
            # consistent for the next op.
            applied.append(
                AppliedOp(
                    op=planned.op.value,
                    payload=planned.payload,
                    ok=False,
                    error=str(e),
                )
            )

    return AssistantResponse(
        message=plan.message,
        applied=applied,
        highlight=plan.highlight,
        variant=variant,
        recompute_ms=total_ms,
    )
