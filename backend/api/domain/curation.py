from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .types import DomainModel, Id, Provenance, new_id, utcnow


class JournalOp(StrEnum):
    """Append-only curation operations on a GraphVariant.

    Every UI edit and every accepted Suggestion lands here. Replay of the
    journal against the parent variant must reproduce the current state.
    """

    MERGE_NODES = "merge_nodes"
    SPLIT_NODE = "split_node"
    RETYPE_NODE = "retype_node"
    MOVE_TO_COMMUNITY = "move_to_community"
    EDIT_EDGE = "edit_edge"
    DELETE_EDGE = "delete_edge"
    DELETE_NODE = "delete_node"
    ADD_EDGE = "add_edge"
    SET_SUMMARY = "set_summary"
    UPDATE_NODE_NAME = "update_node_name"


class JournalEntry(DomainModel):
    id: Id = Field(default_factory=new_id)
    graph_variant_id: Id
    op: JournalOp
    payload: dict[str, Any]
    """Op-specific fields. Schema is op-versioned — see strategies/journal.py.

    Examples:
        MERGE_NODES: {"survivor_id": Id, "absorbed_ids": [Id, ...]}
        MOVE_TO_COMMUNITY: {"node_id": Id, "from_community_id": Id, "to_community_id": Id}
    """

    actor: str
    """Either "user:<email>" or "agent:<agent_name>"."""

    parent_entry_id: Id | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SuggestionAction(StrEnum):
    """The set of mutations a curation agent can propose. Mirrors a subset
    of JournalOp — accepting a Suggestion creates the matching JournalEntry.
    """

    MERGE = "merge"
    SPLIT = "split"
    RETYPE = "retype"
    MOVE = "move"
    DELETE = "delete"
    EDIT_RELATION = "edit_relation"


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Suggestion(DomainModel):
    """An agent's proposal — never auto-applied. The user accepts to make
    the edit a JournalEntry.
    """

    id: Id = Field(default_factory=new_id)
    graph_variant_id: Id
    agent: str
    action: SuggestionAction
    target_node_ids: list[Id] = Field(default_factory=list)
    target_edge_ids: list[Id] = Field(default_factory=list)
    payload: dict[str, Any]
    """Action-specific. Same versioning policy as JournalEntry.payload."""

    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence: list[Provenance] = Field(default_factory=list)
    cost_estimate_tokens: int | None = Field(default=None, ge=0)
    status: SuggestionStatus = SuggestionStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None
    resulting_journal_entry_id: Id | None = None
