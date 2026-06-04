"""Think-on-Graph (ToG, ICLR 2024) — agentic beam search over the graph.

The LLM acts as an agent that, from keyword-seeded topic entities, iteratively
(1) explores+prunes the most relevant *relations* off each beam path's tail,
(2) explores+prunes the *entities* those relations lead to, extending the
reasoning paths, then (3) reasons whether the accumulated paths suffice to
answer — generating an answer when they do, else going one hop deeper (up to
`depth`). Beam width `width` keeps the top-N paths.

Faithful to the paper's two-step Search→Prune exploration; prune steps are
batched per hop (one LLM call each) to keep the call budget ~3·depth+1.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from api.domain.graph import EdgeType, Layer
from api.domain.types import DomainModel, Id
from api.llm import CompletionClient, CompletionParams, Message
from api.llm.registry import get_completion_client
from api.repository import NotFoundError, RepositoryProtocol
from api.runtime import get_repository
from api.strategies.reasoners.lightrag import _score, _tokenize


def _extract_json(text: str) -> Any:
    """Tolerant JSON parse (handles ```json fences / leading prose)."""
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
        start, end = s.find("{"), s.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None

router = APIRouter(prefix="/api", tags=["tog"])


def _tog_llm() -> CompletionClient | None:
    try:
        return get_completion_client()
    except (RuntimeError, KeyError):
        return None


class ToGRequest(DomainModel):
    query: str = Field(min_length=1)
    variant_ids: list[Id] = Field(default_factory=list)
    width: int = 3
    depth: int = 3
    top_k_seeds: int = 4
    max_relations: int = 20
    max_entities: int = 30


class ToGTriple(DomainModel):
    subject: str
    relation: str
    object: str


class ToGPath(DomainModel):
    triples: list[ToGTriple]
    score: float


class ToGResult(DomainModel):
    answer: str
    model: str
    sufficient: bool
    depth_reached: int
    llm_calls: int
    paths: list[ToGPath]
    evidence_node_ids: list[Id]
    evidence_edge_ids: list[Id]


# Internal beam path: a chain of entity nodes + the edges between them.
class _Path:
    __slots__ = ("nodes", "edges", "score", "_chosen_rels")

    def __init__(self, nodes: list[Any], edges: list[Any], score: float) -> None:
        self.nodes = nodes  # entity Node objects, head→tail
        self.edges = edges  # Edge objects between consecutive nodes
        self.score = score

    @property
    def tail(self) -> Any:
        return self.nodes[-1]

    def label(self) -> str:
        if not self.edges:
            return self.nodes[0].name
        parts = [self.nodes[0].name]
        for e, n in zip(self.edges, self.nodes[1:]):
            parts.append(f"-[{e.relation or e.type.value}]->{n.name}")
        return "".join(parts)


@router.post("/graphs/{variant_id}/tog", response_model=ToGResult)
async def think_on_graph(
    variant_id: Id,
    body: ToGRequest,
    repo: RepositoryProtocol = Depends(get_repository),
    llm: CompletionClient | None = Depends(_tog_llm),
) -> ToGResult:
    if llm is None:
        raise HTTPException(
            status_code=503, detail="no LLM provider configured — set DEEPSEEK__API_KEY"
        )
    vids = body.variant_ids or [variant_id]

    # Pool entity nodes + entity-relation adjacency across the chosen graphs.
    ents: dict[str, Any] = {}
    adj: dict[str, list[tuple[Any, Any]]] = defaultdict(list)  # node_id -> [(edge, neighbor)]
    for vid in vids:
        try:
            state = await repo.load_state(vid)
        except NotFoundError:
            continue
        by_id = {str(n.id): n for n in state.nodes}
        for n in state.nodes:
            if n.layer == Layer.ENTITY:
                ents.setdefault(str(n.id), n)
        for e in state.edges:
            if e.type != EdgeType.ENTITY_RELATION:
                continue
            s, t = str(e.source_node_id), str(e.target_node_id)
            ns, nt = by_id.get(s), by_id.get(t)
            if ns is not None and nt is not None:
                adj[s].append((e, nt))
                adj[t].append((e, ns))

    if not ents:
        raise HTTPException(status_code=409, detail="graph has no entity-relation structure")

    # Seed topic entities by keyword overlap with the question.
    tokens = _tokenize(body.query, 3)
    seeds = sorted(
        (n for n in ents.values() if _score(n, tokens, with_summary=False) > 0),
        key=lambda n: (-_score(n, tokens, with_summary=False), str(n.id)),
    )[: body.top_k_seeds]
    if not seeds:
        # fall back to a few arbitrary hubs so ToG can still explore
        seeds = sorted(ents.values(), key=lambda n: -len(adj[str(n.id)]))[: body.top_k_seeds]

    beam = [_Path([s], [], 1.0) for s in seeds]
    calls = 0
    sufficient = False
    answer = ""
    depth_reached = 0

    for d in range(body.depth):
        depth_reached = d + 1
        # ---- relation exploration (Search → Prune) ----
        beam, used = await _explore_relations(llm, body, beam, adj, ents)
        calls += used
        # ---- entity exploration (Search → Prune) ----
        beam, used = await _explore_entities(llm, body, beam, adj)
        calls += used
        if not beam:
            break
        # ---- reasoning: are the paths enough? ----
        verdict, used = await _reason(llm, body.query, beam)
        calls += used
        if verdict.get("sufficient"):
            sufficient = True
            answer = str(verdict.get("answer") or "").strip()
            break

    if not answer:
        gen, used = await _generate(llm, body.query, beam)
        calls += used
        answer = gen

    # Evidence = every node + edge on the surviving beam paths.
    ev_nodes: list[Id] = []
    ev_edges: list[Id] = []
    seen_n: set[str] = set()
    seen_e: set[str] = set()
    out_paths: list[ToGPath] = []
    for p in beam:
        for n in p.nodes:
            if str(n.id) not in seen_n:
                seen_n.add(str(n.id))
                ev_nodes.append(n.id)
        triples: list[ToGTriple] = []
        for e, a, b in zip(p.edges, p.nodes, p.nodes[1:]):
            if str(e.id) not in seen_e:
                seen_e.add(str(e.id))
                ev_edges.append(e.id)
            triples.append(
                ToGTriple(subject=a.name, relation=e.relation or e.type.value, object=b.name)
            )
        out_paths.append(ToGPath(triples=triples, score=p.score))

    model = getattr(llm, "default_model", "") or ""
    return ToGResult(
        answer=answer,
        model=model,
        sufficient=sufficient,
        depth_reached=depth_reached,
        llm_calls=calls,
        paths=out_paths,
        evidence_node_ids=ev_nodes,
        evidence_edge_ids=ev_edges,
    )


_PARAMS = CompletionParams(
    temperature=0.2,
    max_tokens=900,
    response_format={"type": "json_object"},
    extra={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
)


async def _explore_relations(
    llm: CompletionClient,
    body: ToGRequest,
    beam: list[_Path],
    adj: dict[str, list[tuple[Any, Any]]],
    ents: dict[str, Any],
) -> tuple[list[_Path], int]:
    """Search the relations off each path tail, then LLM-prune to the most
    relevant — recorded back onto each path as an allowed-relation set."""
    blocks = []
    rels_per_path: list[list[str]] = []
    for i, p in enumerate(beam):
        rels = sorted({e.relation or e.type.value for e, _ in adj[str(p.tail.id)]})
        rels = rels[: body.max_relations]
        rels_per_path.append(rels)
        if rels:
            blocks.append(f"Путь {i} (хвост: {p.tail.name}):\n  связи: {', '.join(rels)}")
    if not blocks:
        return beam, 0
    prompt = (
        f"Вопрос: {body.query}\n\n"
        "Для каждого пути выбери до "
        f"{body.width} связей, наиболее полезных, чтобы продвинуться к ответу.\n\n"
        + "\n".join(blocks)
        + '\n\nОтвет строго JSON: {"paths": {"<индекс пути>": ["<связь>", ...]}}'
    )
    out = await _chat(llm, prompt)
    chosen = (out or {}).get("paths") or {}
    # store chosen relations on each path (as an attribute via a parallel list)
    for i, p in enumerate(beam):
        keep = chosen.get(str(i)) or rels_per_path[i][: body.width]
        p._chosen_rels = {str(r).strip() for r in keep}  # type: ignore[attr-defined]
    return beam, 1


async def _explore_entities(
    llm: CompletionClient,
    body: ToGRequest,
    beam: list[_Path],
    adj: dict[str, list[tuple[Any, Any]]],
) -> tuple[list[_Path], int]:
    """Traverse the chosen relations to candidate entities, then LLM-prune to
    the top-N extended paths (the new beam)."""
    candidates: list[_Path] = []
    listing: list[str] = []
    idx = 0
    visited_per: list[tuple[int, _Path]] = []
    for p in beam:
        chosen = getattr(p, "_chosen_rels", set())
        on_path = {str(n.id) for n in p.nodes}
        seen_local: set[str] = set()
        for e, nb in adj[str(p.tail.id)]:
            rel = e.relation or e.type.value
            if chosen and rel not in chosen:
                continue
            if str(nb.id) in on_path or str(nb.id) in seen_local:
                continue
            seen_local.add(str(nb.id))
            cand = _Path(p.nodes + [nb], p.edges + [e], p.score)
            candidates.append(cand)
            listing.append(f"{idx}: {p.tail.name} -[{rel}]-> {nb.name}")
            visited_per.append((idx, cand))
            idx += 1
            if idx >= body.max_entities:
                break
        if idx >= body.max_entities:
            break
    if not candidates:
        return [], 0
    prompt = (
        f"Вопрос: {body.query}\n\n"
        "Ниже расширения путей рассуждения (новые шаги). Выбери до "
        f"{body.width} индексов, наиболее релевантных вопросу, и оцени 0..1.\n\n"
        + "\n".join(listing)
        + '\n\nОтвет строго JSON: {"keep": [{"index": <int>, "score": <0..1>}]}'
    )
    out = await _chat(llm, prompt)
    keep = (out or {}).get("keep") or []
    by_index = {c[0]: c[1] for c in visited_per}
    chosen_paths: list[_Path] = []
    for item in keep:
        try:
            ci = int(item.get("index"))
            sc = float(item.get("score", p.score))
        except (TypeError, ValueError, AttributeError):
            continue
        cp = by_index.get(ci)
        if cp is not None:
            cp.score = sc
            chosen_paths.append(cp)
    if not chosen_paths:
        chosen_paths = candidates[: body.width]
    chosen_paths.sort(key=lambda x: -x.score)
    return chosen_paths[: body.width], 1


async def _reason(
    llm: CompletionClient, query: str, beam: list[_Path]
) -> tuple[dict[str, Any], int]:
    paths_str = "\n".join(f"- {p.label()}" for p in beam)
    prompt = (
        f"Вопрос: {query}\n\nНайденные пути рассуждения по графу:\n{paths_str}\n\n"
        "Достаточно ли этих путей, чтобы ответить на вопрос? Если да — дай ответ.\n"
        'Ответ строго JSON: {"sufficient": true|false, "answer": "<ответ, если sufficient>"}'
    )
    out = await _chat(llm, prompt)
    return (out or {}), 1


async def _generate(
    llm: CompletionClient, query: str, beam: list[_Path]
) -> tuple[str, int]:
    paths_str = "\n".join(f"- {p.label()}" for p in beam) or "(пути не найдены)"
    prompt = (
        f"Вопрос: {query}\n\nПути по графу (возможно неполные):\n{paths_str}\n\n"
        "Ответь на вопрос, опираясь на эти пути; если данных не хватает — скажи об "
        'этом и ответь по тому, что есть. Строго JSON: {"answer": "<ответ>"}'
    )
    out = await _chat(llm, prompt)
    return str((out or {}).get("answer") or "").strip(), 1


async def _chat(llm: CompletionClient, prompt: str) -> dict[str, Any] | None:
    res = await llm.complete(
        [
            Message(role="system", content="Ты — агент рассуждения по графу знаний (Think-on-Graph). Отвечай строго JSON."),
            Message(role="user", content=prompt),
        ],
        _PARAMS,
    )
    parsed = _extract_json(res.text)
    return parsed if isinstance(parsed, dict) else None
