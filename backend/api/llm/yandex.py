from __future__ import annotations

import asyncio

import httpx
from yandex_cloud_ml_sdk import YCloudML

from .base import (
    CompletionClient,
    CompletionParams,
    CompletionResult,
    EmbeddingClient,
    LLMError,
    Message,
)


class YandexCompletionClient(CompletionClient):
    """YandexGPT chat completions through the official ML SDK.

    Refactored from the in-line client that used to live in
    backend/api/graphrag_processing.py. Kept as an opt-in adapter — not
    the default in R2 (Deepseek is). The SDK is sync, so each call is
    pushed to a thread.
    """

    provider = "yandex"

    def __init__(
        self,
        folder_id: str,
        token: str,
        default_model: str = "yandexgpt",
        default_model_version: str = "latest",
    ) -> None:
        self.default_model = default_model
        self._default_version = default_model_version
        self._sdk = YCloudML(folder_id=folder_id, auth=token)

    async def complete(
        self,
        messages: list[Message],
        params: CompletionParams | None = None,
    ) -> CompletionResult:
        p = params or CompletionParams()
        model_name = p.model or self.default_model
        model = self._sdk.models.completions(model_name, model_version=self._default_version)
        payload = [{"role": m.role, "text": m.content} for m in messages]

        def _call() -> tuple[str, str | None]:
            try:
                resp = model.run(payload)
            except Exception as e:
                raise LLMError(f"yandex: {e}") from e
            return resp[0].text, getattr(resp[0], "finish_reason", None)

        text, finish_reason = await asyncio.to_thread(_call)
        return CompletionResult(
            text=text,
            model=model_name,
            finish_reason=finish_reason,
            usage=None,
        )


class YandexEmbeddingClient(EmbeddingClient):
    """YandexGPT embeddings via REST. Pulled from the ad-hoc
    YandexGPTEmbeddingLLM that lived in graphrag_processing.py.
    """

    provider = "yandex"

    def __init__(
        self,
        folder_id: str,
        token: str,
        default_model: str = "text-search-query",
        dim: int = 256,
        timeout_s: float = 30.0,
    ) -> None:
        self._folder_id = folder_id
        self._token = token
        self.default_model = default_model
        self.dim = dim
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        model_name = model or self.default_model
        uri = f"emb://{self._folder_id}/{model_name}/latest"
        url = "https://llm.api.cloud.yandex.net:443/foundationModels/v1/textEmbedding"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
            "x-folder-id": self._folder_id,
        }
        out: list[list[float]] = []
        for text in texts:
            resp = await self._client.post(
                url, headers=headers, json={"modelUri": uri, "text": text}
            )
            if resp.status_code >= 400:
                raise LLMError(f"yandex embed {resp.status_code}: {resp.text}")
            out.append(resp.json()["embedding"])
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
