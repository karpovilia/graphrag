"""Agent + Suggestion routes.

POST /api/graphs/{id}/agents/{name}/run — run an agent against the
variant, persist proposed suggestions, return them.
GET  /api/graphs/{id}/suggestions — list suggestions for a variant
                                     with status / agent filters.
POST /api/suggestions/{id}/accept — accept; turns into JournalEntry.
POST /api/suggestions/{id}/reject — reject without applying.
GET  /api/agents — list registered agents (descriptors).
"""

from __future__ import annotations

import api.agents  # noqa: F401  — trigger @register decorators
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.domain.curation import Suggestion, SuggestionStatus
from api.domain.types import DomainModel, Id
from api.repository import (
    ConcurrentEditError,
    NotFoundError,
    RepositoryError,
    RepositoryProtocol,
)
from api.repository.protocol import JournalAppendResult
from api.runtime import get_repository
from api.strategies import StrategyDescriptor
from api.strategies.registry import agents as agents_registry

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents", response_model=list[StrategyDescriptor])
def list_agents() -> list[StrategyDescriptor]:
    return agents_registry.list()


class AgentRunRequest(DomainModel):
    params: dict = Field(default_factory=dict)


class AgentRunResponse(DomainModel):
    agent: str
    suggestions: list[Suggestion]


@router.post(
    "/graphs/{variant_id}/agents/{agent_name}/run",
    response_model=AgentRunResponse,
)
async def run_agent(
    variant_id: Id,
    agent_name: str,
    body: AgentRunRequest | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> AgentRunResponse:
    if not agents_registry.has(agent_name):
        raise HTTPException(
            status_code=404,
            detail=f"agent {agent_name!r} not registered. "
            f"Available: {agents_registry.names()}",
        )
    try:
        await repo.get_variant(variant_id)
        state = await repo.load_state(variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    cls = agents_registry.get(agent_name)
    agent = cls()  # all R2 agents are stateless
    params = (body.params if body else {}) or {}
    try:
        proposals = await agent.propose(variant_id, state, params)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e

    if proposals:
        await repo.create_suggestions(proposals)
    return AgentRunResponse(agent=agent_name, suggestions=proposals)


@router.get(
    "/graphs/{variant_id}/suggestions",
    response_model=list[Suggestion],
)
async def list_suggestions(
    variant_id: Id,
    status: SuggestionStatus | None = None,
    agent: str | None = None,
    limit: int | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[Suggestion]:
    return await repo.list_suggestions(
        variant_id, status=status, agent=agent, limit=limit
    )


class AcceptSuggestionRequest(DomainModel):
    expected_variant_version: int = Field(ge=0)
    actor: str = Field(min_length=1)


@router.post(
    "/suggestions/{suggestion_id}/accept",
    response_model=JournalAppendResult,
)
async def accept_suggestion(
    suggestion_id: Id,
    body: AcceptSuggestionRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> JournalAppendResult:
    try:
        return await repo.accept_suggestion(
            suggestion_id,
            expected_variant_version=body.expected_variant_version,
            actor=body.actor,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ConcurrentEditError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "expected": e.expected,
                "actual": e.actual,
            },
        ) from e
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class RejectSuggestionRequest(DomainModel):
    actor: str = Field(min_length=1)


@router.post(
    "/suggestions/{suggestion_id}/reject",
    response_model=Suggestion,
)
async def reject_suggestion(
    suggestion_id: Id,
    body: RejectSuggestionRequest,
    repo: RepositoryProtocol = Depends(get_repository),
) -> Suggestion:
    try:
        return await repo.reject_suggestion(suggestion_id, actor=body.actor)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
