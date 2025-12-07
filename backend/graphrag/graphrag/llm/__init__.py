# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""The Datashaper OpenAI Utilities package."""

from .base import BaseLLM, CachingLLM, RateLimitingLLM
from .errors import RetriesExhaustedError
from .limiting import (
    CompositeLLMLimiter,
    LLMLimiter,
    NoopLLMLimiter,
    TpmRpmLLMLimiter,
    create_tpm_rpm_limiters,
)
from .mock import MockChatLLM, MockCompletionLLM
from .openai import (
    OpenAIChatLLM,
    OpenAIClientTypes,
    OpenAIConfiguration,
    create_openai_client,
)
from .types import (
    LLM,
    CompletionInput,
    CompletionLLM,
    CompletionOutput,
    EmbeddingInput,
    EmbeddingLLM,
    EmbeddingOutput,
    ErrorHandlerFn,
    IsResponseValidFn,
    LLMCache,
    LLMConfig,
    LLMInput,
    LLMInvocationFn,
    LLMInvocationResult,
    LLMOutput,
    OnCacheActionFn,
)

__all__ = [
    # LLM Types
    "LLM",
    "BaseLLM",
    "CachingLLM",
    "CompletionInput",
    "CompletionLLM",
    "CompletionOutput",
    "CompositeLLMLimiter",
    "EmbeddingInput",
    "EmbeddingLLM",
    "EmbeddingOutput",
    # Callbacks
    "ErrorHandlerFn",
    "IsResponseValidFn",
    # Cache
    "LLMCache",
    "LLMConfig",
    # LLM I/O Types
    "LLMInput",
    "LLMInvocationFn",
    "LLMInvocationResult",
    "LLMLimiter",
    "LLMOutput",
    "MockChatLLM",
    # Mock
    "MockCompletionLLM",
    "NoopLLMLimiter",
    "OnCacheActionFn",
    "OpenAIChatLLM",
    "OpenAIClientTypes",
    # OpenAI
    "OpenAIConfiguration",
    "RateLimitingLLM",
    # Errors
    "RetriesExhaustedError",
    "TpmRpmLLMLimiter",
    "create_openai_client",
    # Limiters
    "create_tpm_rpm_limiters",
]
