from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from api.domain.curation import JournalEntry, JournalOp
from api.domain.graph import Edge, Layer, Node
from api.domain.types import Id, new_id
from api.llm import CompletionClient, CompletionParams, Message

from ..registry import cleaners
from ..state import GraphBuildState

_DEDUP_SYSTEM_PROMPT = """\
Ты помощник, который проверяет, описывают ли две сущности из графа знаний \
один и тот же реальный объект. Учитывай русскую морфологию: разные падежи и \
формы одного и того же имени — это один объект.

Отвечай строго JSON-объектом со схемой:
{"merge": true|false, "reason": "<короткое объяснение>"}\
"""


@cleaners.register(
    "llm_dedup",
    summary="Merge entity nodes that LLM confirms describe the same object.",
    description=(
        "Russian-first deduplication: bucket entities by normalized first "
        "token, ask the LLM whether the candidates are the same object, "
        "merge confirmed pairs into a survivor, redirect edges, append a "
        "MERGE_NODES journal entry per merge. EDA recommends adding this "
        "step when morphological dispersion ≥ 1.5 — the dominant failure "
        "mode in the paper's case study 1."
    ),
    requires_layers=(Layer.ENTITY,),
    params_schema={
        "max_candidate_pairs": {
            "type": "integer",
            "default": 50,
            "description": "Hard cap on LLM calls per run.",
        },
        "min_confidence": {
            "type": "number",
            "default": 0.0,
            "description": "Reserved — Phase 3 agents will use a real confidence channel.",
        },
        "actor": {
            "type": "string",
            "default": "cleaner:llm_dedup",
            "description": "Recorded as JournalEntry.actor for the merge ops.",
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2410.05779v3.pdf", "docs/raw/2509.21710v2.pdf"),
)
class LLMDeduplicator:
    """LLM-driven entity merge.

    Stateful — needs a CompletionClient. Construct with DI; tests pass a
    fake client. Only entity-layer nodes are touched; community/topic
    summaries that referenced merged entities are NOT re-summarized
    here (that's the TopicReportRefresher agent in Phase 3).
    """

    def __init__(self, llm: CompletionClient) -> None:
        self._llm = llm

    async def clean(
        self,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> GraphBuildState:
        max_pairs = int(params.get("max_candidate_pairs", 50))
        actor = str(params.get("actor", "cleaner:llm_dedup"))

        candidates = _candidate_pairs(state.nodes, cap=max_pairs)
        if not candidates:
            return state

        merges: dict[Id, Id] = {}  # absorbed_id -> survivor_id
        survivor_to_absorbed: dict[Id, list[Id]] = defaultdict(list)
        new_journal = list(state.journal)

        for survivor, absorbed in candidates:
            if survivor.id in merges or absorbed.id in merges:
                # Already touched in this pass — defer cascading merges.
                continue
            decision = await self._ask_llm(survivor, absorbed)
            if not decision:
                continue
            merges[absorbed.id] = survivor.id
            survivor_to_absorbed[survivor.id].append(absorbed.id)
            new_journal.append(
                JournalEntry(
                    id=new_id(),
                    graph_variant_id=survivor.graph_variant_id,
                    op=JournalOp.MERGE_NODES,
                    payload={
                        "survivor_id": str(survivor.id),
                        "absorbed_ids": [str(absorbed.id)],
                        "reason": decision,
                    },
                    actor=actor,
                )
            )

        if not merges:
            return state

        new_nodes = _apply_node_merges(state.nodes, merges)
        new_edges = _redirect_edges(state.edges, merges)
        return GraphBuildState(nodes=new_nodes, edges=new_edges, journal=new_journal)

    async def _ask_llm(self, a: Node, b: Node) -> str | None:
        user_text = (
            "Сущность A: имя={a_name!r}, тип={a_type}, summary={a_sum!r}\n"
            "Сущность B: имя={b_name!r}, тип={b_type}, summary={b_sum!r}\n"
            "Это один и тот же объект?"
        ).format(
            a_name=a.name,
            a_type=a.type,
            a_sum=(a.summary or "")[:200],
            b_name=b.name,
            b_type=b.type,
            b_sum=(b.summary or "")[:200],
        )
        messages = [
            Message(role="system", content=_DEDUP_SYSTEM_PROMPT),
            Message(role="user", content=user_text),
        ]
        result = await self._llm.complete(
            messages,
            CompletionParams(
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"},
            ),
        )
        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError:
            return None
        if not bool(payload.get("merge")):
            return None
        reason = payload.get("reason")
        return str(reason) if reason else "merge confirmed by llm"


def _normalize(name: str) -> str:
    """Crude bucketing key — first whitespace-separated token, lowercased.
    Russian morphology: enough to gather "Иванов"/"Иванова"/"Иванову" into
    the same bucket; a real-world rollout swaps this for natasha lemmatization
    (already a dep — wired in Phase 3 EntityDeduplicator agent).
    """

    return name.strip().split()[0].lower() if name.strip() else ""


def _candidate_pairs(nodes: list[Node], cap: int) -> list[tuple[Node, Node]]:
    buckets: dict[tuple[str, str], list[Node]] = defaultdict(list)
    for n in nodes:
        if n.layer != Layer.ENTITY:
            continue
        key = (n.type, _normalize(n.name))
        if not key[1]:
            continue
        buckets[key].append(n)

    pairs: list[tuple[Node, Node]] = []
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        # Survivor heuristic: longest summary first; ties broken by id ordering
        # for determinism (matters for replay).
        bucket.sort(key=lambda n: (-len(n.summary or ""), str(n.id)))
        survivor = bucket[0]
        for absorbed in bucket[1:]:
            pairs.append((survivor, absorbed))
            if len(pairs) >= cap:
                return pairs
    return pairs


def _apply_node_merges(nodes: list[Node], merges: dict[Id, Id]) -> list[Node]:
    return [n for n in nodes if n.id not in merges]


def _redirect_edges(edges: list[Edge], merges: dict[Id, Id]) -> list[Edge]:
    out: list[Edge] = []
    seen_pairs: set[tuple[Id, Id, str]] = set()
    for e in edges:
        src = merges.get(e.source_node_id, e.source_node_id)
        tgt = merges.get(e.target_node_id, e.target_node_id)
        if src == tgt:
            # Self-loop after redirect — drop.
            continue
        key = (src, tgt, e.type.value)
        if key in seen_pairs:
            # Duplicate after redirect; keep the first occurrence so the
            # original Edge id (and provenance) wins.
            continue
        seen_pairs.add(key)
        if src == e.source_node_id and tgt == e.target_node_id:
            out.append(e)
        else:
            out.append(
                e.model_copy(update={"source_node_id": src, "target_node_id": tgt})
            )
    return out
