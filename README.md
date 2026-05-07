# GraphRAG Explorer

Interactive diagnosis and curation of cascading errors in Russian
GraphRAG pipelines. SIGIR'26 demo (HSE University) — see the paper
draft on Overleaf for the why; this README is the how.

## R2 architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Frontend (Nuxt 4 + Vue 3 + @krainovsd/graph)                         │
│   /corpora            ← list of corpora and variants                  │
│   /wizards/build      ← 5-step build wizard (corpus → docs → EDA      │
│                          → pipeline → review)                          │
│   /wizards/ask        ← reasoning wizard, single + MoE, SSE expert    │
│                          stream                                        │
│   /graphs/{id}        ← LayeredGraph + suggestions sidebar +          │
│                          NodeDrawer with NodeTools                     │
│   /graphs/compare     ← split-view MoE comparison                     │
└──────────┬─────────────────────────────────────────────┬──────────────┘
           │ /api/* (typed client in app/lib/api-client) │
           ▼                                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI, api/)                                              │
│   ┌─────────────────┐   ┌──────────────────┐   ┌──────────────────┐   │
│   │ Strategy        │   │ Curation engine  │   │ MoE orchestrator │   │
│   │ registries      │ → │ (journal applier │ ← │ (run_moe +       │   │
│   │ (8 kinds)       │   │  + repository)   │   │  stream_moe)     │   │
│   └─────────────────┘   └──────────────────┘   └──────────────────┘   │
│   NER + LLM gateway (Deepseek default · Yandex optional)              │
└──────────┬─────────────────────────────────────────────┬──────────────┘
           │                                              │
           ▼                                              ▼
   ┌────────────────────┐                       ┌────────────────────┐
   │  Postgres 16       │                       │  FAISS per-graph   │
   │  (alembic-migrated)│                       │  (named volume)    │
   └────────────────────┘                       └────────────────────┘
```

## Запуск (one-command, Phase 7)

```sh
cp .env.example .env
# Заполни DEEPSEEK__API_KEY и POSTGRES__PASSWORD
docker compose up --build
```

После запуска:

| URL                                | Что                       |
| ---------------------------------- | ------------------------- |
| http://localhost:3000              | Frontend (Nuxt)           |
| http://localhost:8000/api/health   | Backend healthcheck       |
| http://localhost:8000/docs         | OpenAPI swagger           |
| http://localhost:5432              | Postgres (graphrag DB)    |

End-to-end smoke (ingest → build → agent → accept → reason):

```sh
cd backend && uv run python -m scripts.smoke
```

Импорт встроенного HSE podcast корпуса (миграция parquet → R2):

```sh
cd backend
uv run python -m scripts.migrate_podcast --postgres
# затем открыть http://localhost:3000/corpora
```

## Локальный dev (без Docker)

Backend:

```sh
cd backend
uv sync --all-packages
docker run -d --name r2-pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=changeme -e POSTGRES_USER=graphrag -e POSTGRES_DB=graphrag \
  postgres:16-alpine
cd api/db && alembic upgrade head && cd ../..
DEEPSEEK__API_KEY=sk-... POSTGRES__PASSWORD=changeme \
  uv run uvicorn api.__main__:app --reload --port 8000
```

Frontend:

```sh
cd frontend
pnpm install
NUXT_API_PROXY_TARGET=http://localhost:8000 pnpm dev
```

## Тесты

Backend (242+ pytest):

```sh
cd backend/api
uv run pytest -q -m "not slow"
uv run ruff check .
```

Frontend (vue-tsc):

```sh
cd frontend
pnpm vue-tsc --noEmit
```

## Конфигурация

Все настройки идут через env (`.env` или окружение). Поля — в
[backend/api/config/settings.py](backend/api/config/settings.py).
Ключевые:

| Env var                      | Default                 | Что                                              |
| ---------------------------- | ----------------------- | ------------------------------------------------ |
| `DEEPSEEK__API_KEY`          | (empty)                 | Default LLM provider                             |
| `POSTGRES__PASSWORD`         | (empty)                 | Non-empty → backend uses PG repo, иначе in-memory|
| `STORAGE__DATA_DIR`          | `./data`                | FAISS indexes + blobs                            |
| `NUXT_PUBLIC_API_BASE`       | (empty, dev proxy)      | Frontend ↔ backend base URL                      |
| `NUXT_API_PROXY_TARGET`      | `http://localhost:8000` | Dev-mode reverse proxy target                    |

## Phase status (R2)

- ✅ Phase 0 — foundations (domain · LLM · config · FAISS · EDA · CI)
- ✅ Phase 1 — registries (builders · cleaners · clusterers · reasoners) + 5 routes
- ✅ Phase 2 — curation journal · repository · undo · 409 lock
- ✅ Phase 3 — agents (entity_dedup, orphan_rescuer, low_confidence_triplet, topic_report_refresher) + Suggestion CRUD
- ✅ Phase 4 — MoE orchestrator + 3 aggregators + SSE
- ✅ Phase 5 — Tools-on-nodes (5 plugins) + RankerProtocol (tfidf_cosine real, gat stub)
- ✅ Phase 6 — afina-style wizards · LayeredGraph · NodeDrawer · SuggestionsSidebar · LayerMap · split-view
- ✅ Phase 7 — docker-compose · podcast migration · smoke script · this README

Открытые большие куски (см. `docs/redesign/plan.md` § Deferred):

- D1–D7: MoE production-readiness (cost / quotas / batching / cache / aggregator-eval)
- 5b ML: GATRanker actual training/inference path (PyTorch+PyG)
- MicrosoftBuilder + Microsoft{Global,Local}Search: подключить PyPI graphrag (сейчас стабы)

## Документы

- `docs/redesign/requirements.md` — F1–F7, NF1–NF9
- `docs/redesign/plan.md` — фазовый план + Deferred + research-задачи
- `docs/redesign/decisions/0001-deprecate-graphrag-fork.md` — ADR
- `docs/redesign/research/{layered_graph_viz,vector_store,multilayer_community_detection}.md`
- `docs/raw/*.pdf` — 6 papers, на которых стоят дизайн-решения R2
