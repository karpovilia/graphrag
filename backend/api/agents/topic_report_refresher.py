from __future__ import annotations

from typing import Any

from api.curation.applier import affected_set
from api.domain.curation import JournalOp, Suggestion, SuggestionAction
from api.domain.graph import EdgeType, Layer
from api.domain.types import Id
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState


@agents.register(
    "topic_report_refresher",
    summary="Suggest summary refresh on COMMUNITY/TOPIC nodes whose membership shifted.",
    description=(
        "Walks the variant's journal looking for ops that changed "
        "community membership (MERGE_NODES, MOVE_TO_COMMUNITY, "
        "RETYPE_NODE). Surfaces affected COMMUNITY-layer (and "
        "TOPIC-layer if present) nodes for summary refresh — the "
        "mechanism is RETYPE/SET_SUMMARY today; in Phase 5 the "
        "summarizer plugin runs against the affected community."
    ),
    requires_layers=(Layer.COMMUNITY,),
    params_schema={
        "max_suggestions": {
            "type": "integer",
            "default": 50,
        },
    },
    cost_hint="cheap",
)
class TopicReportRefresher:
    _SHIFT_OPS = {
        JournalOp.MERGE_NODES,
        JournalOp.SPLIT_NODE,
        JournalOp.MOVE_TO_COMMUNITY,
        JournalOp.RETYPE_NODE,
    }

    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        cap = int(params.get("max_suggestions", 50))

        community_nodes = {
            n.id: n for n in state.nodes if n.layer in (Layer.COMMUNITY, Layer.TOPIC)
        }
        if not community_nodes:
            return []

        # Replay affected_set against current state for each shift-op
        # in the journal. Communities seen ≥1 time → propose refresh.
        shifted_communities: set[Id] = set()
        for entry in state.journal:
            if entry.op not in self._SHIFT_OPS:
                continue
            try:
                eff = affected_set(state, entry)
            except Exception:
                continue
            shifted_communities.update(
                cid for cid in eff.community_ids if cid in community_nodes
            )

        suggestions: list[Suggestion] = []
        for cid in sorted(shifted_communities, key=str)[:cap]:
            community = community_nodes[cid]
            members = _members_of(community.id, state)
            suggestions.append(
                Suggestion(
                    graph_variant_id=graph_variant_id,
                    agent="topic_report_refresher",
                    action=SuggestionAction.EDIT_RELATION,
                    target_node_ids=[community.id],
                    payload={
                        "edge_id": "",  # repurposed: schedules a SET_SUMMARY follow-up
                        "node_id": str(community.id),
                        "summary_status": "stale",
                    },
                    confidence=0.7,
                    rationale=(
                        f"Community {community.name!r} ({members} members) had "
                        f"membership-shifting ops applied; summary may be stale."
                    ),
                )
            )
        return suggestions


def _members_of(community_id: Id, state: GraphBuildState) -> int:
    return sum(
        1
        for e in state.edges
        if e.type == EdgeType.MEMBER_OF and e.target_node_id == community_id
    )
