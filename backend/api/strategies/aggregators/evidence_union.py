from __future__ import annotations

import statistics
from typing import Any

from api.strategies.protocols import ExpertResult, ReasonResult
from api.strategies.registry import aggregators


@aggregators.register(
    "evidence_union",
    summary="Concatenate expert answers + union their evidence subgraphs.",
    description=(
        "Conservative aggregator: keeps every expert's text (separated "
        "by per-variant headers) and unions evidence_node_ids and "
        "evidence_edge_ids. Confidence is the mean of per-expert "
        "confidences. Useful for the SIGIR demo split-view: the user "
        "sees what each expert said and can spot contradictions."
    ),
    params_schema={
        "separator": {
            "type": "string",
            "default": "\n\n---\n\n",
            "description": "Inserted between expert blocks in the merged text.",
        },
        "include_failed": {
            "type": "boolean",
            "default": False,
            "description": "Include error blurbs for failed experts.",
        },
    },
    cost_hint="cheap",
)
class EvidenceUnion:
    async def aggregate(
        self,
        query: str,
        expert_results: list[ExpertResult],
        params: dict[str, Any],
    ) -> ReasonResult:
        separator = str(params.get("separator", "\n\n---\n\n"))
        include_failed = bool(params.get("include_failed", False))

        blocks: list[str] = []
        node_ids: set = set()
        edge_ids: set = set()
        confidences: list[float] = []
        ok_count = 0
        cost_total = 0

        for r in expert_results:
            header = f"[{r.reasoner}@{r.variant_id}]"
            if r.error:
                if include_failed:
                    blocks.append(f"{header} FAILED: {r.error}")
                continue
            ok_count += 1
            blocks.append(f"{header}\n{r.result.text}".rstrip())
            node_ids.update(r.result.evidence_node_ids)
            edge_ids.update(r.result.evidence_edge_ids)
            cost_total += r.result.cost_tokens
            if r.result.confidence is not None:
                confidences.append(r.result.confidence)

        if not blocks:
            return ReasonResult(
                text="MoE aggregation: no expert produced output.",
                confidence=0.0,
                metadata={"aggregator": "evidence_union", "expert_count": 0},
            )

        return ReasonResult(
            text=separator.join(blocks),
            evidence_node_ids=sorted(node_ids, key=str),
            evidence_edge_ids=sorted(edge_ids, key=str),
            confidence=statistics.fmean(confidences) if confidences else None,
            cost_tokens=cost_total,
            metadata={
                "aggregator": "evidence_union",
                "expert_count": len(expert_results),
                "successful_expert_count": ok_count,
            },
        )
