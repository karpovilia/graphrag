from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EntityMention:
    """One NER hit. `lemma` is the canonicalized form (Russian: lemma);
    `type` follows natasha's News labels (PER / LOC / ORG) and is mapped
    to our NodeType later in `recommend.py`.
    """

    text: str
    lemma: str
    type: str
    start: int
    end: int


class NerProtocol(Protocol):
    """Stand-in so the EDA service can be unit-tested without pulling
    natasha's models. Real implementations: NatashaNer below."""

    def extract(self, text: str) -> list[EntityMention]: ...


class NatashaNer:
    """Russian-language NER + lemmatization via natasha NewsNERTagger.

    Heavy — loads News embeddings (~hundreds of MB) on first use. Not
    suitable for unit tests; use a fake NerProtocol there.
    """

    def __init__(self) -> None:
        # Imports are kept inside __init__ so importing the EDA module
        # at app startup doesn't pull in the natasha graph.
        from natasha import (
            Doc,
            MorphVocab,
            NewsEmbedding,
            NewsMorphTagger,
            NewsNERTagger,
            Segmenter,
        )

        self._Doc = Doc
        self._segmenter = Segmenter()
        self._morph_vocab = MorphVocab()
        self._emb = NewsEmbedding()
        self._morph_tagger = NewsMorphTagger(self._emb)
        self._ner_tagger = NewsNERTagger(self._emb)

    def extract(self, text: str) -> list[EntityMention]:
        if not text:
            return []
        doc = self._Doc(text)
        doc.segment(self._segmenter)
        doc.tag_morph(self._morph_tagger)
        doc.tag_ner(self._ner_tagger)

        mentions: list[EntityMention] = []
        for span in doc.spans:
            span.normalize(self._morph_vocab)
            mentions.append(
                EntityMention(
                    text=span.text,
                    lemma=(span.normal or span.text).lower(),
                    type=span.type,
                    start=span.start,
                    end=span.stop,
                )
            )
        return mentions
