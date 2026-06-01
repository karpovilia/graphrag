"""Shared LLM-extraction helpers for LightRAG / Microsoft builders.

Both builders walk a corpus chunk-by-chunk and ask an LLM for a
structured extraction of entities and relations. They differ in the
prompt (LightRAG asks for local/global keys, Microsoft asks for
descriptions + can do gleaning passes), but the chunking, JSON parsing,
and deduplication-by-name logic is identical — kept here so the two
builders stay thin.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from api.domain.corpus import Document
from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.schema import CorpusSchema
from api.domain.types import Id, Provenance
from api.llm import CompletionClient, CompletionParams, LLMError, Message

DEFAULT_ALLOWED_TYPES = ("PERSON", "ORG", "EVENT", "PLACE", "CONCEPT", "MISC")
"""Fallback ontology used when no CorpusSchema is supplied. Matches the
NER baseline so existing variants keep working unchanged."""


@dataclass
class ExtractedEntity:
    name: str
    type: str
    description: str = ""
    local_keys: list[str] = field(default_factory=list)
    global_keys: list[str] = field(default_factory=list)


@dataclass
class ExtractedRelation:
    source: str
    target: str
    predicate: str
    description: str = ""
    weight: float = 1.0


@dataclass
class ChunkExtraction:
    """One LLM call's output, normalized."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)


def chunk_document(
    text: str, *, size: int, overlap: int = 0
) -> list[tuple[int, int, str]]:
    """Split text into char-window chunks with optional overlap. Splits
    on byte boundaries — good enough for the demo, real production would
    use a token-aware splitter.
    """

    if not text:
        return []
    if size <= 0:
        size = 1500
    if overlap < 0 or overlap >= size:
        overlap = 0
    out: list[tuple[int, int, str]] = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + size, n)
        out.append((pos, end, text[pos:end]))
        if end >= n:
            break
        pos = end - overlap
    return out


def _normalize_entity_key(name: str, type_: str) -> tuple[str, str]:
    """Bucketing key for cross-chunk dedup. Lowercase + strip; no
    morphology — that's the LLMDeduplicator cleaner's job."""

    return (type_.upper().strip() or "MISC", name.strip().lower())


def _safe_type(t: str, *, allowed: tuple[str, ...] | None = None) -> str:
    """Normalize and validate against the active ontology. With no
    `allowed` set (open-vocab mode), only the DEFAULT_ALLOWED_TYPES are
    accepted and the rest collapse to MISC. With `allowed` (schema mode),
    only schema-defined types pass through; everything else is returned
    as the special sentinel "__OUT_OF_SCHEMA__" so callers can drop the
    extraction."""

    t = (t or "").upper().strip()
    if allowed is not None:
        return t if t in allowed else "__OUT_OF_SCHEMA__"
    return t if t in DEFAULT_ALLOWED_TYPES else "MISC"


OUT_OF_SCHEMA = "__OUT_OF_SCHEMA__"


# ---- prompts ----

_LIGHTRAG_SYSTEM = """\
Ты помощник, извлекающий граф знаний из русскоязычного текста.

Для каждой сущности из текста дай ДВА набора ключей:
- local_keys: 2-5 конкретных атрибутов/идентификаторов (имена, метрики, \
артефакты, проекты, инструменты, места).
- global_keys: 1-3 абстрактные темы / надпроблемы, к которым сущность \
относится.

Также выдели важные отношения между сущностями, которые видны в тексте.

Используй типы сущностей: PERSON, ORG, EVENT, PLACE, CONCEPT, MISC.

Возвращай СТРОГО JSON-объект:
{
  "entities": [
    {"name": "...", "type": "PERSON|ORG|EVENT|PLACE|CONCEPT|MISC",
     "description": "<1-2 предложения>",
     "local_keys": ["...", "..."],
     "global_keys": ["...", "..."]}
  ],
  "relations": [
    {"source": "<имя сущности>", "target": "<имя сущности>",
     "predicate": "<глагольное отношение>",
     "description": "<краткое объяснение>"}
  ]
}
Не добавляй ничего вне JSON.\
"""

_MICROSOFT_SYSTEM = """\
Ты помощник, извлекающий граф знаний из русскоязычного текста в стиле \
Microsoft GraphRAG.

Для каждой сущности дай: имя (как в тексте), тип, и 2-3 предложения с \
описанием (роль, контекст, особенности).

Для каждой пары связанных сущностей дай отношение с предикатом и кратким \
описанием доказательств в тексте; weight (1-10) отражает уверенность.

Используй типы: PERSON, ORG, EVENT, PLACE, CONCEPT, MISC.

Возвращай СТРОГО JSON:
{
  "entities": [
    {"name": "...", "type": "PERSON|ORG|EVENT|PLACE|CONCEPT|MISC",
     "description": "<2-3 предложения>"}
  ],
  "relations": [
    {"source": "...", "target": "...", "predicate": "<отношение>",
     "description": "<пояснение>", "weight": 1-10}
  ]
}
Не добавляй ничего вне JSON.\
"""

_GLEAN_SYSTEM = """\
Ты помощник по обогащению графа знаний. Тебе дан фрагмент текста и УЖЕ \
извлечённые сущности и отношения. Твоя задача — дополнить недостающее: \
сущности, которые были пропущены, и отношения между ними или с уже \
известными сущностями.

Возвращай СТРОГО JSON в той же схеме (entities + relations). Если \
ничего не пропущено — верни пустые массивы.\
"""


def _format_schema_for_prompt(schema: CorpusSchema) -> str:
    """Turn a CorpusSchema into the typed-vocabulary block that gets
    injected into the system prompt. The block lists every allowed
    entity_type with description+examples, then every relation_type
    with its domain/range and direction arrow.

    The LLM is told to *only* use these — anything outside the schema
    is dropped at parse time."""

    lines: list[str] = ["", "ИСПОЛЬЗУЙ ТОЛЬКО СЛЕДУЮЩИЕ ТИПЫ СУЩНОСТЕЙ:"]
    for t in schema.entity_types:
        examples = ", ".join(t.examples[:4]) if t.examples else "—"
        desc = t.description or "(описание не задано)"
        lines.append(f"- {t.name}: {desc} Примеры: {examples}.")

    if schema.relation_types:
        lines.append("")
        lines.append(
            "ИСПОЛЬЗУЙ ТОЛЬКО СЛЕДУЮЩИЕ ОТНОШЕНИЯ (стрелка = направление):"
        )
        for r in schema.relation_types:
            dom = " | ".join(r.domain) if r.domain else "*"
            rg = " | ".join(r.range) if r.range else "*"
            arrow = "↔" if r.symmetric else "→"
            desc = r.description or "(описание не задано)"
            lines.append(f"- {r.name} ({dom}) {arrow} ({rg}): {desc}")

    lines.append("")
    lines.append(
        "Если сущность не подходит ни под один тип — НЕ ИЗВЛЕКАЙ. "
        "Если отношение не подходит ни под один тип, или эндпоинты не "
        "удовлетворяют domain/range — НЕ ИЗВЛЕКАЙ."
    )
    return "\n".join(lines)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_extraction(
    text: str,
    *,
    schema: CorpusSchema | None = None,
) -> ChunkExtraction:
    """Pull the first JSON object from `text` and coerce to
    ChunkExtraction. Tolerant: bad JSON / missing fields → empty.

    When a schema is supplied: entities whose type isn't in the schema
    are dropped, and relations are dropped unless predicate ∈ schema
    AND endpoint types match the relation's domain/range. This is the
    "hard" schema mode — the prompt asks the LLM to obey, the parser
    enforces it on top in case the LLM cheats."""

    if not text:
        return ChunkExtraction()
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return ChunkExtraction()
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ChunkExtraction()
    if not isinstance(payload, dict):
        return ChunkExtraction()

    allowed_types: tuple[str, ...] | None = None
    allowed_rels: set[str] | None = None
    if schema is not None:
        allowed_types = tuple(schema.entity_type_names())
        allowed_rels = {r.name for r in schema.relation_types}

    entities: list[ExtractedEntity] = []
    # Track each entity's type so we can enforce domain/range on relations.
    entity_type_by_name: dict[str, str] = {}
    for item in payload.get("entities") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized_type = _safe_type(
            str(item.get("type") or ""), allowed=allowed_types
        )
        if normalized_type == OUT_OF_SCHEMA:
            continue
        ent = ExtractedEntity(
            name=name,
            type=normalized_type,
            description=str(item.get("description") or "").strip(),
            local_keys=[str(k).strip() for k in (item.get("local_keys") or []) if k],
            global_keys=[str(k).strip() for k in (item.get("global_keys") or []) if k],
        )
        entities.append(ent)
        entity_type_by_name[name.strip().lower()] = normalized_type

    relations: list[ExtractedRelation] = []
    for item in payload.get("relations") or []:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source") or "").strip()
        tgt = str(item.get("target") or "").strip()
        if not src or not tgt or src == tgt:
            continue
        predicate = str(item.get("predicate") or "связан").strip() or "связан"

        if schema is not None:
            # Predicate must be in schema (normalized to UPPER_SNAKE
            # to match how the schema stores names).
            norm_pred = predicate.upper().replace(" ", "_").replace("-", "_")
            if allowed_rels and norm_pred not in allowed_rels:
                continue
            predicate = norm_pred
            # Endpoint types must be known from the entities we kept
            # in this chunk + match relation's domain/range.
            src_type = entity_type_by_name.get(src.strip().lower())
            tgt_type = entity_type_by_name.get(tgt.strip().lower())
            if not src_type or not tgt_type:
                continue
            if not schema.validate_triple(src_type, predicate, tgt_type):
                # Try the symmetric flip — if the relation is symmetric
                # the LLM may have written the endpoints either way.
                rel = schema.lookup_relation(predicate)
                if rel and rel.symmetric and schema.validate_triple(
                    tgt_type, predicate, src_type
                ):
                    src, tgt = tgt, src
                else:
                    continue

        try:
            weight = float(item.get("weight") or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        relations.append(
            ExtractedRelation(
                source=src,
                target=tgt,
                predicate=predicate,
                description=str(item.get("description") or "").strip(),
                weight=max(0.1, weight),
            )
        )

    return ChunkExtraction(entities=entities, relations=relations)


async def extract_chunk(
    *,
    chunk_text: str,
    llm: CompletionClient,
    style: str,
    schema: CorpusSchema | None = None,
    gleanings: int = 0,
    max_tokens: int = 1500,
) -> ChunkExtraction:
    """Run the chosen extraction prompt on a single chunk. Returns an
    empty ChunkExtraction on LLM error rather than failing the whole
    build — extraction is best-effort, the orchestrator continues.

    When `schema` is supplied, the system prompt is augmented with the
    explicit entity/relation vocabulary and parse-stage filters drop
    anything outside it (hard schema mode)."""

    if style == "lightrag":
        base_system = _LIGHTRAG_SYSTEM
    elif style == "microsoft":
        base_system = _MICROSOFT_SYSTEM
    else:
        raise ValueError(f"unknown extraction style {style!r}")

    system = base_system
    if schema is not None and (schema.entity_types or schema.relation_types):
        system = base_system + "\n" + _format_schema_for_prompt(schema)

    messages = [
        Message(role="system", content=system),
        Message(role="user", content=chunk_text),
    ]
    try:
        result = await llm.complete(
            messages,
            CompletionParams(
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            ),
        )
    except LLMError as e:
        logger.warning("extract_chunk: LLM error ({}), skipping chunk", e)
        return ChunkExtraction()

    extraction = _parse_extraction(result.text, schema=schema)

    for _ in range(max(0, gleanings)):
        glean = await _glean(
            llm, chunk_text, extraction, max_tokens=max_tokens, schema=schema
        )
        if not glean.entities and not glean.relations:
            break
        # Merge: dedup entities by (type, name_lower); append new relations.
        seen = {_normalize_entity_key(e.name, e.type) for e in extraction.entities}
        for ent in glean.entities:
            if _normalize_entity_key(ent.name, ent.type) not in seen:
                extraction.entities.append(ent)
                seen.add(_normalize_entity_key(ent.name, ent.type))
        extraction.relations.extend(glean.relations)

    return extraction


async def _glean(
    llm: CompletionClient,
    chunk_text: str,
    so_far: ChunkExtraction,
    *,
    max_tokens: int,
    schema: CorpusSchema | None = None,
) -> ChunkExtraction:
    summary_payload = {
        "entities": [
            {"name": e.name, "type": e.type} for e in so_far.entities
        ],
        "relations": [
            {"source": r.source, "target": r.target, "predicate": r.predicate}
            for r in so_far.relations
        ],
    }
    user = (
        f"Уже извлечено:\n{json.dumps(summary_payload, ensure_ascii=False)}\n\n"
        f"Текст:\n{chunk_text}"
    )
    system = _GLEAN_SYSTEM
    if schema is not None and (schema.entity_types or schema.relation_types):
        system = _GLEAN_SYSTEM + "\n" + _format_schema_for_prompt(schema)
    try:
        result = await llm.complete(
            [
                Message(role="system", content=system),
                Message(role="user", content=user),
            ],
            CompletionParams(
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            ),
        )
    except LLMError as e:
        logger.warning("glean: LLM error ({}), skipping pass", e)
        return ChunkExtraction()
    return _parse_extraction(result.text, schema=schema)


# ---- pipeline glue: chunks → GraphBuildState ----


@dataclass
class _ChunkRef:
    document: Document
    char_start: int
    char_end: int
    text: str
    chunk_node: Node


async def run_extraction_pipeline(
    *,
    graph_variant_id: Id,
    documents: list[tuple[Document, str]],
    llm: CompletionClient,
    style: str,
    chunk_size: int,
    chunk_overlap: int = 0,
    gleanings: int = 0,
    concurrency: int = 4,
    max_chunks: int | None = None,
    max_entities_per_chunk: int | None = None,
    schema: CorpusSchema | None = None,
) -> tuple[list[Node], list[Edge]]:
    """Run the chosen extraction prompt over every chunk of every document
    and return CHUNK + ENTITY nodes plus MENTIONED_IN + ENTITY_RELATION
    edges. Cross-chunk entity dedup is done by case-insensitive (type, name).

    When `schema` is supplied, the LLM prompt is augmented with the
    typed vocabulary and parse-stage filters drop entities/relations
    outside it (hard schema mode)."""

    chunk_refs: list[_ChunkRef] = []
    for doc, text in documents:
        for cs, ce, ctext in chunk_document(text, size=chunk_size, overlap=chunk_overlap):
            chunk_node = Node(
                graph_variant_id=graph_variant_id,
                layer=Layer.CHUNK,
                type="CHUNK",
                granularity=0,
                name=_short_name(doc.title, cs),
                attributes={
                    "char_start": cs,
                    "char_end": ce,
                    "document_id": str(doc.id),
                },
                provenance=[
                    Provenance(
                        document_id=doc.id,
                        span_start=cs,
                        span_end=ce,
                    )
                ],
            )
            chunk_refs.append(
                _ChunkRef(
                    document=doc,
                    char_start=cs,
                    char_end=ce,
                    text=ctext,
                    chunk_node=chunk_node,
                )
            )

    if max_chunks is not None and max_chunks > 0:
        chunk_refs = chunk_refs[:max_chunks]

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_one(ref: _ChunkRef, idx: int) -> tuple[_ChunkRef, ChunkExtraction]:
        async with sem:
            if idx % 25 == 0:
                logger.info(
                    "extract[{}] chunk {}/{} (doc={})",
                    style,
                    idx + 1,
                    len(chunk_refs),
                    ref.document.title[:40],
                )
            extraction = await extract_chunk(
                chunk_text=ref.text,
                llm=llm,
                style=style,
                schema=schema,
                gleanings=gleanings,
            )
            return ref, extraction

    results = await asyncio.gather(
        *(_run_one(ref, i) for i, ref in enumerate(chunk_refs))
    )

    # ---- assemble nodes/edges ----

    chunk_nodes = [ref.chunk_node for ref in chunk_refs]
    entity_by_key: dict[tuple[str, str], Node] = {}
    # accumulate descriptions/keys across chunks so the final entity has
    # all context, not just the first occurrence.
    descriptions: dict[tuple[str, str], list[str]] = defaultdict(list)
    local_acc: dict[tuple[str, str], list[str]] = defaultdict(list)
    global_acc: dict[tuple[str, str], list[str]] = defaultdict(list)
    chunk_membership: dict[tuple[str, str], set[Id]] = defaultdict(set)
    relation_acc: dict[tuple[Id, Id, str], dict[str, Any]] = {}

    for ref, extraction in results:
        ents = extraction.entities
        if max_entities_per_chunk is not None and max_entities_per_chunk > 0:
            ents = ents[:max_entities_per_chunk]

        chunk_entity_ids: dict[str, Id] = {}  # raw_name -> entity Id

        for e in ents:
            # `e.type` is already validated by _parse_extraction (against
            # the schema if one was passed, else against DEFAULT_ALLOWED_TYPES).
            # No re-validation here.
            key = _normalize_entity_key(e.name, e.type)
            node = entity_by_key.get(key)
            if node is None:
                node = Node(
                    graph_variant_id=graph_variant_id,
                    layer=Layer.ENTITY,
                    type=e.type,
                    granularity=1,
                    name=e.name,
                    summary=e.description or None,
                    attributes={},
                )
                entity_by_key[key] = node
            chunk_entity_ids[e.name.strip().lower()] = node.id

            if e.description:
                descriptions[key].append(e.description)
            local_acc[key].extend(e.local_keys)
            global_acc[key].extend(e.global_keys)
            chunk_membership[key].add(ref.chunk_node.id)

        # relations
        for r in extraction.relations:
            src_id = chunk_entity_ids.get(r.source.strip().lower())
            tgt_id = chunk_entity_ids.get(r.target.strip().lower())
            if src_id is None or tgt_id is None or src_id == tgt_id:
                continue
            key_pair = (src_id, tgt_id, r.predicate)
            if key_pair[0] > key_pair[1]:
                # Stable orientation for undirected co-mention edges so we
                # don't keep both A→B and B→A from different chunks.
                key_pair = (key_pair[1], key_pair[0], r.predicate)
            entry = relation_acc.get(key_pair)
            if entry is None:
                relation_acc[key_pair] = {
                    "weight": float(r.weight),
                    "descriptions": [r.description] if r.description else [],
                    "count": 1,
                }
            else:
                entry["weight"] += float(r.weight)
                entry["count"] += 1
                if r.description:
                    entry["descriptions"].append(r.description)

    # finalize entity attributes
    for key, node in entity_by_key.items():
        local_keys = _dedup_keep_order(local_acc[key])
        global_keys = _dedup_keep_order(global_acc[key])
        descs = _dedup_keep_order(descriptions[key])
        if descs and not node.summary:
            node.summary = descs[0]
        node.attributes = {
            **node.attributes,
            "local_keys": local_keys[:10],
            "global_keys": global_keys[:5],
            "descriptions": descs[:5],
            "mention_count": len(chunk_membership[key]),
        }

    # build mention edges: one per (entity, chunk) pair seen
    mention_edges: list[Edge] = []
    for key, chunk_ids in chunk_membership.items():
        node = entity_by_key[key]
        for cid in chunk_ids:
            mention_edges.append(
                Edge(
                    graph_variant_id=graph_variant_id,
                    type=EdgeType.MENTIONED_IN,
                    source_node_id=node.id,
                    target_node_id=cid,
                )
            )

    # entity-relation edges: one per (a, b, predicate).
    # Weight transform: log1p(raw_sum) keeps a single dominant predicate
    # from drowning out the rest of the graph (Leiden weights would
    # otherwise route every community decision through one fat edge).
    # The raw sum is preserved in attributes so post-process or UI can
    # show "evidence strength" separately.
    import math

    relation_edges: list[Edge] = []
    for (a, b, predicate), agg in relation_acc.items():
        raw = float(agg["weight"])
        relation_edges.append(
            Edge(
                graph_variant_id=graph_variant_id,
                type=EdgeType.ENTITY_RELATION,
                source_node_id=a,
                target_node_id=b,
                weight=math.log1p(raw),
                relation=predicate,
                explanation=" / ".join(agg["descriptions"][:3]) or None,
                attributes={
                    "mentions": int(agg["count"]),
                    "raw_weight": raw,
                },
            )
        )

    nodes = chunk_nodes + list(entity_by_key.values())
    edges = mention_edges + relation_edges
    logger.info(
        "extract[{}]: {} chunks, {} entities, {} mention edges, {} relation edges",
        style,
        len(chunk_nodes),
        len(entity_by_key),
        len(mention_edges),
        len(relation_edges),
    )
    return nodes, edges


def _short_name(title: str, start: int) -> str:
    base = (title or "chunk").strip()
    return f"{base}@{start}"


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        norm = it.strip()
        if not norm:
            continue
        low = norm.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(norm)
    return out
