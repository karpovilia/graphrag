from __future__ import annotations

from typing import Any

from api.domain.graph import Node
from api.domain.types import Id
from api.strategies.protocols import GraphLoader
from api.strategies.registry import tools


@tools.register(
    "wikidata_lookup",
    summary="Wikidata short biographical lookup for a PERSON / ORG / PLACE.",
    description=(
        "External lookup over wikidata.org SPARQL. Stub in Phase 5 — the "
        "concrete httpx integration lands in 5.x once we decide on a "
        "rate-limit policy that respects Wikidata's terms. Until then "
        "the stub returns the input verbatim and a clear note so the "
        "wizard can still surface the menu entry."
    ),
    params_schema={
        "language": {
            "type": "string",
            "default": "ru",
            "description": "Wikidata label language preference.",
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2509.21710v2.pdf",),
)
class WikidataLookup:
    applies_to: tuple[str, ...] = ("PERSON", "ORG", "PLACE")

    async def run(
        self,
        node: Node,
        graph_variant_id: Id,
        params: dict[str, Any],
        loader: GraphLoader,
    ) -> dict[str, Any]:
        return {
            "status": "not_implemented",
            "node_name": node.name,
            "node_type": node.type,
            "language": params.get("language", "ru"),
            "note": (
                "Wikidata lookup wiring lands in Phase 5.x. Stub returns "
                "the input so the menu shape is exercised in tests."
            ),
        }
