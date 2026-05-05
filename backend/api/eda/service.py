from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable

from api.domain.types import Id, new_id

from .ner import EntityMention, NerProtocol
from .recommend import recommend
from .report import DocumentStats, EdaReport, EntityFrequency


class EdaService:
    """One-shot exploratory pass over a freshly uploaded corpus.

    Stateless — fed a NER backend at construction so tests can swap in
    a fake. The natasha-backed instance is heavy; create it once at
    startup and pass around.
    """

    def __init__(self, ner: NerProtocol, top_entities: int = 20) -> None:
        self._ner = ner
        self._top_entities = top_entities

    def analyze(
        self,
        corpus_id: Id,
        documents: Iterable[tuple[Id, str]],
    ) -> EdaReport:
        """`documents` is (document_id, text) pairs — kept loose so this
        works for both freshly uploaded files and rows already in PG.
        """

        lengths: list[int] = []
        all_mentions: list[EntityMention] = []
        forms_by_lemma: dict[str, set[str]] = defaultdict(set)

        for _doc_id, text in documents:
            lengths.append(len(text))
            mentions = self._ner.extract(text)
            for m in mentions:
                forms_by_lemma[(m.type, m.lemma)].add(m.text.lower())
            all_mentions.extend(mentions)

        if not lengths:
            raise ValueError("EdaService.analyze: corpus has no documents")

        total_chars = sum(lengths)
        document_stats = DocumentStats(
            document_count=len(lengths),
            total_chars=total_chars,
            mean_chars=statistics.fmean(lengths),
            median_chars=float(statistics.median(lengths)),
            p95_chars=int(_percentile(lengths, 0.95)),
        )

        entity_counts: Counter[tuple[str, str]] = Counter(
            (m.type, m.lemma) for m in all_mentions
        )
        top_entities = [
            EntityFrequency(lemma=lemma, type=etype, count=count)
            for (etype, lemma), count in entity_counts.most_common(self._top_entities)
        ]

        density = (
            len(all_mentions) / max(total_chars, 1) * 1000 if all_mentions else 0.0
        )

        if forms_by_lemma:
            dispersion = statistics.fmean(
                len(forms) for forms in forms_by_lemma.values()
            )
        else:
            dispersion = 0.0

        recommendation = recommend(
            document_stats=document_stats,
            mentions=all_mentions,
            morphological_dispersion=dispersion,
        )

        return EdaReport(
            id=new_id(),
            corpus_id=corpus_id,
            document_stats=document_stats,
            entity_density_per_1k_chars=density,
            morphological_dispersion=dispersion,
            top_entities=top_entities,
            recommendation=recommendation,
        )


def _percentile(xs: list[int], q: float) -> float:
    """Linear-interpolation percentile. statistics.quantiles wants n=100
    plus index math; this is shorter for one-off use."""

    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac
