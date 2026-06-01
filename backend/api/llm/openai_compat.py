"""Ephemeral OpenAI-compatible completion client.

Used by the build wizard's "bring-your-own-token" flow: the user pastes
an api_key + base_url + model in the UI, and the route instantiates one
of these for the duration of a single build. Nothing is persisted —
credentials live in the call frame only.

Also works for local OpenAI-compatible servers (Ollama at
http://localhost:11434/v1, vLLM, llama.cpp's server, LM Studio, …).
For those, callers usually pass a dummy api_key like "ollama" — the
server ignores it but the OpenAI SDK insists on a non-empty value.
"""

from __future__ import annotations

from typing import Any

from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError as OpenAIRateLimitError,
)

from .base import (
    CompletionClient,
    CompletionParams,
    CompletionResult,
    CompletionUsage,
    LLMError,
    Message,
    RateLimitError,
)


class OpenAICompatClient(CompletionClient):
    """Wraps any OpenAI-compatible /v1/chat/completions endpoint.

    Single-build lifetime: do NOT cache instances. Credentials should
    never outlive the request that supplied them.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout_s: float = 120.0,
    ) -> None:
        self.provider = "openai_compat"
        self.default_model = default_model
        # The OpenAI SDK rejects "" — local servers don't actually
        # check the key, so any placeholder works.
        self._client = AsyncOpenAI(
            api_key=api_key or "sk-noop",
            base_url=base_url,
            timeout=timeout_s,
        )

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult:
        p = params or CompletionParams()
        model = p.model or self.default_model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "temperature": p.temperature,
            "max_tokens": p.max_tokens,
        }
        if p.response_format is not None:
            payload["response_format"] = p.response_format
        if p.seed is not None:
            payload["seed"] = p.seed
        if p.stop:
            payload["stop"] = p.stop
        payload.update(p.extra)

        try:
            resp = await self._client.chat.completions.create(**payload)
        except OpenAIRateLimitError as e:
            raise RateLimitError(str(e)) from e
        except (APIError, APITimeoutError) as e:
            raise LLMError(f"openai_compat: {e}") from e

        choice = resp.choices[0]
        usage = None
        if resp.usage is not None:
            usage = CompletionUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )
        return CompletionResult(
            text=choice.message.content or "",
            model=resp.model,
            finish_reason=choice.finish_reason,
            usage=usage,
        )
