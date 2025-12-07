# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Load llm utilities."""

from __future__ import annotations
from yandex_cloud_ml_sdk import YCloudML
import json
import time

import asyncio
import logging
from typing import Any, TYPE_CHECKING

import requests

from graphrag.config.enums import LLMType
from graphrag.llm import (
    CompletionLLM,
    EmbeddingLLM,
    LLMCache,
    LLMLimiter,
)

import os

log = logging.getLogger(__name__)

current_dir = os.getcwd()
parent_dir = os.path.abspath(os.path.join(current_dir, "graphrag"))
file_path = os.path.join(parent_dir, "api_key.json")

try:
    folder_id = os.getenv("YANDEX_FOLDER_ID")
    token = os.getenv("YANDEX_TOKEN")
    model_name = os.getenv("YANDEX_MODEL_NAME")
    model_version = os.getenv("YANDEX_MODEL_VERSION")

except FileNotFoundError:
    print("Файл не найден.")
except json.JSONDecodeError:
    print("Ошибка декодирования JSON.")

if TYPE_CHECKING:
    from datashaper import VerbCallbacks

    from graphrag.index.cache import PipelineCache
    from graphrag.index.typing import ErrorHandlerFn

log = logging.getLogger(__name__)

_semaphores: dict[str, asyncio.Semaphore] = {}
_rate_limiters: dict[str, LLMLimiter] = {}


def load_llm(
    name: str,
    llm_type: LLMType,
    callbacks: VerbCallbacks,
    cache: PipelineCache | None,
    llm_config: dict[str, Any] | None = None,
    chat_only=False,
) -> CompletionLLM:
    """Load the LLM for the entity extraction chain."""
    on_error = _create_error_handler(callbacks)

    if llm_type in loaders:
        if chat_only and not loaders[llm_type]["chat"]:
            raise ValueError(f"LLM type {llm_type} does not support chat")
        if cache:
            cache = cache.child(name)

        loader = loaders[llm_type]
        return loader["load"](on_error, cache, llm_config or {})

    raise ValueError(f"Unknown LLM type {llm_type}")


def _create_error_handler(callbacks: VerbCallbacks) -> ErrorHandlerFn:
    def on_error(
        error: BaseException | None = None,
        stack: str | None = None,
        details: dict | None = None,
    ) -> None:
        callbacks.error("Error Invoking LLM", error, stack, details)

    return on_error


def _load_yandex_completion_llm(
    on_error: ErrorHandlerFn,
    cache: LLMCache,
    config: dict[str, Any],
):
    sdk = YCloudML(folder_id=folder_id, auth=token)

    model = sdk.models.completions(model_name, model_version=model_version)

    return YandexGPTLLM(model, on_error=on_error, cache=cache)


def load_llm_embeddings(
    name: str,
    llm_type: LLMType,
    callbacks: VerbCallbacks,
    # on_error: ErrorHandlerFn,
    cache: PipelineCache | None,
    config: dict[str, Any],
) -> EmbeddingLLM:
    """
    Загружает Yandex GPT для генерации эмбеддингов.

    Args:
        on_error (ErrorHandlerFn): Обработчик ошибок.
        cache (LLMCache): Кэш запросов.
        config (dict[str, Any]): Конфигурация для Yandex GPT.

    Returns:
        EmbeddingLLM: Объект для работы с эмбеддингами.
    """
    on_error = _create_error_handler(callbacks)
    sdk = YCloudML(folder_id=folder_id, auth=token)
    model = sdk.models.completions(model_name)

    return YandexGPTEmbeddingLLM(model, on_error, cache)


loaders = {
    LLMType.YandexGPTChat: {
        "load": _load_yandex_completion_llm,
        "chat": False,
    },
    LLMType.YandexGPTEmbedding: {
        "load": load_llm_embeddings,
        "chat": False,
    },
}


class YandexGPTLLM(CompletionLLM):
    def __init__(self, model, on_error, cache):
        self.model = model
        # self.max_tokens = max_tokens
        # self.temperature = temperature
        self.on_error = on_error
        self.cache = cache

    async def __call__(self, prompt: str, **kwargs) -> dict:
        """
        Вызывает Yandex GPT для генерации текста.

        Args:
            prompt (str): Подсказка для модели.
            variables (dict): Переменные для замены в подсказке.
            kwargs: Дополнительные параметры.

        Returns:
            dict: Ответ модели.
        """
        try:
            sdk = YCloudML(folder_id=folder_id, auth=token)

            new_model = sdk.models.completions(model_name)
            if "temperature" in kwargs:
                new_model = new_model.configure(temperature=kwargs["temperature"])
            if "max_tokens" in kwargs:
                new_model = new_model.configure(max_tokens=kwargs["max_tokens"])

            response = new_model.run(prompt)
            result = {
                "output": response[0].text,
                "history": [],
            }

            # Сохраняем в кэш
            # if self.cache:
            #     self.cache.set(cache_key, result)

            return result
        except Exception as e:
            self.on_error(e, None, {"prompt": prompt})
            raise


class YandexGPTEmbeddingLLM(EmbeddingLLM):
    def __init__(self, model, on_error, cache):
        self.model = model
        self.on_error = on_error
        self.cache = cache

    async def generate_embeddings(self, text: list[str]):
        """
        Генерирует эмбеддинги для заданного текста.

        Args:
            text (str): Текст для обработки.

        Returns:
            list[float]: Эмбеддинги текста.
        """
        try:
            # Кэширование запросов
            # cache_key = f"embedding-{text}"
            # if self.cache and cache_key in self.cache:
            #     return self.cache.get(cache_key)

            # if cache is not None:
            #     cache = cache.child(name)

            doc_uri = f"emb://{folder_id}/text-search-doc/latest"
            query_uri = f"emb://{folder_id}/text-search-query/latest"

            embed_url = (
                "https://llm.api.cloud.yandex.net:443/foundationModels/v1/textEmbedding"
            )
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "x-folder-id": f"{folder_id}",
            }

            def get_embedding(text: str, text_type: str = "doc"):
                query_data = {
                    "modelUri": doc_uri if text_type == "doc" else query_uri,
                    "text": text,
                }

                try:
                    return requests.post(
                        embed_url, json=query_data, headers=headers
                    ).json()["embedding"]
                except:
                    time.sleep(1)
                    query_data = {
                        "modelUri": doc_uri if text_type == "doc" else query_uri,
                        "text": text,
                    }
                    res = requests.post(
                        embed_url, json=query_data, headers=headers
                    ).json()

                    return res["embedding"]

            embeddings = [get_embedding(t) for t in text]

            # if self.cache:
            #     self.cache.set(cache_key, embeddings)

            return embeddings

        except Exception as e:
            self.on_error(e, None, {"text": text})
            raise
