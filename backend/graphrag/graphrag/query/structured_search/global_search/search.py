import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import tiktoken
from yandex_cloud_ml_sdk import YCloudML

from graphrag.callbacks.global_search_callbacks import GlobalSearchLLMCallback
from graphrag.query.context_builder.builders import GlobalContextBuilder
from graphrag.query.context_builder.conversation_history import (
    ConversationHistory,
)
from graphrag.query.structured_search.base import BaseSearch, SearchResult
from graphrag.query.structured_search.global_search.map_system_prompt import (
    MAP_SYSTEM_PROMPT,
)
from graphrag.query.structured_search.global_search.reduce_system_prompt import (
    GENERAL_KNOWLEDGE_INSTRUCTION,
    REDUCE_SYSTEM_PROMPT,
)

DEFAULT_MAP_LLM_PARAMS = {
    "max_tokens": 1000,
    "temperature": 0.0,
}

DEFAULT_REDUCE_LLM_PARAMS = {
    "max_tokens": 2000,
    "temperature": 0.0,
}

log = logging.getLogger(__name__)


@dataclass
class GlobalSearchResult(SearchResult):
    """A GlobalSearch result."""

    map_responses: list[SearchResult]
    reduce_context_data: str | list[pd.DataFrame] | dict[str, pd.DataFrame]
    reduce_context_text: str | list[str] | dict[str, str]


class GlobalSearch(BaseSearch):
    """Search orchestration for global search mode."""

    def __init__(
        self,
        context_builder: GlobalContextBuilder,
        folder_id: str,
        token: str,
        token_encoder: tiktoken.Encoding,
        map_system_prompt: str = MAP_SYSTEM_PROMPT,
        reduce_system_prompt: str = REDUCE_SYSTEM_PROMPT,
        response_type: str = "multiple paragraphs",
        allow_general_knowledge: bool = False,
        general_knowledge_inclusion_prompt: str = GENERAL_KNOWLEDGE_INSTRUCTION,
        json_mode: bool = True,
        callbacks: list[GlobalSearchLLMCallback] | None = None,
        max_data_tokens: int = 8000,
        map_llm_params: dict[str, Any] = DEFAULT_MAP_LLM_PARAMS,
        reduce_llm_params: dict[str, Any] = DEFAULT_REDUCE_LLM_PARAMS,
        context_builder_params: dict[str, Any] | None = None,
        concurrent_coroutines: int = 32,
    ):
        super().__init__(
            llm="a",
            context_builder=context_builder,
            context_builder_params=context_builder_params,
        )
        self.map_system_prompt = map_system_prompt
        self.reduce_system_prompt = reduce_system_prompt
        self.response_type = response_type
        self.allow_general_knowledge = allow_general_knowledge
        self.general_knowledge_inclusion_prompt = general_knowledge_inclusion_prompt
        self.callbacks = callbacks
        self.max_data_tokens = max_data_tokens
        self.folder_id = folder_id
        self.token = token
        self.token_encoder = token_encoder
        self.sdk = YCloudML(folder_id=folder_id, auth=token)
        self.map_llm_params = map_llm_params
        self.reduce_llm_params = reduce_llm_params
        if json_mode:
            self.map_llm_params["response_format"] = {"type": "json_object"}
        else:
            self.map_llm_params.pop("response_format", None)

        self.semaphore = asyncio.Semaphore(concurrent_coroutines)

    async def asearch(
        self,
        query: str,
        conversation_history: ConversationHistory | None = None,
        **kwargs: Any,
    ) -> GlobalSearchResult:
        """Perform a global search with callbacks."""
        start_time = time.time()

        context_chunks, context_records = self.context_builder.build_context(
            conversation_history=conversation_history, **self.context_builder_params
        )

        map_responses = []
        for data in context_chunks:
            map_prompt = self.map_system_prompt.format(context_data=data)

            raw_response = await self._generate_text(
                prompt=f"{map_prompt}\n\nUser Query: {query}",
                max_tokens=self.map_llm_params["max_tokens"],
                temperature=self.map_llm_params["temperature"],
            )

            parsed_response = self.parse_search_response(raw_response)

            map_responses.append(
                SearchResult(
                    response=parsed_response,
                    context_data=data,
                    context_text=data,
                    completion_time=time.time() - start_time,
                    llm_calls=1,
                    prompt_tokens=self._count_tokens(map_prompt),
                )
            )

        if self.callbacks:
            for callback in self.callbacks:
                callback.on_map_response_end(map_responses)

        key_points = []
        for index, response in enumerate(map_responses):
            if not isinstance(response.response, list):
                continue
            for element in response.response:
                if not isinstance(element, dict):
                    continue
                if "answer" not in element or "score" not in element:
                    continue
                key_points.append(
                    {
                        "analyst": index,
                        "answer": element["answer"],
                        "score": element["score"],
                    }
                )

        filtered_key_points = [point for point in key_points if point["score"] > 0]
        sorted_key_points = sorted(
            filtered_key_points, key=lambda x: x["score"], reverse=True
        )

        data = []
        total_tokens = 0
        for point in sorted_key_points:
            formatted_response_data = [
                f"----Analyst {point['analyst'] + 1}----",
                f"Importance Score: {point['score']}",
                point["answer"],
            ]
            formatted_response_text = "\n".join(formatted_response_data)
            if (
                total_tokens + self._count_tokens(formatted_response_text)
                > self.max_data_tokens
            ):
                break
            data.append(formatted_response_text)
            total_tokens += self._count_tokens(formatted_response_text)
        text_data = "\n\n".join(data)

        reduce_prompt = self.reduce_system_prompt.format(
            report_data=text_data,
            response_type=self.response_type,
        )
        reduce_response = await self._generate_text(
            prompt=reduce_prompt,
            max_tokens=self.reduce_llm_params["max_tokens"],
            temperature=self.reduce_llm_params["temperature"],
        )

        return GlobalSearchResult(
            response=reduce_response,
            context_data=context_records,
            context_text=context_chunks,
            map_responses=map_responses,
            reduce_context_data=reduce_prompt,
            reduce_context_text=reduce_prompt,
            completion_time=time.time() - start_time,
            llm_calls=len(context_chunks),
            prompt_tokens=self._count_tokens(reduce_prompt),
        )

    def search(
        self,
        query: str,
        conversation_history: ConversationHistory | None = None,
        **kwargs: Any,
    ) -> GlobalSearchResult:
        """Perform a global search synchronously."""
        return asyncio.run(self.asearch(query, conversation_history))

    def _count_tokens(self, text: str) -> int:
        """Count tokens using the provided token encoder."""
        return len(self.token_encoder.encode(text))

    async def _generate_text(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Uses YandexGPT to generate a text completion."""
        model = self.sdk.models.completions("yandexgpt").configure(
            max_tokens=max_tokens,
            temperature=temperature,
        )
        response = model.run(prompt)
        return response[0].text

    def parse_search_response(self, search_response: str) -> list[dict[str, Any]]:
        """Parse the search response JSON and return a list of key points."""
        try:
            search_response = search_response.strip("```")
            response_data = json.loads(search_response)
            if "points" in response_data and isinstance(response_data["points"], list):
                return [
                    {
                        "answer": point.get("description", ""),
                        "score": int(point.get("score", 0)),
                    }
                    for point in response_data["points"]
                    if "description" in point and "score" in point
                ]
            return [{"answer": "", "score": 0}]
        except (json.JSONDecodeError, TypeError, ValueError):
            print("Ошибка парсинга")
            print(search_response)
            log.warning("Failed to parse search response, returning empty response.")
            return [{"answer": "", "score": 0}]
