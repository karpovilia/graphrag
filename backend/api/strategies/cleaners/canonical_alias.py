"""Canonical-alias cleaner.

Applies a *saved* alias dictionary (alias name → canonical name) to a freshly
built graph, so manual merge decisions made on an earlier variant survive
re-ingestion: new texts that re-introduce the same fragmented entities get
folded back into their canonical node automatically, instead of forcing the
user to re-merge every rebuild.

This is the missing feedback loop for curation: a merge on variant N teaches a
name→canonical mapping; running this cleaner on variant N+1 (built from new
documents) replays those decisions. It is name-based on purpose — node UUIDs
are not stable across builds, names (and their canonical form) are.

Pure: state in, state out. For each entity node it resolves a canonical name
(`aliases[name]` if present, else the name itself), groups entities by canonical
name, renames the survivor to the canonical form, and absorbs the rest (edges
redirected, a MERGE_NODES journal entry per absorbed node). Non-entity layers
are untouched.

The alias dictionary is supplied via params (`aliases`); a caller can derive it
from a prior variant's curation journal — see
`canonical_aliases_from_merges()`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge, Layer, Node
from api.domain.types import Id, new_id

from ..registry import cleaners
from ..state import GraphBuildState


@cleaners.register(
    "canonical_alias",
    summary="Apply a saved alias dictionary (name → canonical) so manual merges survive re-ingestion.",
    description=(
        "Replays prior merge decisions on a freshly built graph: entity nodes "
        "whose name is a known alias are renamed to the canonical form and "
        "folded together (edges redirected, MERGE_NODES journalled). Name-based "
        "(UUIDs aren't stable across builds). Feed `aliases` from a previous "
        "variant's curation journal so new texts don't re-create merged dupes."
    ),
    requires_layers=(Layer.ENTITY,),
    params_schema={
        "aliases": {
            "type": "object",
            "default": {},
            "description": "Map {alias_name: canonical_name}. Several aliases may share one canonical.",
        },
        "case_insensitive": {
            "type": "boolean",
            "default": True,
            "description": "Match alias keys against node names case-insensitively (trimmed).",
        },
        "actor": {
            "type": "string",
            "default": "cleaner:canonical_alias",
            "description": "Recorded as JournalEntry.actor for the replayed merges.",
        },
    },
    cost_hint="cheap",
)
class CanonicalAlias:
    descriptor: Any  # set by the decorator

    async def clean(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState:
        raw_aliases: dict[str, str] = dict(params.get("aliases") or {})
        if not raw_aliases:
            return state
        ci = bool(params.get("case_insensitive", True))
        actor = str(params.get("actor", "cleaner:canonical_alias"))

        def norm(s: str) -> str:
            s = s.strip()
            return s.lower() if ci else s

        # alias lookup keyed on normalized alias name → canonical name
        alias_map = {norm(k): v for k, v in raw_aliases.items() if k.strip()}

        def canonical_of(name: str) -> str:
            return alias_map.get(norm(name), name)

        # Group entity nodes by their resolved canonical name.
        groups: dict[str, list[Node]] = defaultdict(list)
        for n in state.nodes:
            if n.layer == Layer.ENTITY:
                groups[canonical_of(n.name)].append(n)

        merges: dict[Id, Id] = {}  # absorbed_id -> survivor_id
        survivors_by_id: dict[Id, Node] = {}
        new_journal = list(state.journal)
        touched = False

        for cname, grp in groups.items():
            # Survivor preference: a node already named the canonical form,
            # then the richest summary, then id order (deterministic replay).
            grp.sort(
                key=lambda n: (norm(n.name) != norm(cname), -len(n.summary or ""), str(n.id))
            )
            survivor = grp[0]
            # Rename survivor to the canonical form + stamp canonical_id so the
            # decision is self-describing on the new variant too.
            if survivor.name != cname or survivor.canonical_id is None:
                survivor = survivor.model_copy(
                    update={"name": cname, "canonical_id": survivor.canonical_id or survivor.id}
                )
                touched = True
            survivors_by_id[survivor.id] = survivor

            for absorbed in grp[1:]:
                merges[absorbed.id] = survivor.id
                touched = True
                new_journal.append(
                    JournalEntry(
                        id=new_id(),
                        graph_variant_id=survivor.graph_variant_id,
                        op=JournalOp.MERGE_NODES,
                        payload={
                            "survivor_id": str(survivor.id),
                            "absorbed_ids": [str(absorbed.id)],
                            "reason": f"canonical alias: '{absorbed.name}' → '{cname}'",
                        },
                        actor=actor,
                    )
                )

        if not touched:
            return state

        # Rebuild node list: non-entities unchanged; entity survivors replaced
        # with their renamed copy; absorbed entities dropped.
        new_nodes: list[Node] = []
        for n in state.nodes:
            if n.layer != Layer.ENTITY:
                new_nodes.append(n)
            elif n.id in merges:
                continue  # absorbed
            else:
                new_nodes.append(survivors_by_id.get(n.id, n))

        new_edges = _redirect_edges(state.edges, merges)
        return GraphBuildState(nodes=new_nodes, edges=new_edges, journal=new_journal)


def canonical_aliases_from_merges(
    pairs: list[tuple[str, str]],
) -> dict[str, str]:
    """Build a flat {alias: canonical} map from (absorbed_name, survivor_name)
    pairs (e.g. extracted from a prior variant's MERGE_NODES history with node
    names resolved). Resolves one level of chaining so alias→intermediate→
    canonical collapses to alias→canonical."""

    direct: dict[str, str] = {}
    for absorbed, survivor in pairs:
        if absorbed.strip() and survivor.strip():
            direct[absorbed.strip()] = survivor.strip()

    def resolve(name: str, seen: set[str]) -> str:
        if name in direct and name not in seen:
            seen.add(name)
            return resolve(direct[name], seen)
        return name

    return {alias: resolve(canon, {alias}) for alias, canon in direct.items()}


def _redirect_edges(edges: list[Edge], merges: dict[Id, Id]) -> list[Edge]:
    """Reattach edges from absorbed nodes onto survivors, dropping self-loops
    and duplicates (first occurrence — and its provenance — wins)."""

    out: list[Edge] = []
    seen: set[tuple[Id, Id, str]] = set()
    for e in edges:
        src = merges.get(e.source_node_id, e.source_node_id)
        tgt = merges.get(e.target_node_id, e.target_node_id)
        if src == tgt:
            continue
        key = (src, tgt, e.type.value)
        if key in seen:
            continue
        seen.add(key)
        if src == e.source_node_id and tgt == e.target_node_id:
            out.append(e)
        else:
            out.append(
                e.model_copy(update={"source_node_id": src, "target_node_id": tgt})
            )
    return out
