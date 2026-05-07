"""Aggregator plugins for MoE reasoning.

Importing this package registers every aggregator under the "aggregator"
kind so /api/aggregators surfaces the wizard cards.
"""

from .evidence_union import EvidenceUnion
from .llm_judge import LLMJudge
from .weighted_vote import WeightedVote

__all__ = ["EvidenceUnion", "LLMJudge", "WeightedVote"]
