import requests
from tenacity import (
    Retrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from graphrag.logging import StatusLogger
from graphrag.query.llm.base import BaseLLM, BaseLLMCallback

# Константы для URL и ошибок
_MODEL_REQUIRED_MSG = "model is required"
YANDEX_API_URL = 'https://llm.api.cloud.yandex.net/foundationModels/v1/completion'


class ChatYandexGPT(BaseLLM):
    """Wrapper for Yandex GPT models."""

    def __init__(
        self,
        token: str,
        folder_id: str,
        model: str = 'gpt://<folder_ID>/yandexgpt-lite',
        max_retries: int = 10,
        request_timeout: float = 180.0,
        reporter: StatusLogger | None = None,
    ):
        self.token = token
        self.folder_id = folder_id
        self.model = model
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self._reporter = reporter # or StatusLogger()
    
    def _request(self, data: dict):
        """Отправка POST-запроса к Yandex GPT API."""
        headers = {
            'Authorization': f'Bearer {self.token}',
            'X-Folder-ID': self.folder_id,
            'Content-Type': 'application/json'
        }
        response = requests.post(YANDEX_API_URL, headers=headers, json=data)
        return response.json()

    def _generate(
        self,
        messages: list[dict],
        streaming: bool = False,
        callbacks: list[BaseLLMCallback] | None = None,
        **kwargs
    ):
        """Генерация текста (без стриминга)."""
        data = {
            'modelUri': self.model,
            'completionOptions': {
                'stream': streaming,
                # 'temperature': kwargs.get('temperature', 0.3),
                # 'maxTokens': kwargs.get('maxTokens', 1000)
            },
            'messages': messages
        }

        try:
            retryer = Retrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential_jitter(max=10),
                reraise=True,
                retry=retry_if_exception_type(requests.exceptions.RequestException),
            )

            for attempt in retryer:
                with attempt:
                    response = self._request(data)
                    if not streaming:
                        return response['result']['alternatives'][0]['text']
                    
        except RetryError as e:
            self._reporter.error(f"Error in generate(): {e}")
            return ""
    
    def stream_generate(
        self,
        messages: list[dict],
        callbacks: list[BaseLLMCallback] | None = None,
        **kwargs: Any,
    ):
        """Генерация текста с поддержкой стриминга (эмуляция)."""
        data = {
            'modelUri': self.model,
            'completionOptions': {
                'stream': True,
                'temperature': kwargs.get('temperature', 0.3),
                'maxTokens': kwargs.get('maxTokens', 1000)
            },
            'messages': messages
        }

        try:
            retryer = Retrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential_jitter(max=10),
                reraise=True,
                retry=retry_if_exception_type(requests.exceptions.RequestException),
            )

            for attempt in retryer:
                with attempt:
                    response = self._request(data)
                    for alternative in response['result']['alternatives']:
                        if callbacks:
                            for callback in callbacks:
                                callback.on_llm_new_token(alternative['text'])
                        yield alternative['text']
                    
        except RetryError as e:
            self._reporter.error(f"Error in stream_generate(): {e}")

    async def agenerate(
        self,
        messages: list[dict],
        streaming: bool = False,
        callbacks: list[BaseLLMCallback] | None = None,
        **kwargs: Any,
    ) -> str:
        """Асинхронная генерация текста."""
        # Точно так же как и `generate`, только для асинхронных случаев.
        # Асинхронный запрос к Yandex GPT можно построить на основе `aiohttp` или других асинхронных библиотек.
        pass

    async def astream_generate(
        self,
        messages: list[dict],
        callbacks: list[BaseLLMCallback] | None = None,
        **kwargs: Any,
    ):
        """Асинхронная генерация текста со стримингом."""
        # То же, что и stream_generate, но асинхронно
        pass
