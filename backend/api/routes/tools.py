"""Tools-on-nodes routes (Phase 5.4).

GET  /api/nodes/{variant_id}/{node_id}/tools           — applicable tools menu
POST /api/nodes/{variant_id}/{node_id}/tools/{name}/run — execute, persist
GET  /api/nodes/{variant_id}/{node_id}/tool_invocations — history (cache view)
"""

from __future__ import annotations

import api.tools  # noqa: F401  — trigger @register
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.domain.run import ToolInvocation
from api.domain.types import DomainModel, Id, new_id
from api.repository import (
    NotFoundError,
    RepositoryGraphLoader,
    RepositoryProtocol,
)
from api.runtime import get_repository
from api.strategies import StrategyDescriptor
from api.strategies.registry import tools as tools_registry

router = APIRouter(prefix="/api", tags=["tools"])


def _filter_tools_for_node(node_type: str) -> list[StrategyDescriptor]:
    """A tool is applicable when its `applies_to` is empty (universal)
    or contains the node's type. Lookup uses the class-level
    attribute, not the descriptor — descriptor metadata stays free of
    the type-binding to keep the wizard schema simple.
    """

    out: list[StrategyDescriptor] = []
    for descriptor in tools_registry.list():
        cls = tools_registry.get(descriptor.name)
        applies_to = getattr(cls, "applies_to", ())
        if not applies_to or node_type in applies_to:
            out.append(descriptor)
    return out


@router.get(
    "/nodes/{variant_id}/{node_id}/tools",
    response_model=list[StrategyDescriptor],
)
async def list_applicable_tools(
    variant_id: Id,
    node_id: Id,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[StrategyDescriptor]:
    try:
        node = await repo.find_node(variant_id, node_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _filter_tools_for_node(node.type)


class RunToolRequest(DomainModel):
    params: dict = Field(default_factory=dict)


@router.post(
    "/nodes/{variant_id}/{node_id}/tools/{tool_name}/run",
    response_model=ToolInvocation,
)
async def run_tool(
    variant_id: Id,
    node_id: Id,
    tool_name: str,
    body: RunToolRequest | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> ToolInvocation:
    if not tools_registry.has(tool_name):
        raise HTTPException(
            status_code=404,
            detail=f"tool {tool_name!r} not registered",
        )
    try:
        node = await repo.find_node(variant_id, node_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    cls = tools_registry.get(tool_name)
    tool = cls()
    applies_to = getattr(tool, "applies_to", ())
    if applies_to and node.type not in applies_to:
        raise HTTPException(
            status_code=400,
            detail=f"tool {tool_name!r} does not apply to node type {node.type!r}; expected one of {list(applies_to)}",
        )

    params = body.params if body else {}
    loader = RepositoryGraphLoader(repo)
    try:
        result = await tool.run(node, variant_id, params, loader)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"tool failed: {e}") from e

    invocation = ToolInvocation(
        id=new_id(),
        node_id=node_id,
        tool=tool_name,
        arguments=params,
        result=result,
    )
    return await repo.record_tool_invocation(invocation)


@router.get(
    "/nodes/{variant_id}/{node_id}/tool_invocations",
    response_model=list[ToolInvocation],
)
async def list_tool_invocations(
    variant_id: Id,
    node_id: Id,
    tool: str | None = None,
    limit: int | None = None,
    repo: RepositoryProtocol = Depends(get_repository),
) -> list[ToolInvocation]:
    try:
        await repo.find_node(variant_id, node_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return await repo.list_tool_invocations(node_id, tool=tool, limit=limit)
