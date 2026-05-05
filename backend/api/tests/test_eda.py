from __future__ import annotations

from api.domain.types import new_id
from api.eda import EdaService, EntityMention, NerProtocol


class _FakeNer(NerProtocol):
    """Returns canned mentions per text. Lets us drive recommendation
    rules deterministically without natasha's News models.
    """

    def __init__(self, by_text: dict[str, list[EntityMention]]) -> None:
        self._by_text = by_text

    def extract(self, text: str) -> list[EntityMention]:
        return list(self._by_text.get(text, ()))


def _person(text: str, lemma: str, start: int = 0) -> EntityMention:
    return EntityMention(text=text, lemma=lemma, type="PER", start=start, end=start + len(text))


def _org(text: str, lemma: str, start: int = 0) -> EntityMention:
    return EntityMention(text=text, lemma=lemma, type="ORG", start=start, end=start + len(text))


def test_analyze_short_dense_corpus_picks_lightrag() -> None:
    text = "Иванов из ВШЭ работает с Петровым над проектом."
    mentions = [
        _person("Иванов", "иванов"),
        _person("Иванова", "иванов"),
        _person("Петров", "петров"),
        _person("Петрову", "петров"),
        _org("ВШЭ", "вшэ"),
    ]
    docs = [(new_id(), text) for _ in range(40)]  # short docs, dense
    svc = EdaService(ner=_FakeNer({text: mentions}))

    report = svc.analyze(corpus_id=new_id(), documents=docs)

    assert report.document_stats.document_count == 40
    assert report.recommendation.builder == "lightrag"
    assert "llm_dedup" in report.recommendation.cleaner_chain
    assert report.morphological_dispersion >= 1.5  # 2 forms per lemma in fixture


def test_analyze_long_corpus_picks_microsoft() -> None:
    text = "x" * 5000
    svc = EdaService(ner=_FakeNer({text: [_person("Иван", "иван")]}))

    report = svc.analyze(corpus_id=new_id(), documents=[(new_id(), text) for _ in range(3)])

    assert report.recommendation.builder == "microsoft"
    assert report.document_stats.median_chars == 5000


def test_node_types_surface_only_high_signal_labels() -> None:
    text = "doc"
    mentions = (
        [_person(f"Сидоров{i}", f"сидоров{i}") for i in range(5)]
        + [_org("ВШЭ", "вшэ")]
        + [_org("РАН", "ран")]
    )  # ORG has only 2 → below threshold of 3
    svc = EdaService(ner=_FakeNer({text: mentions}))

    report = svc.analyze(corpus_id=new_id(), documents=[(new_id(), text)])

    surfaced = {nt.name for nt in report.recommendation.node_types}
    assert "PERSON" in surfaced
    assert "ORG" not in surfaced  # below 3-mention threshold


def test_top_entities_descending() -> None:
    text = "x"
    mentions = (
        [_person("А", "а") for _ in range(5)]
        + [_person("Б", "б") for _ in range(3)]
        + [_org("В", "в") for _ in range(1)]
    )
    svc = EdaService(ner=_FakeNer({text: mentions}))

    report = svc.analyze(corpus_id=new_id(), documents=[(new_id(), text)])

    counts = [e.count for e in report.top_entities]
    assert counts == sorted(counts, reverse=True)


def test_empty_corpus_raises() -> None:
    import pytest

    svc = EdaService(ner=_FakeNer({}))
    with pytest.raises(ValueError):
        svc.analyze(corpus_id=new_id(), documents=[])


def test_morph_dispersion_low_for_unique_forms() -> None:
    text = "doc"
    mentions = [_person("Иван", "иван"), _person("Петр", "петр")]  # 1 form each
    svc = EdaService(ner=_FakeNer({text: mentions}))

    report = svc.analyze(corpus_id=new_id(), documents=[(new_id(), text)])

    assert report.morphological_dispersion == 1.0
    assert "llm_dedup" not in report.recommendation.cleaner_chain
