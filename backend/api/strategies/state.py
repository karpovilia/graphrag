from __future__ import annotations

from dataclasses import dataclass, field

from api.domain.curation import JournalEntry
from api.domain.graph import Edge, Node


@dataclass
class GraphBuildState:
    """In-memory graph as it flows through builder → cleaners → clusterer.

    Domain entities (Node, Edge) keep their identity across stages so
    provenance survives. The journal accumulates structural ops applied
    along the way; once persisted (Phase 2), it becomes the variant's
    initial JournalEntry stream.

    Cleaners are pure-ish: they consume one state and produce another.
    No DB I/O happens until the orchestrator persists at the end of the
    pipeline.
    """

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    journal: list[JournalEntry] = field(default_factory=list)

    def node_index(self) -> dict:
        return {n.id: n for n in self.nodes}

    def edge_index(self) -> dict:
        return {e.id: e for e in self.edges}
