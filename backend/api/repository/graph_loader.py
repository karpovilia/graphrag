"""Repository-backed GraphLoader.

Adapter that lets Reasoners (Phase 1.4) and the MoE orchestrator (4.2)
fetch the nodes / edges of a variant without depending on the
RepositoryProtocol directly.
"""

from __future__ import annotations

from api.domain.graph import Edge, Node
from api.domain.types import Id

from .protocol import RepositoryProtocol


class RepositoryGraphLoader:
    backend = "repository"

    def __init__(self, repo: RepositoryProtocol) -> None:
        self._repo = repo

    async def load_nodes(self, graph_variant_id: Id) -> list[Node]:
        state = await self._repo.load_state(graph_variant_id)
        return list(state.nodes)

    async def load_edges(self, graph_variant_id: Id) -> list[Edge]:
        state = await self._repo.load_state(graph_variant_id)
        return list(state.edges)
