"""Process-wide singletons that wire DI for strategies.

The orchestrator (and FastAPI routes) reach for these instead of
constructing heavy dependencies (natasha pipeline, LLM clients) on
every request. Lazy — first call pays the load cost, subsequent calls
reuse the same object.

Tests bypass this entirely: they instantiate strategies directly with
fake dependencies. Production startup wires the real ones via
api.__main__._wire_llm_clients and friends.
"""

from __future__ import annotations

from functools import lru_cache

from api.eda.ner import NatashaNer, NerProtocol
from api.llm import CompletionClient, get_completion_client


@lru_cache(maxsize=1)
def get_ner() -> NerProtocol:
    """First call loads News embeddings + tagger. Heavy; ≈ hundreds of
    MB resident. Shared across EDA and any NER-driven builder so the
    cost is paid once per process.
    """

    return NatashaNer()


def get_llm() -> CompletionClient:
    """Whatever provider the LLM gateway has registered as default —
    Deepseek in dev, Yandex when configured. Indirection so strategy
    factories don't import api.llm.registry directly.
    """

    return get_completion_client()
