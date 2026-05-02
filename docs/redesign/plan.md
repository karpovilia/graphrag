# GraphRAG Explorer — Work Plan (Redesign R2)

> Версия: draft v2, 2026-05-02 (после ответов на Q1–Q10)
> Парный документ: `requirements.md`. Здесь — как именно превратить требования в изменения кода.
>
> **Зафиксированные решения** (см. § Открытые вопросы → Resolved ниже): депрекейтим Microsoft GraphRAG-форк, дефолтный LLM — Deepseek, MoE — для статьи (production-вопросы → Deferred), wizard-UX в стиле afina-ai-first (пошаговость + back-nav + чат), форкаем @krainovsd/graph, GNN обязателен, vector store — отдельный research, целевой корпус — HSE podcast, типы сущностей — через EDA, деплой локальный.

---

## 0. Tl;dr

Шесть фаз, каждая ≈ 1.5–3 недели одиночной разработки. Фазы 0–2 закладывают фундамент (модель данных, registry, persistence), без которого всё дальнейшее превратится в спагетти. Фазы 3–5 — фичи в порядке риска (агенты → MoE → GNN), фаза 6 — UI-перезагрузка (она самая видимая, поэтому подмывает начать с неё, но без backend-фундамента UI снова уткнётся в `setTimeout(2000)`).

```
Phase 0  Foundations (model, persistence, config)         ≈ 1.5w
Phase 1  Builder/Cleaner/Reasoner registries               ≈ 2w
Phase 2  Curation journal + incremental recompute          ≈ 2w
Phase 3  Curation agents + Suggestion UI                   ≈ 2w
Phase 4  MoE reasoning over multiple GraphVariants         ≈ 2w
Phase 5  Tools-on-nodes + GNN ranker                       ≈ 3w
Phase 6  New UX (afina-style import + layered viewer)      ≈ 3w
```

Общая оценка: ≈ 13–15 недель полной занятости.

---

## 1. Текущее состояние и долги (ground truth)

Подробно — в отчётах подагентов (выше в треде). Кратко важное для плана:

- `backend/api/graphrag_processing.py` — YandexGPT захардкожен (lines 162–189), LocalSearch закомментирован (lines 243–275), DataFrame'ы parquet грузятся в module-scope при старте (lines 144–157). Всё это перепишется.
- `backend/graphrag/graphrag/index/operations/cluster_graph.py` — Bayan уже реализован (lines 123–146), но не подключён к enum `GraphCommunityStrategyType`. Лёгкий win в Phase 1.
- `backend/graphrag/graphrag/` — модифицированная копия Microsoft GraphRAG. **Решение принято: депрекейт.** Заменяем на PyPI-зависимость `graphrag` + тонкий `MicrosoftBuilder`-адаптер. Локальные правки (Bayan в `cluster_graph.py:123-146`, language-aware prompts в `graphrag_processing.py:33-72`) переносим в наши плагины — они нашими и должны быть, не патчем upstream.
- `backend/scripts/ddl.sql` — в Postgres только кеш промптов (`prompt_histories`, `prompt_selected_nodes`). Расширить.
- `frontend/app/pages/index.vue:227,238,263,267` — fake stages `setTimeout(_, 2000)`. Удалить, заменить на SSE.
- `frontend/server/api/import.ts` — no-op заглушка. Перенаправить на бэкенд.
- `frontend/app/pages/graph/[id].vue:494,517` — hardcoded `http://192.168.135.118:8000`. В runtime config.
- `@krainovsd/graph` (frontend `package.json:16`) — 2D force, без layered. Для F7 нужен либо его форк, либо замена. Открытый вопрос Q5.

---

## 2. Целевая архитектура (high-level)

```
┌────────────────────────────────────────────────────────────────────┐
│                     Frontend (Nuxt 4 + Vue 3)                       │
│  Wizard import  │  Layered Graph Viewer (2D + opacity)  │ Reasoning │
└──────────────────┬───────────────────────────────────────┬─────────┘
                   │  REST + SSE                            │
┌──────────────────▼─────────────┐         ┌────────────────▼────────┐
│  FastAPI orchestrator (api/)   │ ◄──────► │  Worker pool (Celery /  │
│  Builder / Reasoner registries │  events  │  arq) для тяжёлых задач │
└──────────────────┬─────────────┘         └─────────────────────────┘
                   │
┌──────────────────▼────────────────────────────────────────────────┐
│  Strategy registries                                                │
│  Builder │ Cleaner │ Clusterer │ Summarizer │ Reasoner │ Agent │ Tool│
└──────────────────┬─────────────────────────────────────────────────┘
                   │
┌──────────────────▼─────────────┐  ┌─────────────────────────────┐
│  Domain model (Corpus,         │  │  LLM gateway (LiteLLM-like) │
│  GraphVariant, Layer, Node,    │  │  Yandex / OpenAI / Anthropic│
│  Edge, Suggestion, Run, Tool)  │  │  / local vLLM, общий backoff│
└──────────────────┬─────────────┘  └─────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────────────┐
│  Persistence: Postgres + pgvector + S3-compatible blob store    │
│  (entities, edges, embeddings, summaries, journal, chunks)      │
└─────────────────────────────────────────────────────────────────┘
```

Ключевая мысль — все «способы» (build/clean/cluster/summarize/reason/curate/tool) — это плагины, регистрируемые декоратором при импорте. Выбор стратегии всегда сериализуется в БД (для воспроизводимости).

---

## 3. Phase 0 — Foundations (≈ 1.5 недели)

**Цель:** общий каркас, без которого нельзя делать ни pluggability, ни incremental recompute.

### Задачи
- **0.1.** Domain model в `backend/api/domain/`: `Corpus`, `GraphVariant`, `Layer`, `Node` (с `layer`, `type`, `granularity`, `provenance`), `Edge`, `Suggestion`, `Run`, `ToolInvocation`, `JournalEntry`. Pydantic v2 как rigid validation.
- **0.2.** Postgres schema (Alembic, не raw `ddl.sql`): таблицы под domain model + ссылки на vector store (см. 0.6). Включает existing `prompt_histories`. Миграция со старого `ddl.sql`.
- **0.3.** LLM gateway: модуль `backend/api/llm/` с интерфейсом `LLMClient.complete(messages, params) -> Completion`. **Дефолтный клиент — Deepseek** (вся разработка и тесты на нём). Адаптеры Yandex/OpenAI — рядом, для прода. Захардкоженный `YandexGPT` из `graphrag_processing.py:162-189` — мигрируется в YandexAdapter, но не используется по умолчанию.
- **0.4.** Конфиг: `pydantic-settings`-based, как сейчас, но без `PODCAST/GAZETA` хардкодов в `settings.py`. Графы — это записи в БД. Целевой первый корпус — HSE podcast (импорт из `backend/data/yandex5_podcast/`).
- **0.5.** Базовые тесты + CI: ruff + pytest + минимум 1 интеграционный тест на in-memory FastAPI. LLM-вызовы в тестах — replay-фикстуры, не реальный Deepseek.
- **0.6.** **Депрекейт форка Microsoft GraphRAG.**
  - Удалить `backend/graphrag/` из workspace `backend/pyproject.toml`.
  - Добавить `graphrag` (Microsoft) как обычную зависимость через `pip`/`uv`.
  - Перенести локальные правки наружу: Bayan-кластерер (`cluster_graph.py:123-146`) → отдельный плагин в Phase 1; language-aware prompts (`graphrag_processing.py:33-72`) → в `prompts/` нашего проекта.
  - Архивная копия форка остаётся в git-истории; в `docs/redesign/decisions/0001-deprecate-graphrag-fork.md` фиксируется почему и что мигрировано.
- **0.7.** **Vector store — FAISS + per-graph index pattern** (override от 2026-05-03 поверх первичной рекомендации R-02; обоснование — `docs/redesign/research/vector_store.md`, шапка «decision overrides»).
  - **Форма:** один `faiss.IndexHNSWFlat` (или `IndexFlatIP` для самых маленьких графов) на каждое сочетание `(graph_variant_id, embedding_model)`. Метаданные узлов и mapping `vector_position ↔ node_id` лежат в Postgres / sqlite-сайдкаре. Это одновременно решает две проблемы FAISS: отсутствие нативного metadata-фильтра (его не нужно — индекс **есть** фильтр по `graph_variant_id`) и плохое удаление в HNSW (на каждую курацию делается полный rebuild индекса; 3k векторов = доли секунды).
  - **`VectorStoreProtocol` сохраняем** в виде `Eq | In | And | Or | Not`-фильтра как описано в R-02, чтобы R3 мог переключиться на Qdrant/pgvector без переписывания call-site'ов. `FaissAdapter` реализует фильтр через выбор подходящего индекса (если фильтр указывает только `graph_variant_id` — берётся соответствующий индекс целиком; для составных фильтров — pre-filter по metadata в PG, затем `IndexIDMap2` со списком разрешённых ids).
  - **Multi-dim:** index-per-model — то же решение «отдельный физический контейнер на каждую размерность», что было бы и у pgvector.
  - **Persistence:** `faiss.write_index(index, blob_path)` после каждого rebuild; blob лежит рядом с graph-варинтом. Lazy-load в память при первом обращении (LRU-кеш на N последних использованных индексов).
  - **DoD-чек-лист:**
    - Реализован `FaissAdapter` по `VectorStoreProtocol` (upsert / search / delete / create_collection).
    - Скрипт `scripts/migrate_parquet_to_db.py` (Phase 0.4) при импорте HSE podcast строит per-graph FAISS-индекс на CPU.
    - Бенчмарк-санити: rebuild индекса на 3k×1024 vec — < 2 секунды; search k=20 — < 5 ms p95. (Цифры с большим запасом, FAISS на этом масштабе тривиален.)
    - Persistence/load round-trip: записал индекс → перезагрузил → top-20 идентичны.
    - Никаких новых сервисов в docker-compose (FAISS — pip-зависимость).
  - **Когда возвращаемся к R-02 рекомендациям:** если в R3 понадобится hybrid search (vec + keyword), реал-тайм concurrent writes от нескольких процессов, или общий объём перевалит за ~1М векторов — переключаемся на Qdrant standalone (Вариант B из R-02). Миграция через dual-write по outbox (см. 2.1) делает это дешёвым.
- **0.8.** EDA-сервис (фундамент для F4.2 шаг 3): `backend/api/eda/` с быстрыми эвристиками по корпусу — длина документов, плотность сущностей (через лёгкий NER, не LLM), оценка морфологического разброса для русского. Возвращает рекомендации для следующих шагов визарда. Минимальная реализация — на Phase 0; обвязка UI — на Phase 6.

### Definition of Done
- `alembic upgrade head` поднимает новую схему.
- `backend/graphrag/` больше не импортируется; `graphrag` подтягивается из PyPI.
- HSE podcast (`data/yandex5_podcast/*.parquet`) импортируется скриптом `backend/scripts/migrate_parquet_to_db.py` в новый формат.
- Тест: «загрузить podcast из parquet → выгрузить как GraphVariant → пересобрать в API → структурное равенство». Контракт на дальнейшее.
- Research-доклад по vector store сдан, выбран backend, `VectorStoreProtocol` имплементирован для выбранного варианта (минимум один).
- ADR `0001-deprecate-graphrag-fork.md` зафиксирован.

### Риски
- Vector store dimensions не совпадут с разными embedding-моделями. Решение: одна `embedding`-колонка/коллекция per `(node_id, model)` с metadata-фильтрацией.
- PyPI-`graphrag` может отстать от форка по фиче или сломать API в новой версии. Решение: версионная фиксация + ADR с планом миграции при breaking change.

---

## 4. Phase 1 — Builder / Cleaner / Reasoner registries (≈ 2 недели)

**Цель:** вытащить «способы» в плагины (F2). После фазы должна работать схема: «загрузил corpus → выбрал builder X / cleaner Y / clusterer Z → получил GraphVariant».

### Задачи
- **1.1.** Декоратор `@register("builder", "lightrag")` + базовый `BuilderProtocol(corpus) -> GraphVariant`. Всё — в `backend/api/strategies/`.
- **1.2.** Builders:
  - `MicrosoftBuilder` — тонкий адаптер над PyPI-пакетом `graphrag` (после депрекейта форка в 0.6),
  - `LightRAGBuilder` (LLM-profiling узлов, см. `docs/raw/2410.05779v3.pdf`),
  - `ToG3Builder` (heterogeneous Chunk-Triplet-Community, см. `docs/raw/2509.21710v2.pdf`).
  - `FastRAGBuilder` (schema/script learning) — стартует за рамками MVP, но место в реестре зарезервировано.
- **1.3.** Cleaners:
  - `LeidenRecluster`, `BayanRecluster` (нашим кодом, не патчем upstream — см. 0.6), `ThresholdPruner`, `LLMDeduplicator`.
- **1.4.** Reasoners:
  - `MicrosoftGlobalSearch` (через PyPI graphrag), `MicrosoftLocalSearch` (включить — у нас он сейчас закомментирован в `graphrag_processing.py:243-275`, в upstream работает), `LightRAGDualKeyword`, `MACERReasoner`.
- **1.5.** API: `POST /api/builders`, `POST /api/cleaners`, `POST /api/reasoners` — list+describe; `POST /api/graphs` — запуск Build. Всё c task_id и SSE-прогрессом.
- **1.6.** В graph/edges/nodes явно проставляется `layer` и `granularity` (фундамент для F7).
- **1.7.** EDA-рекомендатор расширяется: на основе свойств корпуса предлагает default builder/cleaner/clusterer (например: «короткие чанки + плотный NER → LightRAG; длинные документы → Microsoft GraphRAG»). Логика — простой rule-based, не ML.

### Definition of Done
- Можно из CLI собрать тот же podcast двумя разными builders, получить два GraphVariant в одной DB.
- API возвращает каталог всех зарегистрированных стратегий с метаданными (`requires_layers`, `produces_layers`, `cost_estimate`).
- Юнит-тесты на каждый builder/cleaner с replay-фикстурами LLM (нет реальных вызовов в CI).

### Риски
- Microsoft GraphRAG-форк сам по себе — большой движок с собственной архитектурой workflows. Если оборачивать как один builder, риск долгого debug-цикла (см. вопрос Q1).
- LightRAG/MACER — внешние реализации могут потребовать отдельного venv. План: реализовать самим минимум — ровно то, что нужно для демо.

---

## 5. Phase 2 — Curation journal + incremental recompute (≈ 2 недели)

**Цель:** правка графа влечёт точечный пересчёт (claim из §3 статьи: «edits affecting a node trigger only localized regeneration»). Сейчас этого нет.

### Задачи
- **2.1.** `JournalEntry(graph_variant_id, op, payload, actor, ts, parent_id)` в БД, append-only. Операции: `merge_nodes, split_node, retype_node, move_to_community, edit_edge, delete_edge, add_edge, set_summary`. **Здесь же закладываем outbox-таблицу для vector store rebuild-триггеров:** любой merge/split/embed-update порождает запись `vector_outbox(graph_variant_id, model, ts, reason)`, которую vector-writer batches и пересобирает соответствующий FAISS-индекс. Дебаунс на ~1 секунду — несколько правок подряд в одном графе сводятся к одному rebuild. **Бонусом** outbox делает дешёвой будущую миграцию на сетевой backend (Qdrant из Варианта B в R-02): тот же же outbox в режиме dual-write → backfill → top-20 reconciliation → флип флага.
- **2.2.** Incremental engine: на каждый op — функция `affected_set(op, graph) -> set[node_id, edge_id, community_id]` + перезапуск только summarizer/embedding/community-reindex для затронутого. Кеш считаем по hash(node_state).
- **2.3.** Замена fake `POST /api/graph-save` (`backend/api/__main__.py:140-226`) — не «новая копия с timestamp», а нормальная транзакция edit+recompute+версия в журнале. Старый snapshot всё ещё доступен через `GET /api/graphs/:id?at=run_id`.
- **2.4.** Undo/redo по журналу (минимум: revert последней операции).
- **2.5.** Конфликты при concurrent edit — оптимистическая блокировка по `graph_variant.version`.

### Definition of Done
- Сценарий из §4 статьи (Case Study 1: merge fragmented entities → re-run query → ответ другой) воспроизводится через API без перезагрузки приложения.
- Бенчмарк: merge двух узлов на graph 3k вершин — < 3 секунды backend-времени.

### Риски
- Кросс-зависимость summary↔community↔embedding нетривиально декомпозировать. Если всё начинает каскадировать — fallback на «затронутая community → пересчёт всей community».

---

## 6. Phase 3 — Curation agents + Suggestion UI (≈ 2 недели)

**Цель:** Future Work из статьи + User req #1.

### Задачи
- **3.1.** Интерфейс `CurationAgent` (см. F1.1), реестр `@register("agent", "entity_dedup")`.
- **3.2.** Стартовый набор из F1.2 (6 агентов). LLM-агенты используют LLM gateway из 0.3, эвристические — нет.
- **3.3.** `Suggestion` хранится в БД, имеет статус `pending|accepted|rejected|expired`. Принятие suggestion = applies op в журнал из Phase 2.
- **3.4.** `POST /api/agents/:name/run?graph=...` (queued), SSE прогресс, `GET /api/suggestions?graph=...`.
- **3.5.** UI: панель «Suggestions» сбоку от графа: фильтр по агенту/типу действия, batch-accept выделенных, preview эффекта (diff-вид графа до/после).
- **3.6.** Журнал курации экспортируется JSON/CSV для воспроизводимого reporting в статье.

### Definition of Done
- Сценарий: запустить `EntityDeduplicator` на podcast → получить N suggestions → принять подмножество → видны изменения в графе и в QA-ответе.
- Каждый агент покрыт тестом «детерминистичный inputs → ожидаемые suggestions» с replay-LLM.

### Риски
- LLM-агенты дороги. Решение: квоты на агента, dry-run на сэмпле.

---

## 7. Phase 4 — Mixture-of-Experts reasoning (≈ 2 недели)

**Цель:** F3.

### Задачи
- **4.1.** Объединить GraphVariant'ы в `Corpus` (логически уже есть из Phase 0).
- **4.2.** `MoEReasoner.run(query, variants, reasoner_per_variant)` — параллельно запускает Reasoner на каждом GraphVariant.
- **4.3.** Aggregator-плагины: `LLMJudge`, `WeightedVote`, `EvidenceUnion`. Регистрируются как и остальные стратегии.
- **4.4.** API: `POST /api/reason` принимает `mode: single|moe`, `variants: [...]`, `aggregator: ...`. Стрим частичных ответов от каждого эксперта по SSE.
- **4.5.** UI: split-view (левый блок — финальный ответ + aggregator trace, правый — карточки экспертов с их evidence-подграфами).

### Definition of Done
- Один query, два варианта (Microsoft vs LightRAG builder) — UI показывает оба ответа, общую часть evidence и финальное обобщение. Скриншот пригоден для рисунка в статье.

### Риски
- Стоимость = k × stand-alone reasoning. Для UI-демо ограничить k ≤ 3 в дефолте, разрешить ручное расширение.

---

## 8. Phase 5 — Tools-on-nodes + GNN ranker (≈ 3 недели)

**Цель:** F5 + F6.

### 8a. Tools-on-nodes (F6)
- **5.1.** `NodeTool` интерфейс + реестр.
- **5.2.** Стартовые tools (см. F6.2): подключаются как отдельные плагины. Внешние API — поверх `httpx.AsyncClient` с rate-limit.
- **5.3.** Reasoner после ретрива составляет «tool menu» только из тулов узлов в evidence (не глобальный список). Системный промпт фиксирован, тулы передаются как список *описаний* + signature.
- **5.4.** `node.tool_outputs` — кеш с TTL, виден в side-drawer и используется как доп.evidence.
- **5.5.** UI: в детали узла добавлен раздел «Tools» с кнопками запуска и историей результатов.

### 8b. GNN ranker (F5)
- **5.6.** Подграф для query: kNN по embeddings + 2-hop expansion (как baseline сейчас). На этом подграфе запускаем GNN.
- **5.7.** Архитектура: 2-layer GAT (PyG), вход — node features (embedding + degree + layer one-hot), edge features (type + weight). Выход — relevance score для узлов.
- **5.8.** Обучение: synthetic queries из community reports (positive=узлы community, negative=случайные); скрипт `scripts/train_gnn.py` офлайн.
- **5.9.** Inference во время запроса. Fallback на cosine similarity, если модель отсутствует.
- **5.10.** Feedback-loop: пользователь может пометить узел в evidence как «irrelevant» — попадает в датасет для дообучения.

### Definition of Done
- Tools: для PERSON узла можно нажать «Wikidata lookup» и получить biographical short, который попадает в ответ при следующем запросе.
- GNN: в `/api/reason?ranker=gnn` precision@10 узлов на synthetic eval set ≥ baseline cosine + 5pp (минимум; точные числа уточним).

### Риски
- Обучение GNN на маленьких графах (~1k узлов) даёт неустойчивый сигнал. План: тренироваться на bag of graphs (podcast + gazeta + публичные ru-датасеты), inference per graph.
- Внешние tool API — ratelimit и обрывы. Граница ответственности: tool возвращает best-effort + пометку «degraded».

---

## 9. Phase 6 — UX (afina-style import + layered viewer) (≈ 3 недели)

**Цель:** F4 + F7. Делается последним сознательно: к этой фазе у нас уже есть реальные API (no fake stages), реальный multi-layer model в БД и MoE.

### Задачи
- **6.1.** Дизайн-система: токены (палитра/типографика/spacing) в `frontend/app/global.scss`. Рефакторинг текущих inline-стилей `index.vue` / `graph/[id].vue` в общие компоненты.
- **6.2.** Wizard import (F4.2 + F4.3 + F4.4): новая страница `pages/wizards/build.vue`. Шаги — отдельные компоненты, состояние через Pinia, синхронизировано в URL. Свободная back-навигация по breadcrumbs; зависимые шаги после правки помечаются «нужно подтвердить». Реальный SSE-прогресс из бэкенда. На каждом шаге — кнопка «спросить ассистента» → боковой чат, видит контекст шага.
- **6.3.** EDA-шаг визарда (F4.2 шаг 3): UI получает результат `backend/api/eda/` (Phase 0.8) и показывает рекомендации с опцией override. Карточки «обнаружено N документов, плотность сущностей X — рекомендуем Builder Y, типы PERSON/ORG/EVENT». Пользователь может добавить свои типы.
- **6.4.** Wizard reasoning (F4.5): страница `pages/wizards/ask.vue`, тот же шаговый паттерн с back-nav и чатом. Параллельно — оставить «быстрый» chat-bar над графом (как сейчас в `frontend/app/pages/graph/[id].vue:735-742`).
- **6.5.** Список Corpus / GraphVariants / Runs — карточки с фильтрами и статусами.
- **6.6.** **Layered Viewer (F7) — opacity-focus в существующем 2D-layout `@krainovsd/graph`.** Решение от 2026-05-03 (см. `docs/redesign/research/layered_graph_viz.md` §6.6, §7.1–§7.5). 2.5D / three.js отклонены — никаких новых render-зависимостей. Реализация:
  - **Итерация 1 (3–5 дней):** в backend каждому узлу/ребру проставляется `layer ∈ {chunk, entity, community, topic}`; в `@krainovsd/graph` (наш форк) добавляется prop `activeLayer` + opacity-функция; хоткеи `1`/`2`/`3`/`4`/`Tab` переключают `activeLayer`; неактивные слои рендерятся с alpha 0.15–0.25.
  - **Итерация 2 (3–4 дня):** хоткей `L` открывает Layer Map overlay (drag-reorder Z-stacking, opacity-слайдер на слой, slice-toggle); cross-layer selection (выбираешь entity → chunks/communities становятся непрозрачными даже в неактивных слоях).
  - Координация с автором `@krainovsd/graph`: какие фичи (`activeLayer` prop, layer-aware opacity hooks) идут в upstream-пакет, какие (Layer Map overlay UI, хоткеи) — в наш wrapper.
- **6.7.** Granularity slider + layer toggle + slice-mode + camera follow.
- **6.8.** Split-view для MoE-сравнения: два LayeredGraph рядом, синхронизированный selection (по `node.canonical_id`).
- **6.9.** Tools-panel в drawer (привязка к F6).
- **6.10.** Dark mode.
- **6.11.** Удалить hardcoded `http://192.168.135.118:8000` (`graph/[id].vue:494,517`) → `useRuntimeConfig().public.apiBase`.
- **6.12.** Снести `frontend/server/api/import.ts` (заглушка) — теперь визард ходит прямо в реальный backend.

### Definition of Done
- Полный flow: загрузил файлы → EDA-шаг показал рекомендации → собрал 2 варианта → запустил MoE-вопрос → увидел layered-граф, evidence в обоих вариантах, открыл узел, запустил tool, принял suggestion агента, переспросил.
- Свободно вернулся на Шаг 4, поменял Builder, увидел уведомление «шаги 5–7 нужно подтвердить», прошёл их заново.
- Спросил ассистента «почему этот узел оказался в community X?» прямо в чате — получил вменяемый ответ.
- Два «hero» скриншота для статьи: layered overview + MoE split.

### Риски
- Расширение `@krainovsd/graph` под layered-сценарий может оказаться больше планируемого. План B (записан, но не активирован): wrapper-компонент локально использует 3d-force-graph (MIT), а в `@krainovsd/graph` со временем мигрирует только консолидированный API. Решение принимается совместно с автором пакета по итогам research-доклада.
- Чат-affordance дешёв в реализации, но есть риск превратить его в «ещё один reasoner» — нужно сразу зафиксировать, что этот чат **не** трогает граф (только подсказки), иначе размывается граница с Reasoner-визардом.

---

## 10. Открытые вопросы → Resolved

Все Q1–Q10 закрыты. Снимаем их из числа блокеров и фиксируем здесь как ADR-light:

- **Q1 → Resolved.** Microsoft GraphRAG: **депрекейтим форк, берём как PyPI-зависимость** (вариант «б»). Локальные правки выносим в наши плагины. См. Phase 0 task 0.6 и `docs/redesign/decisions/0001-deprecate-graphrag-fork.md` (создаётся в Phase 0).
- **Q2 → Resolved.** **Дефолтный LLM — Deepseek.** Вся разработка и CI на нём. Yandex/OpenAI остаются как адаптеры за тем же gateway, но не блокируют разработку.
- **Q3 → Resolved.** MoE — **для статьи**. Реализуется в Phase 4. Production-вопросы (квоты, ratelimit, async batching, стоимость) сохранены в § Deferred ниже, чтобы не потерять.
- **Q4 → Resolved.** В Afina ценится: 1) явная пошаговость через все обязательные настройки, 2) свободная back-навигация без потери ответов, 3) чатовый ввод во время настройки. Эти три свойства зашиты в F4.3/F4.4 и в Phase 6 task 6.2.
- **Q5 → Resolved.** **Форкаем и расширяем `@krainovsd/graph`** (автор пакета — соавтор проекта). Конкретные изменения — после layered-viz research'а (фоновый агент пишет `docs/redesign/research/layered_graph_viz.md`). Координация с автором — отдельный пункт.
- **Q6 → Resolved.** **GNN обязателен** в R2. Phase 5 не сокращается.
- **Q7 → Resolved.** **pgvector — под вопросом** (известно медленный). Запускается отдельный research-task `docs/redesign/research/vector_store.md` (Phase 0 task 0.7). До результата — pgvector только как baseline за `VectorStoreProtocol`, чтобы потом легко заменить.
- **Q8 → Open (но не блокирует).** Источники для Tools-on-nodes пока не зафиксированы; стартуем с Wikidata + универсальных in-corpus тулов. HSE bibliography / Confluence — добавим как стретч.
- **Q9 → Resolved.** **Enum типов не фиксируется.** EDA-шаг визарда (F4.2 шаг 3, Phase 0 task 0.8 + Phase 6 task 6.3) после анализа корпуса предлагает стартовый набор типов и тулы под них. Пользователь может расширять.
- **Q10 → Resolved.** **Локальный single-instance деплой**, как сейчас. Multi-tenant и SaaS — out of scope.

---

## 11. Deferred — questions to revisit later (не потерять)

Всё, что сознательно отложено. Каждый пункт — кандидат на отдельный issue после закрытия R2.

### MoE production readiness (отложено после Phase 4)
- **D1.** Стоимость: MoE = k × single-graph cost. Какой бюджет токенов на запрос реалистичен для прод-демо? Нужны ли квоты на пользователя/корпус?
- **D2.** Async batching: запускать k экспертов параллельно — это k × QPS на LLM. Достаточно ли rate-limit Deepseek/Yandex? Нужна ли очередь с приоритизацией?
- **D3.** Кеширование MoE-ответов: как инвалидируется кеш при изменении одного из k графов? Хешируем по хешам всех вариантов в составе MoE или по запросу?
- **D4.** Aggregator-плагины: какой реально работает лучше на наших данных — LLM-судья vs weighted vote vs evidence-union? Нужен offline-eval перед прод-релизом.
- **D5.** UI для MoE при k > 3: split-view не масштабируется. Карусель? Группировка по похожим ответам?
- **D6.** Стриминг: можно ли начать показывать первого готового эксперта, пока остальные ещё думают?
- **D7.** Fallback-политика: что показываем, если 1 из k экспертов упал? Игнорировать, retry, понизить confidence?

### Прочее (низкий приоритет)
- **D8.** Tools-on-nodes: расширить за пределы Wikidata (HSE bibliography, Confluence, YaGPT-search) — после Phase 5.
- **D9.** Multi-user collaborative editing — после R2.
- **D10.** Импорт не-text источников (audio/video/PDF) — после R2.

---

## 12. Активные research-задачи

- **R-01. Layered graph visualization.** ✅ **Done** 2026-05-02. Отчёт + обновлённое решение: `docs/redesign/research/layered_graph_viz.md` §6.6, §7.1–§7.5.
  - **Финальное решение от 2026-05-03 (заменяет первичную рекомендацию):** 2.5D / 3D-реализация **отклонена**. Используем opacity-focus в существующем 2D-layout `@krainovsd/graph`. Никаких новых render-зависимостей; всё в форке пакета + наш wrapper. Дев-стоимость: 3–5 дней Итер 1 + 3–4 дня Итер 2 (вместо 1–2 недель × 3 итерации в первичной рекомендации).
  - **Контракт:** каждому узлу/ребру в backend проставляется `layer ∈ {chunk, entity, community, topic}`; UI получает хоткеи `1`/`2`/`3`/`4`/`Tab` для переключения активного слоя и `L` для Layer Map overlay (drag-reorder визуального Z-stacking, opacity-слайдеры, slice-toggle). Семантическая иерархия фиксирована данными, drag-reorder влияет только на отрисовку.
  - **Что отброшено:** `vasturiano/3d-force-graph`, голый three.js, sigma.js v3, cytoscape — все либо тянут новые зависимости, либо геометрически избыточны для нашего юзкейса.
  - **MoE side-by-side** — два инстанса 2D-вьюера рядом, синхронизированный selection (без необходимости mirror-linked камеры — viewport проще).
  - **⚠ Оговорка по первичной рекомендации:** в первой версии отчёта WebSearch/WebFetch были заблокированы политиками harness'а, агент работал по своему knowledge cutoff. Текущее решение принято на основе свойств уже имеющегося 2D-layout, а не сравнительных данных по 3D-либам — поэтому валидация фич сторонних либ перед демо не требуется.

- **R-02. Vector store selection.** ✅ **Done** 2026-05-03. Отчёт: `docs/redesign/research/vector_store.md` (~1114 строк, на русском, 10 разделов + Приложение A со skeleton `PgvectorAdapter`).
  - **Финальное решение от 2026-05-03 (override поверх первичной рекомендации):** **FAISS** + per-graph index pattern. Для нашего масштаба (≤50k vec total, ~3k на граф, single-instance) FAISS закрывает всё без отдельного сервиса; HNSW-проблема с удалением обходится полным rebuild на курацию (тривиально на 3k vec); фильтрация не нужна, потому что один индекс = один `(graph_variant_id, model)`. Подробности в Phase 0.7.
  - **Первичная рекомендация (для истории):** pgvector 0.7+ в той же PG-инстанции (Сценарий «а»). Обоснование: на 50k×1024 dim p95 ≈ 8–25 ms (запас 2× от лимита 50 ms). Откат к ней — простой, потому что `VectorStoreProtocol` сохраняем неизменным.
  - **Вариант B:** Qdrant standalone — активируется в R3 если потребуется hybrid search или объём перевалит ~1M vec.
  - **Отброшено или не подходит:** lancedb (embedded, проблемы с конкурентным доступом из FastAPI), chroma (детская перф-ниша, не для прода), weaviate/vespa (overkill для 50k vec), milvus (overkill + сложность ops), infinity (нишево). pgvecto.rs — рассмотрен, но pgvector 0.7 догнал по перфу для нашего размера и проще ставится.
  - **`VectorStoreProtocol` спроектирован** так, что бэкенд меняется в одном файле. Filter — алгебраический ADT (`Eq | In | And | Or | Not`), не SQL и не raw dict (объяснено почему). Hybrid search / reranking / streaming — **не в R2**, оставлены на R3.
  - **Multi-dim** — через таблицу-per-модель (`embeddings_e5_large`, `embeddings_bge_m3`, ...), потому что `vector(N)` требует фиксированной dim на колонку.
  - **DoD для Phase 0.7** прописан как чек-лист, включая mini-benchmark (50k × 1024 dim, p95 < 50 ms) — это отсекает риск №1, что pgvector 0.7 на filtered HNSW окажется хуже ожиданий.
  - **План миграции на другой backend** прописан явно (dual-write → backfill → сверка top-20 → флип флага). **Соответствующий outbox** заложен в Phase 2 task 2.1, чтобы потом не переписывать write-path.
  - **Russian-specific** раздел: e5-multilingual-large (1024), BGE-m3 (1024), LaBSE (768), sbert_large_nlu_ru (1024), Yandex Search API (256/1024) — все ложатся на pgvector без проблем.
  - **⚠ Оговорка:** WebSearch/WebFetch снова были заблокированы в sandbox-сессии. Цифры и фичи — по knowledge cutoff (январь 2026), помечены `[нужно проверить руками]` там, где источник неточен. Mini-benchmark в DoD как раз и закрывает этот риск.

---

## 13. Итог: следующий шаг

1. Дождаться результата R-01 (layered viz research) — будет автоматически уведомление, документ ляжет в `docs/redesign/research/`.
2. Запустить R-02 (vector store research).
3. Стартовать Phase 0 — фундамент (depreciation форка, domain model, LLM gateway с Deepseek, EDA-сервис).
