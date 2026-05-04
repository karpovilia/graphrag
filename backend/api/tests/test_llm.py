from __future__ import annotations

import pytest

from api.llm import (
    CompletionClient,
    CompletionParams,
    CompletionResult,
    Message,
    get_completion_client,
    register_clients,
)
from api.llm.registry import reset


class _RecordingClient:
    """Minimal fake CompletionClient for tests. Stores the last prompt
    so call-site tests can assert on what the strategy actually sent.
    """

    provider = "fake"
    default_model = "fake-1"

    def __init__(self) -> None:
        self.last_messages: list[Message] | None = None
        self.last_params: CompletionParams | None = None

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult:
        self.last_messages = list(messages)
        self.last_params = params
        return CompletionResult(text="ok", model=self.default_model, finish_reason="stop")


@pytest.fixture(autouse=True)
def _reset_registry():
    reset()
    yield
    reset()


async def test_registry_returns_default_provider() -> None:
    fake = _RecordingClient()
    register_clients(completion={"fake": fake}, default_completion="fake")
    client = get_completion_client()
    res = await client.complete([Message(role="user", content="ping")])
    assert res.text == "ok"
    assert fake.last_messages and fake.last_messages[0].content == "ping"


async def test_registry_returns_named_provider() -> None:
    fake = _RecordingClient()
    register_clients(completion={"fake": fake}, default_completion="fake")
    same = get_completion_client("fake")
    assert isinstance(same, CompletionClient)


def test_unknown_default_raises() -> None:
    with pytest.raises(KeyError):
        register_clients(completion={}, default_completion="missing")


def test_no_default_raises() -> None:
    with pytest.raises(RuntimeError):
        get_completion_client()


def test_completion_params_validation() -> None:
    p = CompletionParams(temperature=0.7, max_tokens=500)
    assert p.temperature == 0.7
    with pytest.raises(Exception):
        CompletionParams(temperature=3.0)
    with pytest.raises(Exception):
        CompletionParams(max_tokens=0)
