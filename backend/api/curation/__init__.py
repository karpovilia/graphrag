"""Curation engine: journal append, replay, affected-set computation.

Pure functions over GraphBuildState. The repository layer wraps these
to materialize curation ops as a transactional (state, journal entry,
vector_outbox) tuple.
"""

from .applier import (
    AffectedSet,
    JournalApplyError,
    affected_set,
    apply_journal_op,
    replay_journal,
)
from .ops import (
    AddEdgePayload,
    DeleteEdgePayload,
    DeleteNodePayload,
    EditEdgePayload,
    JournalOpPayload,
    MergeNodesPayload,
    MoveToCommunityPayload,
    RetypeNodePayload,
    SetSummaryPayload,
    SplitNodePayload,
    UpdateNodeNamePayload,
    parse_payload,
)

__all__ = [
    "AddEdgePayload",
    "AffectedSet",
    "DeleteEdgePayload",
    "DeleteNodePayload",
    "EditEdgePayload",
    "JournalApplyError",
    "JournalOpPayload",
    "MergeNodesPayload",
    "MoveToCommunityPayload",
    "RetypeNodePayload",
    "SetSummaryPayload",
    "SplitNodePayload",
    "UpdateNodeNamePayload",
    "affected_set",
    "apply_journal_op",
    "parse_payload",
    "replay_journal",
]
