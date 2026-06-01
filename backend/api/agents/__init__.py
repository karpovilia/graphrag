"""Curation agents.

Importing this package registers every agent below. Agents propose
Suggestions; they never mutate the graph. The orchestrator runs the
agent, persists Suggestions, and waits for the user to accept (which
the repository turns into a JournalEntry via the Phase 2 applier).
"""

from .community_stability import CommunityStabilityScout
from .entity_dedup import EntityDeduplicator
from .low_confidence_triplet import LowConfidenceTriplet
from .orphan_rescuer import OrphanRescuer
from .relation_consistency import RelationConsistencyChecker
from .similarity_merge_candidates import SimilarityMergeCandidates
from .topic_report_refresher import TopicReportRefresher

__all__ = [
    "CommunityStabilityScout",
    "EntityDeduplicator",
    "LowConfidenceTriplet",
    "OrphanRescuer",
    "RelationConsistencyChecker",
    "SimilarityMergeCandidates",
    "TopicReportRefresher",
]
