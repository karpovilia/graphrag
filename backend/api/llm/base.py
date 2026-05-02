from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field

from api.domain.types import DomainModel

Role = Literal["system", "user", "assistant", "tool"]


class Message(DomainModel):
    role: Role
    content: str
    name: str | None = None


class CompletionParams(DomainModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, gt=0)
    response_format: dict[str, Any] | None = None
    """Provider-specific structured-output hint, e.g. {"type": "json_object"}."""

    model: str | None = None
    """Override the client's default model for this call only."""

    seed: int | None = None
    stop: list[str] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    """Provider-specific knobs that don't fit elsewhere — passed through verbatim."""


class CompletionUsage(DomainModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class CompletionResult(DomainModel):
    text: str
    model: str
    finish_reason: str | None = None
    usage: CompletionUsage | None = None


class LLMError(RuntimeError):
    """Provider-agnostic LLM failure. Concrete adapters wrap their SDK
    errors so call-sites never have to import provider packages.
    """


class RateLimitError(LLMError):
    """The provider rejected the call due to QPS / token-rate limits.

    Surfaced separately from generic LLMError because retry policy is
    different (back off on rate limit, fail fast on auth/server errors).
    """


@runtime_checkable
class CompletionClient(Protocol):
    provider: str
    default_model: str

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult: ...


@runtime_checkable
class EmbeddingClient(Protocol):
    provider: str
    default_model: str
    dim: int

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]: ...
