from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from api.domain.graph import Layer
from api.domain.types import DomainModel

Kind = Literal[
    "builder",
    "cleaner",
    "clusterer",
    "summarizer",
    "reasoner",
    "agent",
    "tool",
    "aggregator",
]


class StrategyDescriptor(DomainModel):
    """Self-description of a registered strategy.

    Surfaced verbatim through /api/{kind}s so the wizard can render
    cards, forms, and the EDA-driven recommendation chips without
    duplicating metadata in the frontend.
    """

    kind: Kind
    name: str
    """Stable identifier — what users put in `cleaner_chain`, what the
    EDA recommender returns, what the orchestrator looks up. Lowercase
    snake_case by convention.
    """

    summary: str = ""
    """One-line UI hover text."""

    description: str = ""
    """Multi-paragraph long-form rationale, shown in the wizard card body."""

    requires_layers: tuple[Layer, ...] = ()
    """Layers that must already be populated in the input GraphVariant.
    Empty for top-of-pipeline builders."""

    produces_layers: tuple[Layer, ...] = ()
    """Layers the strategy emits or replaces. Validated by the
    orchestrator against the cleaner_chain — if a downstream stage
    requires a layer no upstream stage produces, the build is rejected
    before any LLM call."""

    params_schema: dict[str, Any] = Field(default_factory=dict)
    """JSON-schema-flavored param spec. Minimal in R2 — keys/types/defaults.
    The wizard renders a form from this; the backend validates."""

    cost_hint: Literal["cheap", "moderate", "expensive"] | None = None
    """Order-of-magnitude expectation. Cheap = no LLM; moderate = a few
    LLM calls; expensive = O(n) LLM calls in graph size. Used by the
    UI to gate batch operations and quotas in production (D1)."""

    references: tuple[str, ...] = ()
    """Optional pointers to docs/raw papers backing the design, e.g.
    ('docs/raw/2410.05779v3.pdf',). Surfaced in the wizard."""
