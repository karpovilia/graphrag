"""Typed payload schemas for each JournalOp.

Domain JournalEntry stores `payload: dict[str, Any]` because Pydantic
discriminated unions over the op enum get noisy at the persistence
boundary. The applier validates against these models on the way in
and on replay so the schema is enforced at the application boundary
without polluting the wire format.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from api.domain.curation import JournalOp
from api.domain.types import DomainModel, Id


class MergeNodesPayload(DomainModel):
    survivor_id: Id
    absorbed_ids: list[Id]
    reason: str | None = None


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
    JournalOp.ADD_EDGE: AddEdgePayload,
    JournalOp.SET_SUMMARY: SetSummaryPayload,
    JournalOp.UPDATE_NODE_NAME: UpdateNodeNamePayload,
}


def parse_payload(op: JournalOp, payload: dict[str, Any]) -> JournalOpPayload:
    """Inflate a wire-format payload dict to the typed model. Raises
    pydantic.ValidationError on schema mismatch.
    """

    return _OP_TO_MODEL[op].model_validate(payload)
