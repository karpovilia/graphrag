from __future__ import annotations

from collections import Counter

from .ner import EntityMention
from .report import (
    DocumentStats,
    NodeTypeRecommendation,
    Recommendation,
)

# natasha News labels → human-friendly NodeType names. Open set — users
# can extend in the wizard.
NER_TO_NODE_TYPE = {
    "PER": ("PERSON", "Персоны"),
    "LOC": ("PLACE", "Места"),
    "ORG": ("ORG", "Организации"),
}

DEFAULT_TYPE_COLORS = {
    "PERSON": "#ff7f0e",
    "PLACE": "#2ca02c",
    "ORG": "#1f77b4",
}


def recommend(
    document_stats: DocumentStats,
    mentions: list[EntityMention],
    morphological_dispersion: float,
) -> Recommendation:
    """Rule-based picker that runs in milliseconds, no LLM. Rules:

    - **Builder.** Short docs + dense entities → LightRAG (its
      LLM-profiling-per-node costs less when there are many short
      mentions). Long docs (median > 4k chars) → Microsoft GraphRAG via
      our adapter (its hierarchical community summaries amortize over
      length). Default → Microsoft.
    - **Cleaner chain.** Always start with `threshold_prune` (cheap).
      Add `llm_dedup` when morphological dispersion is high (Russian
      inflection makes name fragmentation the #1 failure mode in the
      paper's case study 1).
    - **Clusterer.** Default Leiden. Stays the same regardless — we
      change clusterer in agent runs (CommunityStabilityScout), not
      EDA pre-fills.
    - **NodeTypes.** Surface every NER label we got at least 3 mentions
      of, in descending frequency order. No artificial cap — UI can
      paginate.
    """

    counts: Counter[str] = Counter(m.type for m in mentions)
    node_types = [
        NodeTypeRecommendation(
            name=NER_TO_NODE_TYPE.get(label, (label, label))[0],
            label=NER_TO_NODE_TYPE.get(label, (label, label))[1],
            evidence_count=count,
            suggested_color=DEFAULT_TYPE_COLORS.get(
                NER_TO_NODE_TYPE.get(label, (label,))[0]
            ),
        )
        for label, count in counts.most_common()
        if count >= 3
    ]

    short_docs = document_stats.median_chars <= 1500
    long_docs = document_stats.median_chars > 4000
    entity_density = (
        len(mentions) / max(document_stats.total_chars, 1) * 1000
    )
    dense_entities = entity_density > 5.0

    if short_docs and dense_entities:
        builder = "lightrag"
        builder_reason = (
            "короткие документы + плотный NER — LightRAG amortizes на "
            "много мелких сущностей"
        )
    elif long_docs:
        builder = "microsoft"
        builder_reason = (
            f"медианная длина {document_stats.median_chars:.0f} символов > 4k — "
            "иерархические community-summary Microsoft GraphRAG амортизируются"
        )
    else:
        builder = "microsoft"
        builder_reason = "корпус среднего размера — дефолтный Microsoft GraphRAG"

    cleaners = ["threshold_prune"]
    cleaner_reason_parts: list[str] = ["threshold_prune (всегда — дёшево)"]
    if morphological_dispersion >= 1.5:
        cleaners.append("llm_dedup")
        cleaner_reason_parts.append(
            f"llm_dedup (morph_dispersion={morphological_dispersion:.2f} ≥ 1.5 — "
            "русская морфология фрагментирует сущности)"
        )

    rationale = "\n".join(
        [
            f"Builder: {builder} — {builder_reason}.",
            f"Cleaner chain: {', '.join(cleaner_reason_parts)}.",
            "Clusterer: leiden — дефолт; альтернативы пробуем агентами.",
            f"NodeTypes: {len(node_types)} с ≥ 3 упоминаниями.",
        ]
    )

    return Recommendation(
        builder=builder,
        cleaner_chain=cleaners,
        clusterer="leiden",
        summarizer="microsoft",
        node_types=node_types,
        rationale=rationale,
    )
