from __future__ import annotations

from .base import CompletionClient, EmbeddingClient

_completion: dict[str, CompletionClient] = {}
_embedding: dict[str, EmbeddingClient] = {}
_default_completion: str | None = None
_default_embedding: str | None = None


def register_clients(
    completion: dict[str, CompletionClient] | None = None,
    embedding: dict[str, EmbeddingClient] | None = None,
    default_completion: str | None = None,
    default_embedding: str | None = None,
) -> None:
    """Register LLM clients at startup. Idempotent — re-registering a
    provider name overwrites the previous binding (used in tests).
    """

    global _default_completion, _default_embedding
    if completion:
        _completion.update(completion)
    if embedding:
        _embedding.update(embedding)
    if default_completion is not None:
        if default_completion not in _completion:
            raise KeyError(f"completion provider {default_completion!r} not registered")
        _default_completion = default_completion
    if default_embedding is not None:
        if default_embedding not in _embedding:
            raise KeyError(f"embedding provider {default_embedding!r} not registered")
        _default_embedding = default_embedding


def get_completion_client(provider: str | None = None) -> CompletionClient:
    name = provider or _default_completion
    if name is None:
        raise RuntimeError("no default completion provider registered")
    try:
        return _completion[name]
    except KeyError as e:
        raise KeyError(f"completion provider {name!r} not registered") from e


def get_embedding_client(provider: str | None = None) -> EmbeddingClient:
    name = provider or _default_embedding
    if name is None:
        raise RuntimeError("no default embedding provider registered")
    try:
        return _embedding[name]
    except KeyError as e:
        raise KeyError(f"embedding provider {name!r} not registered") from e


def reset() -> None:
    """Test helper. Don't call from prod code."""

    global _default_completion, _default_embedding
    _completion.clear()
    _embedding.clear()
    _default_completion = None
    _default_embedding = None
