from __future__ import annotations

from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError as OpenAIRateLimitError

from .base import (
    CompletionClient,
    CompletionParams,
    CompletionResult,
    CompletionUsage,
    LLMError,
    Message,
    RateLimitError,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"


class DeepseekClient(CompletionClient):
    """Deepseek over its OpenAI-compatible REST endpoint.

    Stateless wrapper — one client per process is fine. Concurrency
    handled by the underlying httpx pool inside AsyncOpenAI.
    """

    provider = "deepseek"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEEPSEEK_BASE_URL,
        default_model: str = DEEPSEEK_DEFAULT_MODEL,
        timeout_s: float = 60.0,
    ) -> None:
        self.default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key,
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
            raise LLMError(f"deepseek: {e}") from e

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
