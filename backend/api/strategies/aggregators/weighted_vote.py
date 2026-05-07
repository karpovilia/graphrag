from __future__ import annotations

import statistics
from typing import Any

from api.strategies.protocols import ExpertResult, ReasonResult
from api.strategies.registry import aggregators


@aggregators.register(
    "weighted_vote",
    summary="Pick the highest-confidence expert; carry over its evidence.",
    description=(
        "Cheapest aggregator. Each ExpertResult contributes its "
        "confidence (default 1.0 when the expert reports None) as a "
        "weight; the expert with the highest weighted score wins. The "
        "winner's text and evidence_*_ids become the final answer; "
        "the loser metadata is preserved in result.metadata for the "
        "split-view UI."
    ),
    params_schema={
        "default_confidence": {
            "type": "number",
            "default": 1.0,
            "description": "Used when an expert reports confidence=None.",
        },
        "skip_failed": {
            "type": "boolean",
            "default": True,
            "description": "Drop expert results whose .error is set before voting.",
        },
    },
    cost_hint="cheap",
)
class WeightedVote:
    async def aggregate(
        self,
        query: str,
        expert_results: list[ExpertResult],
        params: dict[str, Any],
    ) -> ReasonResult:
        default_conf = float(params.get("default_confidence", 1.0))
        skip_failed = bool(params.get("skip_failed", True))

        usable = [
            r
            for r in expert_results
            if not (skip_failed and r.error)
        ]
        if not usable:
            return ReasonResult(
                text="MoE aggregation: every expert failed.",
                confidence=0.0,
                metadata={
                    "aggregator": "weighted_vote",
                    "expert_count": len(expert_results),
                    "failed_count": len(expert_results),
                },
            )

        scored = [
            ((r.result.confidence if r.result.confidence is not None else default_conf), r)
            for r in usable
        ]
        scored.sort(key=lambda kv: (-kv[0], str(kv[1].variant_id)))
        winning_score, winner = scored[0]

        return winner.result.model_copy(
            update={
                "metadata": {
                    **winner.result.metadata,
                    "aggregator": "weighted_vote",
                    "winning_variant_id": str(winner.variant_id),
                    "winning_reasoner": winner.reasoner,
                    "winning_score": winning_score,
                    "expert_count": len(expert_results),
                    "skipped_expert_count": len(expert_results) - len(usable),
                    "all_scores": [
                        {
                            "variant_id": str(r.variant_id),
                            "reasoner": r.reasoner,
                            "score": s,
                        }
                        for s, r in scored
                    ],
                }
            }
        )


def _mean_confidence(results: list[ExpertResult], default: float) -> float:
    """Helper used by other aggregators that want average expert confidence."""

    confidences = [
        r.result.confidence if r.result.confidence is not None else default
        for r in results
        if r.error is None
    ]
    return statistics.fmean(confidences) if confidences else 0.0
