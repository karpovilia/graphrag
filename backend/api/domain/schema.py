"""Corpus-level ontology: entity types + typed relations.

The schema is what turns LLM extraction from a string-soup into a
typed knowledge graph: entity_types fix the vocabulary of node `.type`
values; relation_types fix the predicate vocabulary AND constrain
which types of entities can be source/target.

The wizard flow is:
  1. EDA report runs (rule-based, no LLM, no schema yet).
  2. User triggers schema proposal — LLM reads a sample of chunks
     and emits a draft CorpusSchema with entity + relation types,
     examples, domain/range. Saved to `Corpus.metadata.schema`.
  3. User reviews/edits the draft. Types the user removes will not
     be extracted by the builder; types the user keeps are baked
     into the extraction prompt.
  4. Build pipeline reads `Corpus.metadata.schema` and injects it
     into the builder's prompt. LightRAG and Microsoft are both
     schema-aware in hard mode — anything outside the schema is
     dropped at parse time.

Storage decision: live on `Corpus.metadata.schema` as plain JSON,
not a separate table. The schema is small (typically 5-15 entity
types + 5-15 relation types), it's tightly coupled to the corpus,
and it's rarely queried independently. A dedicated table would buy
nothing.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from .types import DomainModel


class EntityTypeDef(DomainModel):
    """One row of the entity-type ontology.

    The `name` is the canonical token the builder writes into
    `Node.type`. Keep it UPPER_SNAKE — that's what existing builders
    expect (PERSON, ORG, …) and what reasoners pattern-match on.
    """

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    """One short sentence. Goes verbatim into the extraction prompt so
    the LLM knows what *counts* as e.g. a CLIENT."""

    examples: list[str] = Field(default_factory=list)
    """Surface forms from the corpus. The LLM uses them as anchors."""

    suggested_color: str | None = None
    """Hex color for the layered viewer. Optional — frontend has a
    fallback palette."""

    @field_validator("name")
    @classmethod
    def _upper_snake(cls, v: str) -> str:
        # Normalize to UPPER_SNAKE so a user typing "team_member" or
        # "Team Member" still lands on TEAM_MEMBER. Forbid spaces in
        # the canonical name — they break the prompt template.
        cleaned = v.strip().replace(" ", "_").replace("-", "_")
        return cleaned.upper()


class RelationTypeDef(DomainModel):
    """One row of the relation ontology.

    `domain` and `range` constrain the typed shape of an edge:
    edges whose endpoints don't match are rejected at extraction
    time. Empty `domain`/`range` mean "any entity type" — useful
    for very generic relations like RELATED_TO, but the wizard
    discourages it.
    """

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    domain: list[str] = Field(default_factory=list)
    """List of EntityTypeDef.name values allowed at the edge source."""

    range: list[str] = Field(default_factory=list)
    """List of EntityTypeDef.name values allowed at the edge target."""

    symmetric: bool = False
    """True for relations like INTEGRATES_WITH: A→B is the same fact as
    B→A. The builder deduplicates undirected pairs in that case."""

    examples: list[str] = Field(default_factory=list)
    """Free-form "A — B" strings from the corpus."""

    @field_validator("name")
    @classmethod
    def _upper_snake(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "_").replace("-", "_")
        return cleaned.upper()


class CorpusSchema(DomainModel):
    """The full ontology for a corpus. Optional everywhere — corpora
    without a schema fall back to the old open-vocabulary extraction.
    """

    entity_types: list[EntityTypeDef] = Field(default_factory=list)
    relation_types: list[RelationTypeDef] = Field(default_factory=list)
    proposed_by: str | None = None
    """e.g. "llm:deepseek-chat" or "user". Audit trail for the
    /api/corpora/{id}/schema/history view (Phase 3)."""

    version: int = Field(default=1, ge=1)
    """User edits bump this; builders record the version in
    GraphVariant.config so re-extraction with a newer schema reads as
    a new run."""

    def entity_type_names(self) -> list[str]:
        return [t.name for t in self.entity_types]

    def relation_type_names(self) -> list[str]:
        return [t.name for t in self.relation_types]

    def lookup_relation(self, name: str) -> RelationTypeDef | None:
        norm = name.strip().upper()
        for r in self.relation_types:
            if r.name == norm:
                return r
        return None

    def validate_triple(
        self, source_type: str, predicate: str, target_type: str
    ) -> bool:
        """True if `(source_type) -[predicate]-> (target_type)` is
        consistent with the schema. Empty domain/range counts as "any".
        Used by builders in hard mode to drop ill-typed triples
        produced by the LLM.
        """

        rel = self.lookup_relation(predicate)
        if rel is None:
            return False
        if rel.domain and source_type.upper() not in {d.upper() for d in rel.domain}:
            return False
        if rel.range and target_type.upper() not in {d.upper() for d in rel.range}:
            return False
        return True
