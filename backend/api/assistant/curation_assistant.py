"""The LLM half of the conversational curation assistant.

`CurationAssistant.plan()` turns a free-text instruction + the current graph
context into a validated list of curation operations (and a short reply). It
does NOT touch the repository — the route applies the returned ops through the
normal journal path so journalling/undo/recompute all come for free.

Design notes:
- Provider-agnostic: we ask for a JSON plan rather than relying on native
  function-calling, so it works on Deepseek, GLM, anything with json_object.
- Grounded: the op payloads reference node/edge **ids**, and we hand the model
  an explicit id index. A name the model emits where an id is expected is
  resolved back to an id (case-insensitive) before validation, so "delete Да"
  survives the model echoing the name.
- Safe by construction: every op is validated against api.curation.ops; an op
  that doesn't validate (or targets an unknown node) is dropped, not applied.
"""

from __future__ import annotations

import json
import re
from typing import Any

from api.curation.ops import parse_payload
from api.domain.curation import JournalOp
from api.domain.graph import Layer, Node
from api.domain.types import DomainModel
from api.llm import CompletionClient, CompletionParams, Message
from api.strategies.state import GraphBuildState

# Ops the assistant is allowed to plan. A curated subset of JournalOp — the
# day-to-day cleanup gestures. (split_node / add_edge need richer specs than a
# one-line instruction usually carries, so they're left out of the catalogue
# for now; the model is told to ask instead of guessing.)
_OP_CATALOG: dict[str, str] = {
    "delete_node": '{"op":"delete_node","node_id":"<id>","reason":"<why>"}',
    "retype_node": '{"op":"retype_node","node_id":"<id>","new_type":"<TYPE>"}',
    "update_node_name": '{"op":"update_node_name","node_id":"<id>","name":"<new name>"}',
    "set_summary": '{"op":"set_summary","node_id":"<id>","summary":"<text or null>"}',
    "merge_nodes": (
        '{"op":"merge_nodes","survivor_id":"<id>","absorbed_ids":["<id>"],'
        '"reason":"<why>","survivor_name":"<name>","absorbed_names":["<name>"],'
        '"entity_type":"<TYPE>"}'
    ),
    "delete_edge": '{"op":"delete_edge","edge_id":"<id>","reason":"<why>"}',
    "edit_edge": '{"op":"edit_edge","edge_id":"<id>","updates":{"weight":1.0}}',
    "move_to_community": (
        '{"op":"move_to_community","node_id":"<id>","to_community_id":"<id>"}'
    ),
}

# Read-only "view" actions — NOT journal mutations. The planner pulls these out
# of the ops list and returns the node ids to highlight; nothing is persisted.
_VIEW_CATALOG: dict[str, str] = {
    "highlight_nodes": (
        '{"op":"highlight_nodes","query":"<подстрока имени>","type":"<опц. TYPE>",'
        '"node_ids":["<опц. id>"]}'
    ),
}

# Which payload fields hold node/edge ids — used to resolve a name the model
# may have echoed instead of the id.
_NODE_ID_FIELDS = ("node_id", "survivor_id")
_NODE_ID_LIST_FIELDS = ("absorbed_ids",)

_SYSTEM_PROMPT = """\
Ты — ассистент-куратор графа знаний. Пользователь пишет на естественном языке, \
что сделать с текущим срезом графа; ты выбираешь подходящие операции и \
заполняешь их. Ты НЕ объясняешь, как сделать это вручную — ты выдаёшь сам план \
операций, который система применит (мутации — с возможностью отката).

Операции-мутации (изменяют граф, формат payload):
{catalog}

Операции-просмотр (НИЧЕГО не меняют, только подсвечивают узлы на графе):
{view_catalog}

Правила:
- Если пользователь просит НАЙТИ / ПОКАЗАТЬ / ПОДСВЕТИТЬ / ВЫДЕЛИТЬ узлы \
(«найди всех Миш», «покажи организации») — это НЕ повод переспрашивать. \
Используй highlight_nodes с "query" (подстрока имени, регистр игнорируется) — \
система сама подсветит ВСЕ совпадения в срезе. Можно сузить по "type". Не \
выбирай один узел и не уточняй «кого именно» — подсвечивай все подходящие.
- Если пользователь ссылается на «их», «эти», «найденные», «подсвеченные» — \
это узлы из блока «Подсвечено сейчас» (результат прошлого поиска). Применяй \
операцию к каждому из них (например, слить всех в один survivor, удалить всех).
- Для мутаций используй ТОЛЬКО id из блока КОНТЕКСТ; не выдумывай id. Если цель \
мутации не найдена — верни пустой "ops" и переспроси в "message".
- Минимум операций. Тип в retype_node бери из существующих, если есть \
синонимичный (например «организация» → ORG).
- "message" — короткий ответ на языке пользователя: что ты делаешь.

Ответ — СТРОГО JSON-объект:
{{"message": "<ответ>", "ops": [<операция>, ...]}}\
"""


class PlannedOp(DomainModel):
    op: JournalOp
    payload: dict[str, Any]


class AssistantPlan(DomainModel):
    message: str
    ops: list[PlannedOp]
    highlight: list[str] = []
    """Node ids the assistant wants lit up on the graph (read-only — from
    highlight_nodes view actions). Resolved server-side against the slice."""


class CurationAssistant:
    """Stateless LLM planner. Construct with a CompletionClient (the route
    passes the registered default — Deepseek; tests pass a fake)."""

    def __init__(self, llm: CompletionClient) -> None:
        self._llm = llm

    async def plan(
        self,
        state: GraphBuildState,
        *,
        message: str,
        selected_node_ids: list[str] | None = None,
        slice_node_ids: list[str] | None = None,
        highlighted_node_ids: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
        max_context_nodes: int = 400,
    ) -> AssistantPlan:
        # "Текущий срез" = the nodes visible on screen (temporal window etc.).
        # Search/highlight is scoped to it; absent → the whole graph.
        slice_set = {str(s) for s in slice_node_ids} if slice_node_ids else None
        slice_nodes = (
            [n for n in state.nodes if str(n.id) in slice_set]
            if slice_set is not None
            else state.nodes
        )
        hl_set = {str(h) for h in highlighted_node_ids or []}
        highlighted = [n for n in state.nodes if str(n.id) in hl_set]
        context = build_graph_context(
            state,
            selected_node_ids=selected_node_ids or [],
            mentioned=_mentioned_nodes(message, slice_nodes),
            highlighted=highlighted,
            slice_nodes=slice_nodes,
            in_slice=slice_set is not None,
            max_nodes=max_context_nodes,
        )
        name_to_id = _name_index(state.nodes)

        messages: list[Message] = [
            Message(
                role="system",
                content=_SYSTEM_PROMPT.format(
                    catalog="\n".join(f"- {v}" for v in _OP_CATALOG.values()),
                    view_catalog="\n".join(f"- {v}" for v in _VIEW_CATALOG.values()),
                ),
            )
        ]
        for turn in history or []:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append(Message(role=role, content=content))  # type: ignore[arg-type]
        messages.append(
            Message(role="user", content=f"КОНТЕКСТ:\n{context}\n\nЗАДАЧА: {message}")
        )

        result = await self._llm.complete(
            messages,
            CompletionParams(
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"},
            ),
        )
        parsed = _extract_json(result.text)
        if not isinstance(parsed, dict):
            return AssistantPlan(message=_FALLBACK_MSG, ops=[])

        reply = str(parsed.get("message") or "").strip() or _FALLBACK_MSG
        raw_ops = parsed.get("ops")
        ops: list[PlannedOp] = []
        highlight: set[str] = set()
        if isinstance(raw_ops, list):
            for raw in raw_ops:
                if isinstance(raw, dict) and raw.get("op") in _VIEW_CATALOG:
                    highlight |= _resolve_highlight(raw, slice_nodes, name_to_id)
                    continue
                op = _validate_op(raw, name_to_id)
                if op is not None:
                    ops.append(op)
        return AssistantPlan(message=reply, ops=ops, highlight=sorted(highlight))


_FALLBACK_MSG = "Не удалось разобрать ответ модели. Уточни запрос."


def build_graph_context(
    state: GraphBuildState,
    *,
    selected_node_ids: list[str],
    mentioned: list[Node] | None = None,
    highlighted: list[Node] | None = None,
    slice_nodes: list[Node] | None = None,
    in_slice: bool = False,
    max_nodes: int = 400,
) -> str:
    """Compact, id-grounded view of the graph for the prompt: the selected
    node(s) and any node named in the instruction in full (so a big graph's
    400-row cap can't hide the target), the distinct entity types (so retype
    picks a real one), and a capped id|name|type|layer index to target by id.

    `slice_nodes` (when `in_slice`) scopes the listing/types to the nodes the
    user currently sees — the "текущий срез" — so highlight/search means
    "in what's on screen", not the whole graph."""
    nodes = slice_nodes if slice_nodes is not None else state.nodes
    selected = {str(s) for s in selected_node_ids}
    types = sorted({n.type for n in nodes if n.layer == Layer.ENTITY and n.type})

    lines: list[str] = []
    if in_slice:
        lines.append(f"Текущий срез: {len(nodes)} узлов видно.")
    if selected:
        lines.append("Выделено сейчас:")
        for n in nodes:
            if str(n.id) in selected:
                lines.append(
                    f"  • id={n.id} имя={n.name!r} тип={n.type} слой={n.layer.value}"
                    + (f" summary={n.summary[:120]!r}" if n.summary else "")
                )
    if highlighted:
        lines.append(
            "Подсвечено сейчас (результат прошлого поиска — это «их», «эти», "
            "«найденные»):"
        )
        for n in highlighted:
            lines.append(
                f"  • id={n.id} имя={n.name!r} тип={n.type} слой={n.layer.value}"
            )
    if mentioned:
        lines.append("Узлы, упомянутые в запросе:")
        for n in mentioned:
            lines.append(
                f"  • id={n.id} имя={n.name!r} тип={n.type} слой={n.layer.value}"
            )
    if types:
        lines.append(f"Существующие типы сущностей: {', '.join(types)}")

    sel_ids = selected
    inc = [
        e
        for e in state.edges
        if str(e.source_node_id) in sel_ids or str(e.target_node_id) in sel_ids
    ][:60]
    if inc:
        lines.append("Рёбра выделенных узлов:")
        for e in inc:
            lines.append(
                f"  • edge_id={e.id} {e.source_node_id}→{e.target_node_id}"
                f" тип={e.type.value}"
            )

    label = "Узлы среза" if in_slice else "Узлы"
    lines.append(f"{label} (id | имя | тип | слой), до {max_nodes}:")
    shown = sorted(nodes, key=lambda n: (n.layer.value, str(n.id)))[:max_nodes]
    for n in shown:
        lines.append(f"  {n.id} | {n.name} | {n.type} | {n.layer.value}")
    if len(nodes) > max_nodes:
        lines.append(f"  …и ещё {len(nodes) - max_nodes} узлов (сузь запрос)")
    return "\n".join(lines)


def _resolve_highlight(
    raw: dict[str, Any], slice_nodes: list[Node], name_to_id: dict[str, str]
) -> set[str]:
    """Expand a highlight_nodes view action to concrete node ids, scoped to the
    slice: explicit node_ids (names resolved) plus every node whose name
    contains `query` (case-insensitive), optionally filtered by `type`. This is
    the 'find all the Mishas' path — match many, never disambiguate."""
    in_slice = {str(n.id) for n in slice_nodes}
    valid_ids = set(name_to_id.values())
    out: set[str] = set()

    for v in raw.get("node_ids") or []:
        rid = _resolve_id(v, name_to_id, valid_ids)
        if isinstance(rid, str) and rid in in_slice:
            out.add(rid)

    query = str(raw.get("query") or "").strip().lower()
    type_f = str(raw.get("type") or "").strip().lower()
    if query or type_f:
        for n in slice_nodes:
            name_ok = query in (n.name or "").lower() if query else True
            type_ok = (n.type or "").lower() == type_f if type_f else True
            if name_ok and type_ok:
                out.add(str(n.id))
    return out


def _mentioned_nodes(message: str, nodes: list[Node], cap: int = 40) -> list[Node]:
    """Nodes whose name the user actually typed — guaranteed into the context
    even on a graph too big to list whole. Single-token names match a token
    exactly (so "Да" matches the node, not the "да" inside "удали"); multi-word
    names match as a phrase substring."""
    low = message.lower()
    toks = set(re.findall(r"[\w\-]+", low))
    out: list[Node] = []
    seen: set[str] = set()
    for n in nodes:
        nm = (n.name or "").strip().lower()
        if not nm or str(n.id) in seen:
            continue
        if (nm in toks) or (" " in nm and nm in low):
            out.append(n)
            seen.add(str(n.id))
            if len(out) >= cap:
                break
    return out


def _name_index(nodes: list[Node]) -> dict[str, str]:
    """Case-insensitive name → id (first occurrence wins)."""
    idx: dict[str, str] = {}
    for n in nodes:
        key = (n.name or "").strip().lower()
        if key and key not in idx:
            idx[key] = str(n.id)
    return idx


def _resolve_id(value: Any, name_to_id: dict[str, str], valid_ids: set[str]) -> Any:
    """If the model put a real id, keep it. If it echoed a name, map it back."""
    if not isinstance(value, str):
        return value
    if value in valid_ids:
        return value
    return name_to_id.get(value.strip().lower(), value)


def _validate_op(raw: Any, name_to_id: dict[str, str]) -> PlannedOp | None:
    if not isinstance(raw, dict):
        return None
    op_name = raw.get("op")
    if op_name not in _OP_CATALOG:
        return None
    try:
        op = JournalOp(op_name)
    except ValueError:
        return None

    payload = {k: v for k, v in raw.items() if k != "op"}
    valid_ids = set(name_to_id.values())
    for f in _NODE_ID_FIELDS:
        if f in payload:
            payload[f] = _resolve_id(payload[f], name_to_id, valid_ids)
    for f in _NODE_ID_LIST_FIELDS:
        if isinstance(payload.get(f), list):
            payload[f] = [_resolve_id(v, name_to_id, valid_ids) for v in payload[f]]

    # Validate against the typed payload model; drop anything that doesn't fit.
    try:
        parse_payload(op, payload)
    except Exception:
        return None
    return PlannedOp(op=op, payload=payload)


def _extract_json(text: str) -> Any:
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
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
