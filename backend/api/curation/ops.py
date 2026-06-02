"""Typed payload schemas for each JournalOp.

Domain JournalEntry stores `payload: dict[str, Any]` because Pydantic
discriminated unions over the op enum get noisy at the persistence
boundary. The applier validates against these models on the way in
and on replay so the schema is enforced at the application boundary
without polluting the wire format.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from api.domain.curation import JournalOp
from api.domain.types import DomainModel, Id


class MergeNodesPayload(DomainModel):
    survivor_id: Id
    absorbed_ids: list[Id]
    reason: str | None = None
    new_name: str | None = None
    """Optional rename of the survivor as part of the merge.

    The demo scenario (docs/redesign/demo_scenario.md §5) treats merge
    + rename as one user gesture: pick a survivor, rename it to the
    canonical form. Stored as part of the same JournalEntry so undo
    rolls back both changes atomically. None = leave survivor's name
    untouched."""


class SplitNodePayload(DomainModel):
    original_id: Id
    new_nodes: list[dict[str, Any]]
    """Each dict gets fed to Node(**...) — must be a complete spec
    (graph_variant_id, layer, type, granularity, name)."""

    edge_redirect: dict[str, Id] = Field(default_factory=dict)
    """edge_id → which of the new nodes inherits each edge that touched
    the original. Edges not in this map default to the first new node."""


class RetypeNodePayload(DomainModel):
    node_id: Id
    new_type: str
    old_type: str | None = None


class MoveToCommunityPayload(DomainModel):
    node_id: Id
    to_community_id: Id
    from_community_id: Id | None = None


class EditEdgePayload(DomainModel):
    edge_id: Id
    updates: dict[str, Any]
    """Subset of Edge fields to update (weight / relation / explanation /
    attributes). Refused at apply time if the field doesn't exist."""


class DeleteEdgePayload(DomainModel):
    edge_id: Id
    reason: str | None = None
    """Human-readable cause (parity with MergeNodesPayload.reason). When
    an auto-invalidation delete supplies one it feeds Edge.invalidation
    provenance (§1.4) — and switches the applier to *soft* delete: the
    edge stays in state with tx_to + invalidation stamped instead of
    being dropped. reason=None keeps the legacy hard-delete behaviour."""

    ingestion_event_id: Id | None = None
    """Which ingestion event retired this edge (§1.4 provenance). Linked
    into Edge.invalidation. None for a manual curation delete."""

    superseded_at: datetime | None = None
    """tx_to / invalidation.at instant for the soft delete. Filled by the
    journal-append route from the linked IngestionEvent.ingested_at (so
    the death lands inside the historical tx window), NOT by the client.
    Falls back to the entry timestamp when absent."""


class DeleteNodePayload(DomainModel):
    node_id: Id
    """Removes the node and every edge that referenced it. Used by the
    OrphanRescuer agent's DELETE Suggestions when the user accepts."""

    reason: str | None = None
    """Human-readable cause for the deletion (§1.4)."""


class AddEdgePayload(DomainModel):
    edge: dict[str, Any]
    """Full Edge spec for instantiation."""


class SetSummaryPayload(DomainModel):
    node_id: Id
    summary: str | None


class UpdateNodeNamePayload(DomainModel):
    node_id: Id
    name: str


JournalOpPayload = (
    MergeNodesPayload
    | SplitNodePayload
    | RetypeNodePayload
    | MoveToCommunityPayload
    | EditEdgePayload
    | DeleteEdgePayload
    | DeleteNodePayload
    | AddEdgePayload
    | SetSummaryPayload
    | UpdateNodeNamePayload
)


_OP_TO_MODEL = {
    JournalOp.MERGE_NODES: MergeNodesPayload,
    JournalOp.SPLIT_NODE: SplitNodePayload,
    JournalOp.RETYPE_NODE: RetypeNodePayload,
    JournalOp.MOVE_TO_COMMUNITY: MoveToCommunityPayload,
    JournalOp.EDIT_EDGE: EditEdgePayload,
    JournalOp.DELETE_EDGE: DeleteEdgePayload,
    JournalOp.DELETE_NODE: DeleteNodePayload,
    JournalOp.ADD_EDGE: AddEdgePayload,
    JournalOp.SET_SUMMARY: SetSummaryPayload,
    JournalOp.UPDATE_NODE_NAME: UpdateNodeNamePayload,
}


def parse_payload(op: JournalOp, payload: dict[str, Any]) -> JournalOpPayload:
    """Inflate a wire-format payload dict to the typed model. Raises
    pydantic.ValidationError on schema mismatch.
    """

    return _OP_TO_MODEL[op].model_validate(payload)
