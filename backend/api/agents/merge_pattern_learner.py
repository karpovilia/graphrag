"""Merge-pattern learning agent (active learning over the curation journal).

The user merges fragmented entities by hand. Every accepted MERGE writes a
self-describing journal entry (§A: survivor_name / absorbed_names / entity_type).
This agent reads the last N of those, asks a small local LLM (GLM, reachable
over an SSH tunnel — see `GLMSettings`) to *generalise* what kind of pairs the
user keeps merging, then proposes analogous candidates among the entities that
are still separate.

It runs as a three-step skill — the LLM does the reasoning, the agent does the
plumbing and grounding:

  1. **form-rule**   — from the merge history, articulate a concise rule + the
                       signals that drive it (the LLM writes its own spec).
  2. **build-shortlist** — apply that rule to the current entity inventory and
                       emit candidate (survivor, absorbed) pairs.
  3. **verify**      — re-examine each candidate against the rule, drop the
                       false positives, attach a confidence.

Only pairs whose two names resolve to two *distinct* entity nodes that still
exist become MERGE Suggestions — the LLM cannot invent node ids, and a pair it
hallucinates simply fails to ground and is dropped. The agent never mutates the
graph; it proposes, the user accepts.

Stateless from the route's perspective (`cls()`), but accepts an injected
CompletionClient so tests run without touching the network.
"""

from __future__ import annotations

import json
from typing import Any

from api.config.settings import get_settings
from api.domain.curation import JournalOp, Suggestion, SuggestionAction
from api.domain.graph import Node
from api.domain.types import Id
from api.llm import CompletionClient, CompletionParams, Message
from api.llm.openai_compat import OpenAICompatClient
from api.strategies.registry import agents
from api.strategies.state import GraphBuildState

from ._helpers import entity_nodes

_RULE_SYSTEM = """\
Ты — ассистент куратора графа знаний. Куратор вручную объединял пары сущностей, \
которые описывают один и тот же реальный объект (разные написания, падежи, \
аббревиатуры, опечатки, синонимы). По истории его решений сформулируй ОДНО \
краткое правило, по которому он объединяет, и перечисли наблюдаемые сигналы.

Ответ — строго JSON:
{"rule": "<одно-два предложения>", "signals": ["<сигнал>", ...]}\
"""

_SHORTLIST_SYSTEM = """\
Ты применяешь правило куратора к списку сущностей графа, которые ПОКА НЕ \
объединены. Предложи пары-кандидаты на объединение строго по правилу. \
Используй ТОЛЬКО имена из присланного списка, не выдумывай новые. Survivor — \
более полное/каноничное имя, absorbed — то, что вливается.

Ответ — строго JSON:
{"pairs": [{"survivor": "<имя из списка>", "absorbed": "<имя из списка>", "why": "<кратко>"}]}\
"""

_VERIFY_SYSTEM = """\
Проверь шорт-лист пар-кандидатов на объединение против правила куратора. \
Оставь только те пары, где ты уверен, что это один и тот же объект; отбрось \
сомнительные и омонимы. Для каждой оставшейся пары укажи confidence 0..1.

Ответ — строго JSON:
{"pairs": [{"survivor": "<имя>", "absorbed": "<имя>", "confidence": 0.0}]}\
"""


@agents.register(
    "merge_pattern_learner",
    summary="Learn the user's merge rule from recent merges and propose analogous pairs (GLM).",
    description=(
        "Active-learning curation agent. Reads the last N MERGE_NODES "
        "journal entries (with their structured survivor/absorbed names), "
        "asks a local GLM to generalise the user's merge rule, applies it "
        "to the still-separate entities, verifies the shortlist, and emits "
        "MERGE Suggestions for pairs that ground to two real nodes. Three-"
        "step skill: form-rule → build-shortlist → verify. Backed by GLM "
        "over an SSH tunnel (GLMSettings); tests inject a fake client."
    ),
    params_schema={
        "recent_merges": {
            "type": "integer",
            "default": 100,
            "description": "How many of the most recent MERGE_NODES entries to learn from.",
        },
        "min_merges": {
            "type": "integer",
            "default": 3,
            "description": "Skip the run if fewer than this many merges exist — too little to generalise.",
        },
        "max_entities": {
            "type": "integer",
            "default": 400,
            "description": "Cap on entity names shown to the LLM when building the shortlist.",
        },
        "max_suggestions": {
            "type": "integer",
            "default": 50,
            "description": "Cap on proposals per run.",
        },
        "min_confidence": {
            "type": "number",
            "default": 0.5,
            "description": "Drop verified pairs below this confidence.",
        },
    },
    cost_hint="moderate",
    references=("docs/raw/2410.05779v3.pdf",),
)
class MergePatternLearner:
    descriptor: Any  # set by the decorator

    def __init__(self, llm: CompletionClient | None = None) -> None:
        # Route calls cls() → llm is built lazily from settings on first use.
        # Tests pass a fake client so nothing hits the network.
        self._llm = llm

    def _client(self) -> CompletionClient:
        if self._llm is None:
            cfg = get_settings().glm
            self._llm = OpenAICompatClient(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                default_model=cfg.model,
                timeout_s=cfg.timeout_s,
            )
        return self._llm

    def _params(self) -> CompletionParams:
        """JSON-mode params, with the GLM thinking toggle threaded through
        as an extra_body chat-template kwarg (no-op for other backends)."""
        cfg = get_settings().glm
        return CompletionParams(
            temperature=0.0,
            max_tokens=1500,
            response_format={"type": "json_object"},
            extra={
                "extra_body": {
                    "chat_template_kwargs": {"enable_thinking": cfg.enable_thinking}
                }
            },
        )

    async def propose(
        self,
        graph_variant_id: Id,
        state: GraphBuildState,
        params: dict[str, Any],
    ) -> list[Suggestion]:
        recent_n = int(params.get("recent_merges", 100))
        min_merges = int(params.get("min_merges", 3))
        max_entities = int(params.get("max_entities", 400))
        cap = int(params.get("max_suggestions", 50))
        min_conf = float(params.get("min_confidence", 0.5))

        history = _recent_merges(state, recent_n)
        if len(history) < min_merges:
            return []

        ents = entity_nodes(state.nodes)
        # Names already absorbed in history are gone from the graph; the
        # shortlist is built only over what's still separate.
        by_name = _index_by_name(ents)
        if len(by_name) < 2:
            return []

        rule = await self._form_rule(history)
        if not rule:
            return []

        shown = sorted(ents, key=lambda n: str(n.id))[:max_entities]
        candidates = await self._build_shortlist(rule, shown)
        if not candidates:
            return []

        verified = await self._verify(rule, candidates)

        suggestions: list[Suggestion] = []
        seen: set[tuple[Id, Id]] = set()
        for pair in verified:
            conf = pair.get("confidence")
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = min_conf
            if conf < min_conf:
                continue
            survivor = _resolve(by_name, pair.get("survivor"))
            absorbed = _resolve(by_name, pair.get("absorbed"))
            if survivor is None or absorbed is None or survivor.id == absorbed.id:
                continue
            key = (survivor.id, absorbed.id)
            if key in seen or (absorbed.id, survivor.id) in seen:
                continue
            seen.add(key)
            suggestions.append(
                Suggestion(
                    graph_variant_id=graph_variant_id,
                    agent="merge_pattern_learner",
                    action=SuggestionAction.MERGE,
                    target_node_ids=[survivor.id, absorbed.id],
                    payload={
                        "survivor_id": str(survivor.id),
                        "absorbed_ids": [str(absorbed.id)],
                        "reason": f"merge pattern: {rule['rule']}",
                        "survivor_name": survivor.name,
                        "absorbed_names": [absorbed.name],
                        "entity_type": survivor.type,
                    },
                    confidence=max(0.0, min(1.0, conf)),
                    rationale=(
                        f"Learned rule: {rule['rule']} "
                        f"Proposed merging {absorbed.name!r} into {survivor.name!r}."
                    ),
                )
            )
            if len(suggestions) >= cap:
                break
        return suggestions

    async def _form_rule(self, history: list[dict[str, Any]]) -> dict[str, Any] | None:
        examples = "\n".join(
            f"- [{h['entity_type'] or '?'}] {', '.join(h['absorbed_names'])} → {h['survivor_name']}"
            for h in history
        )
        out = await self._chat(
            _RULE_SYSTEM,
            f"История объединений куратора (absorbed → survivor):\n{examples}",
        )
        if not isinstance(out, dict) or not out.get("rule"):
            return None
        out.setdefault("signals", [])
        return out

    async def _build_shortlist(
        self, rule: dict[str, Any], ents: list[Node]
    ) -> list[dict[str, str]]:
        inventory = "\n".join(f"- [{n.type}] {n.name}" for n in ents)
        signals = ", ".join(str(s) for s in rule.get("signals", []))
        out = await self._chat(
            _SHORTLIST_SYSTEM,
            f"Правило: {rule['rule']}\nСигналы: {signals}\n\n"
            f"Сущности (ещё не объединённые):\n{inventory}",
        )
        return _pairs(out)

    async def _verify(
        self, rule: dict[str, Any], candidates: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        listing = "\n".join(
            f"- {c.get('survivor')} ⇐ {c.get('absorbed')}" for c in candidates
        )
        out = await self._chat(
            _VERIFY_SYSTEM,
            f"Правило: {rule['rule']}\n\nКандидаты на объединение:\n{listing}",
        )
        return _pairs(out)

    async def _chat(self, system: str, user: str) -> Any:
        result = await self._client().complete(
            [
                Message(role="system", content=system),
                Message(role="user", content=user),
            ],
            self._params(),
        )
        return _extract_json(result.text)


def _recent_merges(state: GraphBuildState, n: int) -> list[dict[str, Any]]:
    """Most-recent-first MERGE_NODES entries that carry structured names.
    Entries without survivor_name (legacy merges) are skipped — there's
    nothing to generalise from a bare id pair."""
    out: list[dict[str, Any]] = []
    for entry in reversed(state.journal):
        if entry.op != JournalOp.MERGE_NODES:
            continue
        p = entry.payload
        survivor_name = p.get("survivor_name")
        absorbed_names = [a for a in (p.get("absorbed_names") or []) if a]
        if not survivor_name or not absorbed_names:
            continue
        out.append(
            {
                "survivor_name": survivor_name,
                "absorbed_names": absorbed_names,
                "entity_type": p.get("entity_type"),
            }
        )
        if len(out) >= n:
            break
    return out


def _index_by_name(nodes: list[Node]) -> dict[str, Node]:
    """Case-insensitive, trimmed name → node. First occurrence wins so the
    mapping is deterministic across runs (nodes pre-sorted by caller where
    it matters)."""
    idx: dict[str, Node] = {}
    for n in nodes:
        key = (n.name or "").strip().lower()
        if key and key not in idx:
            idx[key] = n
    return idx


def _resolve(by_name: dict[str, Node], name: Any) -> Node | None:
    if not isinstance(name, str):
        return None
    return by_name.get(name.strip().lower())


def _pairs(out: Any) -> list[dict[str, Any]]:
    if isinstance(out, dict) and isinstance(out.get("pairs"), list):
        return [p for p in out["pairs"] if isinstance(p, dict)]
    if isinstance(out, list):
        return [p for p in out if isinstance(p, dict)]
    return []


def _extract_json(text: str) -> Any:
    """Tolerant JSON parse: handles ```json fences and leading prose that a
    thinking model may still emit. Returns None on failure (caller treats
    that as 'no result' and bails gracefully)."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.lstrip("`")
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
        s = s.strip().rstrip("`").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Last resort: grab the outermost {...} span.
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
