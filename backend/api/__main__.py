"""GraphRAG Explorer R2 — minimal entry point.

The legacy app (parquet-loaded podcast/gazeta globals + GlobalSearch over
the in-tree Microsoft GraphRAG fork) was retired in Phase 0.6. The real
endpoints come back in Phase 1 once the strategy registries land. Until
then this stub just registers LLM clients and exposes /api/health so the
container boots and orchestration can be wired up.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from api.config import get_settings
from api.llm import register_clients
from api.llm.deepseek import DeepseekClient
from api.llm.yandex import YandexCompletionClient, YandexEmbeddingClient
from api.routes import eda_router, graphs_router, strategies_router

app = FastAPI(title="GraphRAG Explorer R2", version="0.2.0")
app.include_router(strategies_router)
app.include_router(eda_router)
app.include_router(graphs_router)


@app.on_event("startup")
def _wire_llm_clients() -> None:
    s = get_settings()
    completion: dict[str, object] = {}
    embedding: dict[str, object] = {}
    default_completion: str | None = None

    if s.deepseek.api_key:
        completion["deepseek"] = DeepseekClient(
            api_key=s.deepseek.api_key,
            base_url=s.deepseek.base_url,
            default_model=s.deepseek.model,
            timeout_s=s.deepseek.timeout_s,
        )
        default_completion = "deepseek"

    if s.yandex.token and s.yandex.folder_id:
        completion["yandex"] = YandexCompletionClient(
            folder_id=s.yandex.folder_id,
            token=s.yandex.token,
            default_model=s.yandex.completion_model,
            default_model_version=s.yandex.completion_model_version,
        )
        embedding["yandex"] = YandexEmbeddingClient(
            folder_id=s.yandex.folder_id,
            token=s.yandex.token,
            default_model=s.yandex.embedding_model,
            dim=s.yandex.embedding_dim,
        )
        default_completion = default_completion or "yandex"

    if not completion:
        logger.warning("no LLM provider configured — set DEEPSEEK__API_KEY or YANDEX__*")
        return

    register_clients(
        completion=completion,  # type: ignore[arg-type]
        embedding=embedding or None,  # type: ignore[arg-type]
        default_completion=default_completion,
        default_embedding="yandex" if "yandex" in embedding else None,
    )
    logger.info(
        "llm clients registered: completion={}, default={}",
        sorted(completion.keys()),
        default_completion,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


def main() -> None:
    import uvicorn

    s = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level=s.log_level.lower())


if __name__ == "__main__":
    main()
