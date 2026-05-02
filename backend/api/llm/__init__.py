"""LLM gateway.

A thin abstraction so strategy plugins (builders, reasoners, agents) can
ask for a chat completion or an embedding without caring which provider
serves it. Default provider for development and CI is Deepseek; Yandex
remains as an opt-in adapter for production runs that need it.
"""

from .base import (
    CompletionClient,
    CompletionParams,
    CompletionResult,
    CompletionUsage,
    EmbeddingClient,
    LLMError,
    Message,
    RateLimitError,
    Role,
)
from .registry import get_completion_client, get_embedding_client, register_clients

__all__ = [
    "CompletionClient",
    "CompletionParams",
    "CompletionResult",
    "CompletionUsage",
    "EmbeddingClient",
    "LLMError",
    "Message",
    "RateLimitError",
    "Role",
    "get_completion_client",
    "get_embedding_client",
    "register_clients",
]
