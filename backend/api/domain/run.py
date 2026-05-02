from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .types import DomainModel, Id, new_id, utcnow


class RunKind(StrEnum):
    """The kinds of background work whose progress and provenance we track.

    Each Run id is what an SSE stream identifies; lookup of evidence later
    in a Suggestion or in a QA answer goes through the run that produced it.
    """

    BUILD = "build"
    CLEAN = "clean"
    CLUSTER = "cluster"
    SUMMARIZE = "summarize"
    REASON = "reason"
    AGENT = "agent"
    EDA = "eda"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Run(DomainModel):
    id: Id = Field(default_factory=new_id)
    kind: RunKind
    strategy: str
    """The plugin name that owns this run, e.g. "builder:lightrag" or
    "agent:entity_dedup".
    """

    corpus_id: Id | None = None
    graph_variant_id: Id | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.QUEUED
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cost_tokens_in: int = Field(default=0, ge=0)
    cost_tokens_out: int = Field(default=0, ge=0)
    cost_currency: str | None = None
    cost_amount: float | None = None


class ToolInvocation(DomainModel):
    """A NodeTool call. Cached on a Node and reusable as evidence by
    subsequent reasoner runs.
    """

    id: Id = Field(default_factory=new_id)
    node_id: Id
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    cost_tokens: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
