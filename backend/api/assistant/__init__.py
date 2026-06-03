"""Conversational curation assistant.

A free-text helper over a graph variant: the user types what they want fixed
("delete the 'Да' node", "Воксисом is an organisation, change its type") and
the assistant picks the right curation operations and fills them in. It reuses
the whole existing curation stack — the typed op payloads (api.curation.ops),
the journal applier, undo — so every change the assistant makes is journalled
and reversible. The LLM only *selects and parameterises* ops; persistence stays
in the repository.
"""

from __future__ import annotations

from .curation_assistant import (
    AssistantPlan,
    CurationAssistant,
    PlannedOp,
    build_graph_context,
)

__all__ = [
    "AssistantPlan",
    "CurationAssistant",
    "PlannedOp",
    "build_graph_context",
]
