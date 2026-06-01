"""Schema relabeler — retype an existing graph against a CorpusSchema.

Use case: a variant was built before the corpus had a schema, so its
entities carry open-vocab types (PERSON / ORG / CONCEPT / MISC) and its
relations carry free-form predicate strings ("обсуждал с", "запускает
оффер", "интегрируется через"). Re-extracting from scratch with the
schema would cost the full LLM budget over again; relabeling reuses the
extracted nodes and only asks the LLM to map (a) each distinct entity
to a schema entity_type, and (b) each distinct predicate string to a
schema relation_type.

Cost: ~3-5 min on a 20k-entity graph vs. ~100 min for a full re-extract.

The relabeler is pure-function-shaped: input = (existing nodes, edges,
schema, llm); output = (new nodes, new edges, mapping report). The
caller decides how to persist — overwrite the variant in-place, or
fork to a new one.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from api.domain.graph import Edge, EdgeType, Layer, Node
from api.domain.schema import CorpusSchema
from api.llm import CompletionClient, CompletionParams, LLMError, Message

DROP_TOKEN = "DROP"

ENTITY_RELABEL_SYSTEM = """\
Ты помощник по классификации. Дан JSON-массив сущностей графа знаний \
и список разрешённых типов с описаниями. Для каждой сущности верни \
один тип из списка, который ей подходит лучше всего.

Если ни один тип не подходит — верни "DROP".

ОТВЕТ — строго JSON-объект:
{"types": ["TYPE1", "TYPE2", "DROP", ...]}

Длина массива types ДОЛЖНА совпадать с длиной входного массива. \
Не возвращай ничего вне JSON.\
"""

RELATION_RELABEL_SYSTEM = """\
Ты помощник по канонизации предикатов. Тебе дают JSON-массив фраз-\
предикатов (русские глагольные обороты, могут быть с предлогами и \
дополнениями) и список разрешённых КАНОНИЧЕСКИХ типов отношений с \
описаниями.

Твоя задача — для КАЖДОЙ фразы найти БЛИЖАЙШИЙ канонический тип. \
Будь либеральным: фразы вроде «делает», «пилит», «занимается», \
«разрабатывает» — это всё WORKS_ON. «использует», «применяет», \
«берёт», «обращается к» — это USES. «зависит от», «требует», \
«нуждается в» — DEPENDS_ON. И так далее.

Возвращай "DROP" ТОЛЬКО когда фраза ЯВНО не описывает никакое из \
заданных отношений (например, бытовые предикаты «родился», «купил», \
«позавтракал» — таких в нормальных корпусах мало, но они бывают).

Игнорируй domain/range — они проверяются отдельно. Сосредоточься на \
семантике глагола.

ОТВЕТ — строго JSON-объект:
{"relations": ["TYPE1", "TYPE2", ...]}

Длина массива relations ДОЛЖНА совпадать с длиной входного массива. \
Не возвращай ничего вне JSON.\
"""


@dataclass
class RelabelReport:
    """Counts that tell the operator what changed."""

    entities_before: int = 0
    entities_after: int = 0
    entities_dropped: int = 0
    entity_type_distribution: dict[str, int] = field(default_factory=dict)
    relations_before: int = 0
    relations_after: int = 0
    relations_dropped_unmapped: int = 0
    relations_dropped_ill_typed: int = 0
    distinct_predicates_in: int = 0
    distinct_predicates_mapped: int = 0
    llm_calls: int = 0


def _format_entity_types_block(schema: CorpusSchema) -> str:
    lines = ["Разрешённые типы:"]
    for t in schema.entity_types:
        examples = ", ".join(t.examples[:3]) if t.examples else "—"
        desc = t.description or "(описание не задано)"
        lines.append(f"- {t.name}: {desc} Примеры: {examples}.")
    lines.append('- DROP: сущность не подходит ни под один тип.')
    return "\n".join(lines)


def _format_relation_types_block(schema: CorpusSchema) -> str:
    """Compact relation listing for the relabeling prompt — name +
    description only. We deliberately do NOT include domain/range here
    because LLMs trying to enforce them tend to mode-collapse into
    DROP. Domain/range is enforced separately by `apply_relabeling`
    via `schema.validate_triple()`."""

    lines = ["Канонические типы отношений (выбирай ОДИН для каждой фразы):"]
    for r in schema.relation_types:
        desc = r.description or "(описание не задано)"
        lines.append(f"- {r.name}: {desc}")
    lines.append(
        '- DROP: ТОЛЬКО если фраза совсем не похожа ни на одно из перечисленных.'
    )
    return "\n".join(lines)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_array(text: str, key: str) -> list[str]:
    if not text:
        return []
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        logger.warning(
            "relabeler: no JSON object in LLM reply ({} chars), padding with DROP",
            len(text),
        )
        return []
    try:
        payload = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        # Most common cause: the LLM hit max_tokens mid-array and
        # returned a truncated JSON. Try to salvage by finding the last
        # complete element via a forgiving regex over the array body.
        logger.warning(
            "relabeler: JSON decode error ({}); attempting salvage on {} chars",
            e,
            len(m.group(0)),
        )
        return _salvage_array(m.group(0), key)
    arr = payload.get(key)
    if not isinstance(arr, list):
        return []
    return [str(x).strip().upper() for x in arr]


_QUOTED_TOKEN_RE = re.compile(r'"([A-Z_]+)"')


def _salvage_array(text: str, key: str) -> list[str]:
    """When JSON is truncated, scrape the recognizable items out of the
    array literal so the run can still proceed. Looks for the `key`'s
    array opening, then extracts every quoted UPPER_SNAKE token until
    the truncation point."""

    idx = text.find(f'"{key}"')
    if idx == -1:
        return []
    arr_start = text.find("[", idx)
    if arr_start == -1:
        return []
    tail = text[arr_start:]
    return [tok.upper() for tok in _QUOTED_TOKEN_RE.findall(tail)]


def _batched(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _classify_batch(
    llm: CompletionClient,
    *,
    system: str,
    payload_obj: dict,
    response_key: str,
    expected_len: int,
    max_tokens: int = 1500,
) -> list[str]:
    try:
        result = await llm.complete(
            [
                Message(role="system", content=system),
                Message(
                    role="user",
                    content=json.dumps(payload_obj, ensure_ascii=False),
                ),
            ],
            CompletionParams(
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            ),
        )
    except LLMError as e:
        logger.warning("relabeler: LLM error ({}), batch fails closed (all DROP)", e)
        return [DROP_TOKEN] * expected_len

    out = _parse_array(result.text, response_key)
    # Defensive: enforce length match by padding/truncating; LLM
    # occasionally drifts on long arrays.
    if len(out) < expected_len:
        out = out + [DROP_TOKEN] * (expected_len - len(out))
    return out[:expected_len]


async def relabel_entities(
    entities: list[Node],
    schema: CorpusSchema,
    llm: CompletionClient,
    *,
    batch_size: int = 50,
    concurrency: int = 8,
) -> tuple[dict, RelabelReport]:
    """Return (entity_id → new_type | DROP, partial report).

    Example matching short-circuits the LLM for entities whose name is
    in any entity_type's examples list — that's deterministic and free.
    """

    allowed = set(schema.entity_type_names())
    if not allowed:
        return {}, RelabelReport(entities_before=len(entities))

    # 1. Examples-first deterministic mapping.
    example_to_type: dict[str, str] = {}
    for t in schema.entity_types:
        for ex in t.examples:
            example_to_type[ex.strip().lower()] = t.name

    mapping: dict[str, str] = {}
    needs_llm: list[Node] = []
    for n in entities:
        hit = example_to_type.get(n.name.strip().lower())
        if hit:
            mapping[str(n.id)] = hit
        else:
            needs_llm.append(n)

    logger.info(
        "relabel: {} entities → {} matched by examples, {} need LLM",
        len(entities),
        len(mapping),
        len(needs_llm),
    )

    # 2. LLM batches for the rest.
    types_block = _format_entity_types_block(schema)
    sem = asyncio.Semaphore(max(1, concurrency))
    batches = _batched(needs_llm, batch_size)
    llm_calls = 0
    llm_calls_lock = asyncio.Lock()

    async def _do_batch(idx: int, batch: list[Node]) -> None:
        nonlocal llm_calls
        async with sem:
            payload = {
                "types_catalog": types_block,
                "entities": [
                    {
                        "name": n.name,
                        "current_type": n.type,
                        "summary": (n.summary or "")[:200],
                    }
                    for n in batch
                ],
            }
            results = await _classify_batch(
                llm,
                system=ENTITY_RELABEL_SYSTEM,
                payload_obj=payload,
                response_key="types",
                expected_len=len(batch),
            )
            async with llm_calls_lock:
                llm_calls += 1
            for n, t in zip(batch, results):
                if t == DROP_TOKEN or t not in allowed:
                    mapping[str(n.id)] = DROP_TOKEN
                else:
                    mapping[str(n.id)] = t
            if idx % 5 == 0:
                logger.info("relabel entities: batch {}/{} done", idx + 1, len(batches))

    await asyncio.gather(*(_do_batch(i, b) for i, b in enumerate(batches)))

    report = RelabelReport(
        entities_before=len(entities),
        llm_calls=llm_calls,
    )
    return mapping, report


_PREDICATE_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_NATASHA_BUNDLE = None


def _natasha_bundle():
    """Lazy-load natasha's segmenter + tagger + morph-vocab. Bundles
    ~150MB of NewsEmbedding into RAM on first call. pymorphy2 doesn't
    work on Python 3.12 (relies on the removed `inspect.getargspec`),
    so we go via natasha instead — already a dep through EDA."""

    global _NATASHA_BUNDLE
    if _NATASHA_BUNDLE is None:
        from natasha import (
            Doc,
            MorphVocab,
            NewsEmbedding,
            NewsMorphTagger,
            Segmenter,
        )

        seg = Segmenter()
        morph_vocab = MorphVocab()
        emb = NewsEmbedding()
        tagger = NewsMorphTagger(emb)
        _NATASHA_BUNDLE = (seg, morph_vocab, tagger, Doc)
    return _NATASHA_BUNDLE


_PREDICATE_ROOT_CACHE: dict[str, str] = {}


def predicate_root(s: str) -> str:
    """Canonical key for grouping predicate strings.

    Strategy: natasha-tag the input → find the first VERB → return its
    lemma. Fallback to first NOUN lemma. Final fallback to the
    lowercased original (so weird tokens still get distinct keys
    instead of all collapsing to "").

    Cuts the distinct-predicate count by ~10-20x on afina ("анализирует
    доход", "анализирует прибыль", "анализирует расходы" all collapse
    to "анализировать"), which is what makes LLM-batch relabeling
    tractable: ~300 LLM-classifications cover thousands of predicate
    strings without mode-collapse."""

    cached = _PREDICATE_ROOT_CACHE.get(s)
    if cached is not None:
        return cached

    key = s.lower().strip()
    if not key:
        _PREDICATE_ROOT_CACHE[s] = key
        return key

    seg, morph_vocab, tagger, Doc = _natasha_bundle()
    doc = Doc(key)
    doc.segment(seg)
    doc.tag_morph(tagger)

    verb_lemma: str | None = None
    noun_lemma: str | None = None
    for tok in doc.tokens:
        tok.lemmatize(morph_vocab)
        if verb_lemma is None and tok.pos == "VERB":
            verb_lemma = tok.lemma
        elif noun_lemma is None and tok.pos == "NOUN":
            noun_lemma = tok.lemma

    root = verb_lemma or noun_lemma or key
    _PREDICATE_ROOT_CACHE[s] = root
    return root


async def relabel_relations(
    relation_strings: list[str],
    schema: CorpusSchema,
    llm: CompletionClient,
    *,
    batch_size: int = 30,
    concurrency: int = 8,
    max_tokens: int = 4000,
    use_lemmatization: bool = True,
) -> tuple[dict[str, str], int]:
    """Return ({raw_predicate_lowercased → schema_relation_name | DROP}, llm_calls).

    Operates on the *distinct lemmatized roots* of the predicate
    vocabulary, not per-string, so a graph with 6000+ distinct
    predicate surface forms (most are inflection variants) costs only
    ~10-20 LLM calls. The mapping is then expanded back to every
    surface form that shared a root.

    Set `use_lemmatization=False` to fall back to per-string
    classification (slower, more prone to mode-collapse, but doesn't
    need pymorphy2 — useful for non-Russian corpora)."""

    distinct_strings = sorted({p.strip() for p in relation_strings if p and p.strip()})
    if not distinct_strings or not schema.relation_types:
        return {}, 0

    # Map each string to its lemmatized root, then classify only the
    # distinct roots. The root list is *much* shorter — typically 300
    # roots for 6000 strings.
    string_to_root: dict[str, str] = {}
    root_to_strings: dict[str, list[str]] = {}
    if use_lemmatization:
        for s in distinct_strings:
            r = predicate_root(s)
            string_to_root[s] = r
            root_to_strings.setdefault(r, []).append(s)
        targets = sorted(root_to_strings.keys())
        logger.info(
            "relabel relations: {} strings → {} distinct lemma roots",
            len(distinct_strings),
            len(targets),
        )
    else:
        # Identity mapping — each string is its own "root".
        for s in distinct_strings:
            string_to_root[s] = s
            root_to_strings[s] = [s]
        targets = list(distinct_strings)

    rel_block = _format_relation_types_block(schema)
    sem = asyncio.Semaphore(max(1, concurrency))
    batches = _batched(targets, batch_size)
    root_mapping: dict[str, str] = {}
    llm_calls = 0
    llm_calls_lock = asyncio.Lock()
    allowed = {r.name for r in schema.relation_types}

    async def _do_batch(idx: int, batch: list[str]) -> None:
        nonlocal llm_calls
        async with sem:
            payload = {
                "relations_catalog": rel_block,
                "predicates": batch,
            }
            results = await _classify_batch(
                llm,
                system=RELATION_RELABEL_SYSTEM,
                payload_obj=payload,
                response_key="relations",
                expected_len=len(batch),
                max_tokens=max_tokens,
            )
            async with llm_calls_lock:
                llm_calls += 1
            for root, mapped in zip(batch, results):
                if mapped == DROP_TOKEN or mapped not in allowed:
                    root_mapping[root] = DROP_TOKEN
                else:
                    root_mapping[root] = mapped
            if idx % 5 == 0:
                logger.info(
                    "relabel predicates: batch {}/{} done", idx + 1, len(batches)
                )

    await asyncio.gather(*(_do_batch(i, b) for i, b in enumerate(batches)))

    # Expand the root-level mapping back to every surface form that
    # shared a root. `apply_relabeling` keys on lowercased raw strings.
    mapping: dict[str, str] = {}
    for root, surface_forms in root_to_strings.items():
        assigned = root_mapping.get(root, DROP_TOKEN)
        for s in surface_forms:
            mapping[s.lower()] = assigned

    logger.info(
        "relabel relations: {} roots classified ({} mapped, {} DROP), "
        "fanned out to {} surface forms",
        len(root_mapping),
        sum(1 for v in root_mapping.values() if v != DROP_TOKEN),
        sum(1 for v in root_mapping.values() if v == DROP_TOKEN),
        len(mapping),
    )
    return mapping, llm_calls


def apply_relabeling(
    nodes: list[Node],
    edges: list[Edge],
    entity_mapping: dict[str, str],
    relation_mapping: dict[str, str],
    schema: CorpusSchema,
    *,
    strict_domain_range: bool = False,
) -> tuple[list[Node], list[Edge], RelabelReport]:
    """Apply the (entity_id → new_type) and (predicate → relation_name)
    mappings to produce a new (nodes, edges) pair.

    Soft schema (default, `strict_domain_range=False`): entities NOT in
    the schema are dropped; relations NOT mapped to a schema predicate
    are dropped; relations mapped to a schema predicate but with
    endpoints that violate the relation's domain/range are KEPT and
    tagged `attributes.ill_typed=true`. Empirically the strict path
    drops ~30-40% of typed edges (e.g. COMPONENT-«анализирует»-OFFER
    is rejected because ANALYZES requires TEAM_MEMBER on the source),
    which loses too much signal for an open-vocab-extracted graph.

    Strict schema (`strict_domain_range=True`): ill-typed edges are
    also dropped. Useful when the consumer needs a guaranteed-valid
    ontology graph (e.g. a SPARQL-style reasoner)."""

    surviving_nodes: list[Node] = []
    type_dist: dict[str, int] = {}
    dropped_entity_ids: set = set()

    for n in nodes:
        if n.layer != Layer.ENTITY:
            surviving_nodes.append(n)
            continue
        new_type = entity_mapping.get(str(n.id))
        if new_type is None or new_type == DROP_TOKEN:
            dropped_entity_ids.add(n.id)
            continue
        surviving_nodes.append(
            n.model_copy(
                update={
                    "type": new_type,
                    "attributes": {
                        **n.attributes,
                        "previous_type": n.type,
                    },
                }
            )
        )
        type_dist[new_type] = type_dist.get(new_type, 0) + 1

    # Drop community / member_of touching dropped entities — they'll
    # be recomputed by re-running the clusterer downstream.
    surviving_nodes = [
        n
        for n in surviving_nodes
        if n.layer != Layer.COMMUNITY
    ]
    surviving_community_ids: set = set()  # all dropped, set is empty by design.

    node_by_id = {n.id: n for n in surviving_nodes}
    surviving_edges: list[Edge] = []
    rels_dropped_unmapped = 0
    rels_dropped_illtyped = 0
    relations_before = 0

    for e in edges:
        if e.source_node_id in dropped_entity_ids or e.target_node_id in dropped_entity_ids:
            continue
        if (
            e.type == EdgeType.MEMBER_OF
            or e.source_node_id in surviving_community_ids
            or e.target_node_id in surviving_community_ids
        ):
            # Drop all old community/member_of edges; clusterer rebuilds.
            continue
        if e.type != EdgeType.ENTITY_RELATION:
            # MENTIONED_IN and others pass through untouched (they don't
            # carry a schema-relation predicate).
            surviving_edges.append(e)
            continue

        relations_before += 1
        raw = (e.relation or "").strip().lower()
        new_pred = relation_mapping.get(raw)
        if new_pred is None or new_pred == DROP_TOKEN:
            rels_dropped_unmapped += 1
            continue

        # Validate domain/range against the schema using the entities'
        # new types. If the relation is symmetric, try the flipped
        # orientation. On mismatch: drop in strict mode, keep with
        # `attributes.ill_typed=true` in soft mode.
        src_node = node_by_id.get(e.source_node_id)
        tgt_node = node_by_id.get(e.target_node_id)
        if src_node is None or tgt_node is None:
            continue
        new_src_id = e.source_node_id
        new_tgt_id = e.target_node_id
        ill_typed = False
        if not schema.validate_triple(src_node.type, new_pred, tgt_node.type):
            rel = schema.lookup_relation(new_pred)
            if rel and rel.symmetric and schema.validate_triple(
                tgt_node.type, new_pred, src_node.type
            ):
                new_src_id, new_tgt_id = e.target_node_id, e.source_node_id
            elif strict_domain_range:
                rels_dropped_illtyped += 1
                continue
            else:
                ill_typed = True
                rels_dropped_illtyped += 1  # count for reporting; edge kept

        extra_attrs: dict = {
            **e.attributes,
            "previous_predicate": e.relation,
        }
        if ill_typed:
            extra_attrs["ill_typed"] = True
        surviving_edges.append(
            e.model_copy(
                update={
                    "relation": new_pred,
                    "source_node_id": new_src_id,
                    "target_node_id": new_tgt_id,
                    "attributes": extra_attrs,
                }
            )
        )

    report = RelabelReport(
        entities_before=len([n for n in nodes if n.layer == Layer.ENTITY]),
        entities_after=len([n for n in surviving_nodes if n.layer == Layer.ENTITY]),
        entities_dropped=len(dropped_entity_ids),
        entity_type_distribution=type_dist,
        relations_before=relations_before,
        relations_after=len([e for e in surviving_edges if e.type == EdgeType.ENTITY_RELATION]),
        relations_dropped_unmapped=rels_dropped_unmapped,
        relations_dropped_ill_typed=rels_dropped_illtyped,
        distinct_predicates_in=len(set(
            (e.relation or "").strip().lower()
            for e in edges
            if e.type == EdgeType.ENTITY_RELATION
        )),
        distinct_predicates_mapped=sum(
            1 for v in relation_mapping.values() if v != DROP_TOKEN
        ),
    )
    return surviving_nodes, surviving_edges, report
