from __future__ import annotations

import pytest

from api.domain.corpus import Document
from api.domain.graph import EdgeType, Layer
from api.domain.types import Id, new_id
from api.eda.ner import EntityMention, NerProtocol
from api.strategies.builders import (
    FastRAGBuilder,
    LightRAGBuilder,
    MicrosoftBuilder,
    NerExtractionBuilder,
    ToG3Builder,
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


# ---- Stubs ----


@pytest.mark.parametrize(
    "cls,name",
    [
        (MicrosoftBuilder, "microsoft"),
        (LightRAGBuilder, "lightrag"),
        (ToG3Builder, "tog3"),
        (FastRAGBuilder, "fastrag"),
    ],
)
def test_stub_builders_have_descriptors(cls, name) -> None:
    d = cls.descriptor
    assert d.kind == "builder"
    assert d.name == name
    assert d.produces_layers  # non-empty


@pytest.mark.parametrize(
    "cls",
    [MicrosoftBuilder, LightRAGBuilder, ToG3Builder, FastRAGBuilder],
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
