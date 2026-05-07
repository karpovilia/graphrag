from __future__ import annotations

import pytest

import api.strategies.aggregators  # noqa: F401  — trigger @register
from api.domain.types import new_id
from api.llm import CompletionParams, CompletionResult, Message
from api.strategies.aggregators import EvidenceUnion, LLMJudge, WeightedVote
from api.strategies.protocols import ExpertResult, ReasonResult
from api.strategies.registry import aggregators


# ---- registry sanity ----


def test_aggregators_registered() -> None:
    names = aggregators.names()
    assert {"weighted_vote", "evidence_union", "llm_judge"}.issubset(set(names))


@pytest.mark.parametrize("cls", [WeightedVote, EvidenceUnion, LLMJudge])
def test_descriptors_present(cls) -> None:
    d = cls.descriptor
    assert d.kind == "aggregator"
    assert d.name in {"weighted_vote", "evidence_union", "llm_judge"}


# ---- helpers ----


def _expert(text: str, *, confidence: float | None, variant_id=None, error=None) -> ExpertResult:
    return ExpertResult(
        variant_id=variant_id or new_id(),
        reasoner="keyword_search",
        result=ReasonResult(
            text=text,
            confidence=confidence,
            evidence_node_ids=[new_id()],
        ),
        error=error,
    )


# ---- WeightedVote ----


async def test_weighted_vote_picks_highest_confidence() -> None:
    a = _expert("answer A", confidence=0.4)
    b = _expert("answer B", confidence=0.9)
    c = _expert("answer C", confidence=0.7)

    res = await WeightedVote().aggregate("q", [a, b, c], {})

    assert res.text == "answer B"
    assert res.metadata["aggregator"] == "weighted_vote"
    assert res.metadata["winning_score"] == 0.9
    assert len(res.metadata["all_scores"]) == 3


async def test_weighted_vote_uses_default_confidence_for_none() -> None:
    a = _expert("a", confidence=None)
    b = _expert("b", confidence=0.5)
    res = await WeightedVote().aggregate("q", [a, b], {"default_confidence": 0.9})
    assert res.text == "a"  # 0.9 default beats 0.5


async def test_weighted_vote_skips_failed_by_default() -> None:
    failed = _expert("dead", confidence=None, error="boom")
    ok = _expert("alive", confidence=0.3)
    res = await WeightedVote().aggregate("q", [failed, ok], {})
    assert res.text == "alive"


async def test_weighted_vote_all_failed_returns_zero_confidence() -> None:
    e = _expert("", confidence=None, error="boom")
    res = await WeightedVote().aggregate("q", [e, e], {})
    assert res.confidence == 0.0
    assert "every expert failed" in res.text.lower()


# ---- EvidenceUnion ----


async def test_evidence_union_concatenates_and_unions() -> None:
    a = _expert("про Иванова", confidence=0.8)
    b = _expert("про Петрова", confidence=0.6)
    res = await EvidenceUnion().aggregate("q", [a, b], {})

    assert "про Иванова" in res.text
    assert "про Петрова" in res.text
    assert res.metadata["successful_expert_count"] == 2
    # union of evidence nodes
    assert len(res.evidence_node_ids) == 2


async def test_evidence_union_drops_failed_unless_configured() -> None:
    a = _expert("ok", confidence=0.5)
    b = _expert("", confidence=None, error="timeout")
    res = await EvidenceUnion().aggregate("q", [a, b], {})
    assert "FAILED" not in res.text
    res2 = await EvidenceUnion().aggregate("q", [a, b], {"include_failed": True})
    assert "FAILED" in res2.text


async def test_evidence_union_no_blocks_returns_empty() -> None:
    res = await EvidenceUnion().aggregate("q", [], {})
    assert res.confidence == 0.0
    assert "no expert" in res.text.lower()


# ---- LLMJudge ----


class _FakeLLM:
    provider = "fake"
    default_model = "fake-judge"

    def __init__(self, text: str = "synthesized") -> None:
        self._text = text
        self.last_messages: list[Message] | None = None

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult:
        self.last_messages = list(messages)
        return CompletionResult(
            text=self._text,
            model=self.default_model,
            finish_reason="stop",
        )


async def test_llm_judge_calls_llm_with_expert_blocks() -> None:
    llm = _FakeLLM("Итоговый ответ.")
    a = _expert("Иванов работает в ВШЭ", confidence=0.8)
    b = _expert("Иванов руководит лабораторией", confidence=0.7)

    res = await LLMJudge(llm=llm).aggregate("Кто такой Иванов?", [a, b], {})

    assert res.text == "Итоговый ответ."
    assert llm.last_messages is not None
    user_msg = llm.last_messages[1].content
    assert "Иванов работает в ВШЭ" in user_msg
    assert "Иванов руководит лабораторией" in user_msg
    assert "Кто такой Иванов?" in user_msg
    assert res.metadata["aggregator"] == "llm_judge"
    assert res.metadata["successful_expert_count"] == 2


async def test_llm_judge_unions_evidence_from_experts() -> None:
    llm = _FakeLLM("X")
    a = _expert("a", confidence=0.5)
    b = _expert("b", confidence=0.5)
    res = await LLMJudge(llm=llm).aggregate("q", [a, b], {})
    assert len(res.evidence_node_ids) == 2  # both contributed unique node ids


async def test_llm_judge_all_failed_skips_llm() -> None:
    llm = _FakeLLM("should not see")
    e = _expert("", confidence=None, error="boom")
    res = await LLMJudge(llm=llm).aggregate("q", [e], {})
    assert llm.last_messages is None
    assert res.confidence == 0.0
