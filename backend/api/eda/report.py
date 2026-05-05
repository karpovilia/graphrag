from __future__ import annotations

from datetime import datetime

from pydantic import Field

from api.domain.types import DomainModel, Id, utcnow


class DocumentStats(DomainModel):
    """Length-distribution numbers used both for human display and for
    rule-based builder selection (short-chunk corpora prefer LightRAG,
    long-doc corpora prefer Microsoft GraphRAG).
    """

    document_count: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    mean_chars: float = Field(ge=0)
    median_chars: float = Field(ge=0)
    p95_chars: int = Field(ge=0)


class EntityFrequency(DomainModel):
    lemma: str
    type: str
    count: int = Field(ge=0)


class NodeTypeRecommendation(DomainModel):
    """A single suggested NodeType for the wizard.

    `evidence_count` is how many mentions natasha found in the EDA pass —
    it lets the UI rank suggestions by how grounded they are.
    """

    name: str
    label: str
    evidence_count: int = Field(ge=0)
    suggested_color: str | None = None


class Recommendation(DomainModel):
    """The actionable side of the report — what the wizard should
    pre-fill on the Builder/Cleaner/Clusterer steps.
    """

    builder: str
    cleaner_chain: list[str] = Field(default_factory=list)
    clusterer: str
    summarizer: str | None = None
    node_types: list[NodeTypeRecommendation] = Field(default_factory=list)
    rationale: str
    """Human-readable, shown next to the Apply button so the user knows
    why these defaults were picked.
    """


class EdaReport(DomainModel):
    id: Id
    corpus_id: Id
    created_at: datetime = Field(default_factory=utcnow)
    document_stats: DocumentStats
    entity_density_per_1k_chars: float = Field(ge=0)
    morphological_dispersion: float = Field(ge=0)
    """For Russian: mean number of distinct surface forms per lemma in
    the NER spans. > 1.5 hints heavy inflection — useful as the trigger
    for the LLMDeduplicator cleaner.
    """

    top_entities: list[EntityFrequency] = Field(default_factory=list)
    recommendation: Recommendation
