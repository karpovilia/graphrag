from __future__ import annotations

import json

import pytest

from api.domain.corpus import Document
from api.domain.graph import EdgeType, Layer
from api.domain.types import Id, new_id
from api.eda.ner import EntityMention, NerProtocol
from api.llm import CompletionParams, CompletionResult, Message
from api.strategies.builders import (
    FastRAGBuilder,
    LightRAGBuilder,
    MicrosoftBuilder,
    NerExtractionBuilder,
    ToG3Builder,
)


class _FakeLLM:
    """Returns canned JSON extractions per call. Tests script the queue."""

    provider = "fake"
    default_model = "fake-1"

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Message]] = []

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult:
        self.calls.append(list(messages))
        if self._responses:
            payload = self._responses.pop(0)
        else:
            payload = {"entities": [], "relations": []}
        return CompletionResult(
            text=json.dumps(payload, ensure_ascii=False),
            model=self.default_model,
            finish_reason="stop",
        )


class _FakeNer(NerProtocol):
    def __init__(self, by_text: dict[str, list[EntityMention]]) -> None:
        self._by_text = by_text

    def extract(self, text: str) -> list[EntityMention]:
        return list(self._by_text.get(text, ()))


def _doc(corpus_id: Id, title: str = "doc") -> Document:
    return Document(
        corpus_id=corpus_id,
        title=title,
        char_length=42,
        sha256="0" * 64,
    )


def _person(text: str, lemma: str, start: int = 0) -> EntityMention:
    return EntityMention(
        text=text, lemma=lemma, type="PER", start=start, end=start + len(text)
    )


# ---- NerExtractionBuilder ----


async def test_ner_builder_produces_chunk_and_entity_layers() -> None:
    corpus_id = new_id()
    variant_id = new_id()
    text = "Иванов работает с Петровым во ВШЭ."
    doc = _doc(corpus_id)
    ner = _FakeNer(
        {
            text: [
                _person("Иванов", "иванов", start=0),
                _person("Петровым", "петров", start=18),
            ]
        }
    )

    state = await NerExtractionBuilder(ner=ner).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={"chunk_size": 1500},
    )

    chunks = [n for n in state.nodes if n.layer == Layer.CHUNK]
    entities = [n for n in state.nodes if n.layer == Layer.ENTITY]
    assert len(chunks) == 1
    assert len(entities) == 2
    assert {e.name for e in entities} == {"Иванов", "Петровым"}
    assert all(n.graph_variant_id == variant_id for n in state.nodes)


async def test_ner_builder_chunks_long_documents() -> None:
    corpus_id, variant_id = new_id(), new_id()
    text = "abc" * 1000  # 3000 chars
    doc = _doc(corpus_id)

    state = await NerExtractionBuilder(ner=_FakeNer({})).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={"chunk_size": 1000},
    )

    chunks = [n for n in state.nodes if n.layer == Layer.CHUNK]
    assert len(chunks) == 3
    spans = sorted((n.attributes["char_start"], n.attributes["char_end"]) for n in chunks)
    assert spans == [(0, 1000), (1000, 2000), (2000, 3000)]


async def test_ner_builder_dedups_entities_across_chunks() -> None:
    corpus_id, variant_id = new_id(), new_id()
    chunks_text = ["A", "B"]
    docs = [(_doc(corpus_id, title=f"d{i}"), chunks_text[i]) for i in range(2)]
    # Same lemma "иванов" surfaces in both texts → single Entity node.
    ner = _FakeNer(
        {
            "A": [_person("Иванов", "иванов")],
            "B": [_person("Иванова", "иванов")],
        }
    )

    state = await NerExtractionBuilder(ner=ner).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=docs,
        params={"chunk_size": 1500},
    )

    entities = [n for n in state.nodes if n.layer == Layer.ENTITY]
    assert len(entities) == 1
    # Mentioned-in edges fired for both occurrences.
    mentions = [e for e in state.edges if e.type == EdgeType.MENTIONED_IN]
    assert len(mentions) == 2


async def test_ner_builder_creates_cooccurrence_relations() -> None:
    corpus_id, variant_id = new_id(), new_id()
    text = "Иванов и Петров работают в ВШЭ."
    doc = _doc(corpus_id)
    ner = _FakeNer(
        {
            text: [
                _person("Иванов", "иванов"),
                _person("Петров", "петров"),
            ]
        }
    )

    state = await NerExtractionBuilder(ner=ner).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={"chunk_size": 1500},
    )

    relations = [e for e in state.edges if e.type == EdgeType.ENTITY_RELATION]
    assert len(relations) == 1
    assert relations[0].weight == 1.0
    assert relations[0].relation == "co_occurrence"


async def test_ner_builder_min_cooccurrence_filters_relations() -> None:
    corpus_id, variant_id = new_id(), new_id()
    chunks = ["A only", "A only", "A and B"]
    docs = [(_doc(corpus_id, title=f"d{i}"), chunks[i]) for i in range(3)]
    ner = _FakeNer(
        {
            "A only": [_person("Анна", "анна")],
            "A and B": [_person("Анна", "анна"), _person("Борис", "борис")],
        }
    )

    state = await NerExtractionBuilder(ner=ner).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=docs,
        params={"chunk_size": 1500, "min_cooccurrence": 2},
    )

    # Co-occurrence Анна+Борис happened once → below threshold of 2.
    relations = [e for e in state.edges if e.type == EdgeType.ENTITY_RELATION]
    assert relations == []


async def test_ner_builder_provenance_points_to_document() -> None:
    corpus_id, variant_id = new_id(), new_id()
    text = "Иванов"
    doc = _doc(corpus_id)
    ner = _FakeNer({text: [_person("Иванов", "иванов")]})

    state = await NerExtractionBuilder(ner=ner).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={"chunk_size": 1500},
    )

    chunk = next(n for n in state.nodes if n.layer == Layer.CHUNK)
    assert chunk.provenance and chunk.provenance[0].document_id == doc.id

    mention = next(e for e in state.edges if e.type == EdgeType.MENTIONED_IN)
    assert mention.provenance and mention.provenance[0].document_id == doc.id


def test_ner_builder_descriptor_metadata() -> None:
    d = NerExtractionBuilder.descriptor
    assert d.kind == "builder"
    assert d.name == "ner_extraction"
    assert Layer.CHUNK in d.produces_layers
    assert Layer.ENTITY in d.produces_layers
    assert d.cost_hint == "cheap"


# ---- LightRAGBuilder ----


async def test_lightrag_builder_extracts_entities_and_relations() -> None:
    corpus_id, variant_id = new_id(), new_id()
    text = "Иванов работает в ВШЭ над проектом Афина."
    doc = _doc(corpus_id)

    llm = _FakeLLM(
        [
            {
                "entities": [
                    {
                        "name": "Иванов",
                        "type": "PERSON",
                        "description": "ведущий инженер",
                        "local_keys": ["инженер", "руководитель"],
                        "global_keys": ["разработка"],
                    },
                    {
                        "name": "ВШЭ",
                        "type": "ORG",
                        "description": "университет",
                        "local_keys": ["вуз"],
                        "global_keys": ["образование"],
                    },
                ],
                "relations": [
                    {
                        "source": "Иванов",
                        "target": "ВШЭ",
                        "predicate": "работает в",
                        "description": "сотрудничает с университетом",
                    }
                ],
            }
        ]
    )

    state = await LightRAGBuilder(llm=llm).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={"chunk_size": 1500, "concurrency": 1},
    )

    chunks = [n for n in state.nodes if n.layer == Layer.CHUNK]
    entities = [n for n in state.nodes if n.layer == Layer.ENTITY]
    relations = [e for e in state.edges if e.type == EdgeType.ENTITY_RELATION]
    mentions = [e for e in state.edges if e.type == EdgeType.MENTIONED_IN]

    assert len(chunks) == 1
    assert {e.name for e in entities} == {"Иванов", "ВШЭ"}
    ivanov = next(e for e in entities if e.name == "Иванов")
    assert "инженер" in ivanov.attributes["local_keys"]
    assert "разработка" in ivanov.attributes["global_keys"]
    assert ivanov.summary == "ведущий инженер"
    assert len(relations) == 1
    assert relations[0].relation == "работает в"
    assert len(mentions) == 2  # one per entity, both in the single chunk


async def test_lightrag_builder_dedups_entities_across_chunks() -> None:
    corpus_id, variant_id = new_id(), new_id()
    # Two chunks (chunk_size=10 splits "abcdefghijklmnop" → 2 windows).
    doc = _doc(corpus_id, title="d")
    text = "abcdefghijklmnopqrstuvwxyz"

    llm = _FakeLLM(
        [
            {
                "entities": [
                    {"name": "Анна", "type": "PERSON", "local_keys": ["k1"]}
                ],
                "relations": [],
            },
            {
                "entities": [
                    {"name": "анна", "type": "PERSON", "local_keys": ["k2"]}
                ],
                "relations": [],
            },
            {"entities": [], "relations": []},  # extra slot for any 3rd chunk
        ]
    )

    state = await LightRAGBuilder(llm=llm).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={"chunk_size": 10, "chunk_overlap": 0, "concurrency": 1},
    )

    entities = [n for n in state.nodes if n.layer == Layer.ENTITY]
    assert len(entities) == 1
    # Both keys accumulated.
    assert {"k1", "k2"} <= set(entities[0].attributes["local_keys"])
    # Mentioned in both chunks.
    assert entities[0].attributes["mention_count"] == 2


async def test_lightrag_builder_max_chunks_caps_calls() -> None:
    corpus_id, variant_id = new_id(), new_id()
    doc = _doc(corpus_id)
    text = "x" * 5000  # 5 chunks at size=1000

    llm = _FakeLLM([])  # all calls fall back to empty extraction

    state = await LightRAGBuilder(llm=llm).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={"chunk_size": 1000, "max_chunks": 2, "concurrency": 1},
    )

    chunks = [n for n in state.nodes if n.layer == Layer.CHUNK]
    assert len(chunks) == 2
    assert len(llm.calls) == 2


# ---- MicrosoftBuilder ----


async def test_microsoft_builder_extracts_with_descriptions() -> None:
    corpus_id, variant_id = new_id(), new_id()
    text = "Совет директоров Альфа-Банка обсудил отчёт."
    doc = _doc(corpus_id)
    llm = _FakeLLM(
        [
            {
                "entities": [
                    {
                        "name": "Совет директоров",
                        "type": "ORG",
                        "description": "коллегиальный орган управления",
                    },
                    {
                        "name": "Альфа-Банк",
                        "type": "ORG",
                        "description": "коммерческий банк",
                    },
                ],
                "relations": [
                    {
                        "source": "Совет директоров",
                        "target": "Альфа-Банк",
                        "predicate": "управляет",
                        "description": "правление банка",
                        "weight": 5,
                    }
                ],
            },
            {"entities": [], "relations": []},  # gleaning pass — empty stop
        ]
    )

    state = await MicrosoftBuilder(llm=llm).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={
            "chunk_size": 1500,
            "extraction_max_gleanings": 1,
            "concurrency": 1,
        },
    )

    relations = [e for e in state.edges if e.type == EdgeType.ENTITY_RELATION]
    assert len(relations) == 1
    # Weight transform: stored = log1p(raw). raw lives in attributes so
    # the UI can still surface "5 mentions worth" separately.
    import math

    assert relations[0].weight == pytest.approx(math.log1p(5.0))
    assert relations[0].attributes["raw_weight"] == 5.0
    assert relations[0].explanation == "правление банка"
    # 1 main extraction + 1 empty gleaning that short-circuits before another.
    assert len(llm.calls) == 2


async def test_microsoft_builder_gleaning_merges_new_entities() -> None:
    corpus_id, variant_id = new_id(), new_id()
    text = "Один коротенький текст."
    doc = _doc(corpus_id)
    llm = _FakeLLM(
        [
            {
                "entities": [{"name": "Альфа", "type": "ORG"}],
                "relations": [],
            },
            {
                "entities": [
                    {"name": "Альфа", "type": "ORG"},  # duplicate — ignored
                    {"name": "Бета", "type": "ORG"},  # new — added
                ],
                "relations": [],
            },
        ]
    )

    state = await MicrosoftBuilder(llm=llm).build(
        graph_variant_id=variant_id,
        corpus_id=corpus_id,
        documents=[(doc, text)],
        params={
            "chunk_size": 1500,
            "extraction_max_gleanings": 1,
            "concurrency": 1,
        },
    )

    entities = sorted(
        (n for n in state.nodes if n.layer == Layer.ENTITY),
        key=lambda n: n.name,
    )
    assert [e.name for e in entities] == ["Альфа", "Бета"]
    assert len(llm.calls) == 2  # main + 1 gleaning


# ---- Stubs (still unwired) ----


@pytest.mark.parametrize(
    "cls,name",
    [
        (LightRAGBuilder, "lightrag"),
        (MicrosoftBuilder, "microsoft"),
        (ToG3Builder, "tog3"),
        (FastRAGBuilder, "fastrag"),
    ],
)
def test_builders_have_descriptors(cls, name) -> None:
    d = cls.descriptor
    assert d.kind == "builder"
    assert d.name == name
    assert d.produces_layers  # non-empty


@pytest.mark.parametrize(
    "cls",
    [ToG3Builder, FastRAGBuilder],
)
async def test_stub_builders_raise_not_implemented(cls) -> None:
    inst = cls()
    with pytest.raises(NotImplementedError):
        await inst.build(
            graph_variant_id=new_id(),
            corpus_id=new_id(),
            documents=[],
            params={},
        )
