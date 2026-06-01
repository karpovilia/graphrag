"""Schema proposer: one LLM pass over a sample of the corpus → draft
CorpusSchema (entity_types + relation_types with domain/range).

Used by the Schema Wizard step. The whole point of the schema is to
spend LLM budget once on a small sample to design a typed extraction
prompt, then run the *real* extraction with that prompt — instead of
spending LLM budget on chunk after chunk only to get a string-soup
ontology that mixes "команда Tele2" and "Tele2 KZ" (object) under
the same MISC bucket.

Sampling strategy: uniform random by chunk index, with a stable seed
so the proposal is reproducible. We deliberately sample chunks, not
documents — long documents would dominate otherwise and short notes
would be invisible to the proposer.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass

from loguru import logger

from api.domain.corpus import Document
from api.domain.schema import CorpusSchema, EntityTypeDef, RelationTypeDef
from api.llm import CompletionClient, CompletionParams, LLMError, Message
from api.strategies.builders._llm_extract import chunk_document

PROPOSE_SYSTEM_PROMPT = """\
Ты эксперт по построению онтологий из русскоязычных корпусов \
(переписка, заметки встреч, ТЗ, продуктовая документация).

Тебе дадут несколько фрагментов корпуса. Твоя задача — предложить \
типизированную онтологию для построения графа знаний. Онтология состоит \
из:

1. entity_types — типы сущностей. Имена в UPPER_SNAKE (например \
   TEAM_MEMBER, CLIENT, COMPONENT). Опиши, что относится к типу, и дай \
   2-4 примера дословных формулировок из текста.

2. relation_types — типы отношений с ДОМЕНОМ и РЕНДЖЕМ. Имя в \
   UPPER_SNAKE. domain и range — массивы entity_type-имён из (1); \
   они задают, какие типы могут стоять слева/справа от отношения. \
   Если отношение симметрично (A↔B как один факт) — symmetric=true.

ВАЖНО про relation_types — учти что корпус заметок встреч содержит \
ДВА класса отношений, оба нужны:

  а) ТЕХНИЧЕСКИЕ / структурные (как объекты связаны в системе): \
     WORKS_ON, INTEGRATES_WITH, USES, HAS_METRIC, DEPENDS_ON, \
     PROVIDES, MANAGES, AFFECTS — стандартный софт-арх-инвентарь.

  б) ДИСКУССИОННЫЕ / процессные (что происходит на встречах): \
     DISCUSSES, ANALYZES, REPORTS_ON, DECIDES_ABOUT, MENTIONS, \
     ESCALATES, COORDINATES_WITH, LAUNCHES, BLOCKED_BY, AUTOMATES. \
     Без них половина текста корпуса (обсуждения, акценты, анализы) \
     не покрывается онтологией и теряется при extraction.

Дай 10-18 relation_types — покрывая ОБА класса. Каждое имеет \
осмысленный domain/range, не «любая→любая». Включай ВСЕ дискуссионные \
типы из списка (б), если в тексте есть соответствующие глаголы.

Хорошая онтология:
- 6-12 entity_types
- 10-18 relation_types (технические + дискуссионные)
- Типы не пересекаются по смыслу

Возвращай СТРОГО JSON:
{
  "entity_types": [
    {"name": "TEAM_MEMBER",
     "description": "Сотрудник команды Афины (имена, фамилии, ники).",
     "examples": ["Иванов И.И.", "артемио", "Петров А."]}
  ],
  "relation_types": [
    {"name": "WORKS_ON",
     "description": "Сотрудник занимается компонентом или оффером.",
     "domain": ["TEAM_MEMBER"],
     "range":  ["COMPONENT", "OFFER"],
     "symmetric": false,
     "examples": ["Иванов И.И. — Phone-checker"]},
    {"name": "DISCUSSES",
     "description": "Сотрудник обсуждает что-либо на встрече.",
     "domain": ["TEAM_MEMBER"],
     "range":  ["COMPONENT", "OFFER", "TRIGGER", "METRIC"],
     "symmetric": false,
     "examples": ["Иванов И.И. — запуск оффера"]}
  ]
}
Не добавляй ничего вне JSON.\
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class _Chunk:
    document_title: str
    text: str


def _gather_chunks(
    documents: list[tuple[Document, str]],
    chunk_size: int,
    sample_size: int,
    seed: int,
) -> list[_Chunk]:
    """All chunks across all documents → uniform-random sample of
    sample_size. Stable seed."""

    out: list[_Chunk] = []
    for doc, text in documents:
        for _start, _end, ctext in chunk_document(text, size=chunk_size, overlap=0):
            out.append(_Chunk(document_title=doc.title, text=ctext))
    if not out:
        return []
    if sample_size >= len(out):
        return out
    rng = random.Random(seed)
    return rng.sample(out, sample_size)


def _format_sample(chunks: list[_Chunk]) -> str:
    blocks: list[str] = []
    for i, c in enumerate(chunks):
        blocks.append(f"--- фрагмент {i + 1} (документ: {c.document_title}) ---\n{c.text}")
    return "\n\n".join(blocks)


def _parse_proposal(text: str, *, proposed_by: str) -> CorpusSchema:
    if not text:
        return CorpusSchema(proposed_by=proposed_by)
    match = _JSON_RE.search(text)
    if not match:
        return CorpusSchema(proposed_by=proposed_by)
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("schema_proposer: bad JSON from LLM, returning empty schema")
        return CorpusSchema(proposed_by=proposed_by)
    if not isinstance(payload, dict):
        return CorpusSchema(proposed_by=proposed_by)

    entity_types: list[EntityTypeDef] = []
    for item in payload.get("entity_types") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            entity_types.append(
                EntityTypeDef(
                    name=name,
                    description=str(item.get("description") or "").strip(),
                    examples=[
                        str(x).strip()
                        for x in (item.get("examples") or [])
                        if x
                    ][:8],
                )
            )
        except Exception as e:
            logger.warning("schema_proposer: drop invalid entity_type {!r}: {}", name, e)

    valid_names = {t.name for t in entity_types}
    relation_types: list[RelationTypeDef] = []
    for item in payload.get("relation_types") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        # Drop domain/range refs that don't exist in entity_types so
        # the wizard isn't asked to fix dangling refs.
        domain = [
            d.upper().replace(" ", "_")
            for d in (item.get("domain") or [])
            if isinstance(d, str)
        ]
        range_ = [
            d.upper().replace(" ", "_")
            for d in (item.get("range") or [])
            if isinstance(d, str)
        ]
        domain = [d for d in domain if d in valid_names]
        range_ = [d for d in range_ if d in valid_names]
        try:
            relation_types.append(
                RelationTypeDef(
                    name=name,
                    description=str(item.get("description") or "").strip(),
                    domain=domain,
                    range=range_,
                    symmetric=bool(item.get("symmetric") or False),
                    examples=[
                        str(x).strip()
                        for x in (item.get("examples") or [])
                        if x
                    ][:5],
                )
            )
        except Exception as e:
            logger.warning("schema_proposer: drop invalid relation_type {!r}: {}", name, e)

    return CorpusSchema(
        entity_types=entity_types,
        relation_types=relation_types,
        proposed_by=proposed_by,
    )


async def propose_corpus_schema(
    *,
    documents: list[tuple[Document, str]],
    llm: CompletionClient,
    sample_size: int = 20,
    sample_chunk_size: int = 3000,
    seed: int = 42,
    max_tokens: int = 4000,
) -> CorpusSchema:
    """Sample the corpus, ask the LLM for an ontology proposal. The
    output is a *draft* — the wizard shows it for review/edit before
    the user commits with PUT /api/corpora/{id}/schema.

    Cost: one LLM call. Sample size of 20 × 3000 chars ≈ 15-20k tokens
    of input — comfortably inside Deepseek's context."""

    chunks = _gather_chunks(documents, sample_chunk_size, sample_size, seed)
    if not chunks:
        return CorpusSchema(proposed_by=f"llm:{llm.default_model}")
    logger.info(
        "schema_proposer: sampled {} chunks across {} documents",
        len(chunks),
        len(documents),
    )
    user_text = _format_sample(chunks)
    try:
        result = await llm.complete(
            [
                Message(role="system", content=PROPOSE_SYSTEM_PROMPT),
                Message(role="user", content=user_text),
            ],
            CompletionParams(
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            ),
        )
    except LLMError as e:
        logger.error("schema_proposer: LLM error {}", e)
        return CorpusSchema(proposed_by=f"llm:{llm.default_model}")
    return _parse_proposal(result.text, proposed_by=f"llm:{result.model}")
