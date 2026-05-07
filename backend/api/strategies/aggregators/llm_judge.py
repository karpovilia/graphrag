from __future__ import annotations

import statistics
from typing import Any

from api.llm import CompletionClient, CompletionParams, Message
from api.strategies.protocols import ExpertResult, ReasonResult
from api.strategies.registry import aggregators

_JUDGE_SYSTEM_PROMPT = """\
Ты — судья. Тебе подают вопрос и несколько ответов от разных экспертов \
по графу знаний. Твоя задача: дать один итоговый ответ на вопрос, \
опираясь на ответы экспертов. Если эксперты противоречат друг другу, \
выбери наиболее обоснованную версию и кратко объясни выбор.

Отвечай в стиле эксперта (без префиксов «Я выбрал»), на том же языке, \
что и вопрос. Если ни один из ответов не отвечает на вопрос — скажи об \
этом прямо.\
"""


@aggregators.register(
    "llm_judge",
    summary="Hand expert answers to an LLM and ask for one synthesized response.",
    description=(
        "Heaviest aggregator — one extra LLM call per MoE run. Best when "
        "experts disagree or when single-shot voting is too coarse. The "
        "evidence subgraph is the union of every expert's evidence; only "
        "the text answer is LLM-synthesized. Cost scales with the number "
        "of experts (each contributes a labeled block to the prompt)."
    ),
    params_schema={
        "max_tokens": {"type": "integer", "default": 800},
        "temperature": {"type": "number", "default": 0.0},
    },
    cost_hint="moderate",
    references=("docs/raw/2506.13782v1.pdf",),
)
class LLMJudge:
    """Stateful — needs a CompletionClient. The MoE orchestrator wires it
    in; tests pass a fake client.
    """

    def __init__(self, llm: CompletionClient) -> None:
        self._llm = llm

    async def aggregate(
        self,
        query: str,
        expert_results: list[ExpertResult],
        params: dict[str, Any],
    ) -> ReasonResult:
        usable = [r for r in expert_results if not r.error]
        if not usable:
            return ReasonResult(
                text="MoE aggregation: every expert failed.",
                confidence=0.0,
                metadata={"aggregator": "llm_judge", "failed_count": len(expert_results)},
            )

        max_tokens = int(params.get("max_tokens", 800))
        temperature = float(params.get("temperature", 0.0))

        prompt_blocks = [f"Вопрос: {query}", "", "Ответы экспертов:"]
        for r in usable:
            block = (
                f"--- эксперт {r.reasoner}@{r.variant_id} "
                f"(confidence={r.result.confidence}) ---\n"
                f"{r.result.text}"
            )
            prompt_blocks.append(block)
        prompt_blocks.append("")
        prompt_blocks.append("Дай один итоговый ответ.")

        completion = await self._llm.complete(
            [
                Message(role="system", content=_JUDGE_SYSTEM_PROMPT),
                Message(role="user", content="\n".join(prompt_blocks)),
            ],
            CompletionParams(temperature=temperature, max_tokens=max_tokens),
        )

        node_ids: set = set()
        edge_ids: set = set()
        for r in usable:
            node_ids.update(r.result.evidence_node_ids)
            edge_ids.update(r.result.evidence_edge_ids)

        confidences = [
            r.result.confidence for r in usable if r.result.confidence is not None
        ]
        return ReasonResult(
            text=completion.text.strip(),
            evidence_node_ids=sorted(node_ids, key=str),
            evidence_edge_ids=sorted(edge_ids, key=str),
            confidence=statistics.fmean(confidences) if confidences else None,
            cost_tokens=(completion.usage.total_tokens if completion.usage else 0)
            + sum(r.result.cost_tokens for r in usable),
            metadata={
                "aggregator": "llm_judge",
                "judge_model": completion.model,
                "expert_count": len(expert_results),
                "successful_expert_count": len(usable),
            },
        )
