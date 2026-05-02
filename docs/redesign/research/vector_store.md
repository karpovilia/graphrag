# Vector Store для GraphRAG Explorer — research

> ## ⚠ Decision override (2026-05-03)
>
> **Финальный выбор для R2: FAISS + per-graph index pattern.** Это override поверх первичной рекомендации этого доклада (pgvector 0.7+). Доклад сохраняется ниже как research-фундамент: его сравнительная таблица, дизайн `VectorStoreProtocol`, план миграции и Russian-specific раздел остаются в силе и нужны для понимания контекста.
>
> **Почему FAISS:** для нашего масштаба (≤50k vec total, ~3k на граф, single-instance, без hybrid search в R2) FAISS закрывает всё без отдельного сервиса. Принцип «не выпендриваться» — собрать минимальный стек, не приносить новой зависимости там, где её можно избежать.
>
> **Форма:** один `IndexHNSWFlat` на каждое сочетание `(graph_variant_id, embedding_model)`. Это **одновременно решает** обе ключевые слабости FAISS:
> 1. отсутствие нативного metadata-фильтра — фильтр по `graph_variant_id` встроен в выбор индекса (один индекс = один граф);
> 2. плохое удаление в HNSW — на каждую курацию делается полный rebuild индекса (3k vec = доли секунды).
>
> **Что меняется в плане:**
> - Phase 0.7 — `FaissAdapter` вместо `PgvectorAdapter`; mini-benchmark из DoD заменён на rebuild-санити (3k×1024 < 2с, search < 5ms p95).
> - Phase 2.1 — outbox теперь триггерит rebuild индекса (с дебаунсом ~1с), а не sync-репликацию.
> - `VectorStoreProtocol` сохраняется без изменений — это единственная причина, почему R3 может вернуться к pgvector/Qdrant без переписывания call-site'ов.
>
> **Когда возвращаемся к R-02 рекомендациям:** R3, если потребуется hybrid search (vec + keyword), реал-тайм concurrent writes от нескольких процессов, или общий объём перевалит за ~1М векторов — переключаемся на Qdrant standalone (Вариант B доклада). Миграция через dual-write по outbox делает это дешёвым.
>
> Подробности интеграции — `docs/redesign/plan.md` § Phase 0.7 и § 12 R-02.
>
> ---

> Статус: research-доклад, май 2026.
> Аудитория: lead-разработчик (ki) + backend-команда HSE GraphRAG Explorer (демо SIGIR'26).
> ВАЖНО про источники: при подготовке этого доклада инструменты `WebSearch`/`WebFetch`
> оказались заблокированы политиками harness'а (та же ситуация, что в `layered_graph_viz.md`).
> Все факты, версии и числа ниже — по моему knowledge cutoff (январь 2026). Конкретные
> бенчмарк-цифры помечены как `[нужно проверить руками]`, если у меня нет источника, на
> который я могу сослаться по памяти. Перед финальным выбором в Phase 0.7 прогнать
> mini-benchmark локально (см. § 9.3, DoD).
> Релевантный контекст плана: `docs/redesign/plan.md` § 3 «Phase 0», задача 0.7. Этот
> документ — input для решения, который потом превратится в ADR `0002-vector-store-choice.md`.

---

## 1. Постановка

GraphRAG Explorer — single-instance open-source инсталляция (поднимается через
`docker-compose` рядом с Postgres, без SaaS-режима, без шардинга и репликации). Основной
корпус — HSE podcast на русском; на одну инсталляцию ожидается ~3k узлов на каждый
`GraphVariant` и до 10–20 параллельных вариантов на корпус, итого ~50k embedding'ов.
Параллельно используются несколько embedding-моделей (multilingual-e5-large 1024,
LaBSE 768, yandex-text-search 256/512, BGE-m3 1024 — точные размерности зависят от
выбора в Phase 0.3) → нужна поддержка **multiple collections с разными dim в одном
процессе**. Запросы фильтруются по `(graph_variant_id, layer, node_type)` — это горячий
путь, без него любая search-операция возвращает мусор из чужих графов. Курация графа
(`merge_nodes`, `split_node`, `move_to_community`, см. `plan.md` § 5 Phase 2) дёргает
**incremental upsert/delete на отдельных узлах** — индекс должен это переваривать без
перестроения. Целевой p95 для k=20 NN на warm cache — < 50 ms. Что **не нужно**:
горизонтальное масштабирование, миллиарды векторов, multi-region, multi-tenancy
(один процесс = одна инсталляция = один пользователь-команда).

Задача исследования: выбрать backend, сформулировать `VectorStoreProtocol`, оценить
риски и план миграции, если потом понадобится сменить.

---

## 2. Кандидаты

Для каждого кандидата: что это, лицензия, deployment, HNSW, metadata filtering,
multi-collection / multi-dim, цена incremental upsert, dev/ops стоимость.

### 2.1. pgvector (≥ 0.7, 0.8 в начале 2026)

- **Что**: расширение PostgreSQL, тип `vector(N)`, операторы `<->` (L2), `<#>` (inner
  product), `<=>` (cosine). С версии 0.5.0 — HNSW (раньше был только IVFFlat).
- **Лицензия**: PostgreSQL License (BSD-like), полностью OSS.
- **Deployment**: расширение к уже стоящему Postgres → `CREATE EXTENSION vector;`.
  Никакого нового сервиса. Идеально ложится на наш `docker-compose`.
- **HNSW**: да, с 0.5.0; параметры `m`, `ef_construction` на уровне индекса,
  `hnsw.ef_search` — на уровне сессии. С 0.7 параллельная сборка HNSW-индекса.
- **Metadata filtering**: обычный SQL `WHERE`. Это и плюс (выразительность),
  и минус (HNSW в pgvector ≤ 0.6 был известен «post-filter» проблемой:
  индекс возвращает k кандидатов, потом `WHERE` отфильтровывает → effective
  recall падает). В 0.7+ добавили **iterative index scans** (`hnsw.iterative_scan`),
  которые расширяют выборку до тех пор, пока не наберётся k after-filter
  результатов — это серьёзно меняет ситуацию против старых отзывов.
- **Multi-collection с разными dim**: тривиально — каждая коллекция = отдельная
  таблица или отдельная колонка с `vector(N)`. Можно даже одну таблицу с
  partial indexes по `model_name`, но проще — таблица per `(collection)`.
- **Incremental upsert**: дешёвый INSERT/UPDATE, HNSW-вставка O(log N) per item,
  delete — мягкое (мертвые tuples + VACUUM). Параллельные writes ОК.
- **Dev cost**: минимальный — у нас уже есть `asyncpg`/`SQLAlchemy`-стек, добавить
  `vector` тип через `pgvector-python` (5 минут работы).
- **Ops cost**: 0 — те же бэкапы, те же мониторинги, что и для остальных таблиц.
- **Минусы**: при больших N (100M+) проигрывает специализированным движкам,
  но у нас 50k — это в зоне, где разница нивелируется.

### 2.2. pgvecto.rs

- **Что**: альтернативное расширение Postgres, написанное на Rust (TensorChord).
  Цель — побить pgvector по latency/throughput за счёт SIMD и отдельного storage.
- **Лицензия**: Apache 2.0.
- **Deployment**: тоже расширение к Postgres, но **отдельный процесс-демон**
  (background worker), что усложняет упаковку. Готовый docker image
  `tensorchord/pgvecto-rs` есть.
- **HNSW**: да, плюс quantization (PQ, SQ).
- **Metadata filtering**: SQL `WHERE` + они вводят VBASE-подобный итеративный
  scan, который позиционируется как «более правильный pre-filter».
- **Multi-collection с разными dim**: как у pgvector, через таблицы.
- **Incremental upsert**: дешёвый, как и у pgvector.
- **Dev cost**: чуть выше — другой синтаксис создания индексов, отдельная
  логика для quantization (нам не нужна).
- **Ops cost**: больше, чем pgvector (отдельный демон, другой формат WAL для
  векторных данных, потенциальные проблемы при PG-апгрейдах).
- **Статус**: проект активный по моему cutoff, но менее зрелый, чем pgvector.
  По переписке в issues встречались случаи рассинхрона WAL и vector storage
  при крашах — для single-instance демо это приемлемый риск, но взвешенный.
- **Reality check**: проект **переименован в `vectorchord`** (точное название и
  миграционный путь — `[нужно проверить руками]`). Если используем — берём
  свежую версию.

### 2.3. Qdrant (standalone, Rust)

- **Что**: отдельный векторный сервис, единый бинарник на Rust. Один из самых
  популярных open-source vector DB.
- **Лицензия**: Apache 2.0.
- **Deployment**: docker image `qdrant/qdrant`, бинарник, persistence на диск,
  REST + gRPC API. Идеально для docker-compose.
- **HNSW**: да, основной индекс. Поддержка scalar/binary quantization.
- **Metadata filtering**: **payload filters first-class** — Qdrant строит
  индекс с учётом filter (через payload index), что даёт правильный pre-filter,
  а не post-filter. Это исторически их преимущество над pgvector.
- **Multi-collection с разными dim**: коллекция = отдельный конфиг с своей dim,
  своей метрикой. Tens of collections в одном процессе — норма.
- **Incremental upsert**: O(log N) HNSW insert, soft delete + optimizer
  (фоновая компакция). Транзакции — atomic per point batch.
- **Dev cost**: `qdrant-client` (Python, async) хорош, типизирован, активно
  развивается. Чуть-чуть больше boilerplate, чем pgvector (нужно описывать
  collection schema и filter DSL).
- **Ops cost**: отдельный сервис в compose, отдельный том, отдельный backup.
  Но ничего сложного.
- **Прод-зрелость**: высокая, есть managed cloud, известные prod-инсталляции.

### 2.4. Milvus (standalone Lite + полный, Go/C++)

- **Что**: тяжелый distributed vector DB. Есть **Milvus Lite** (embedded,
  Python-only, `milvus-lite` через pip, single-process, persists в файл — с
  2024 года) и **полный Milvus** (Pulsar/Kafka, etcd, MinIO, несколько
  компонентов).
- **Лицензия**: Apache 2.0.
- **Deployment**: Lite — embedded, идеально для прототипов; полный — серьезно
  тяжелее любого другого кандидата (etcd + object storage + MQ обязательны).
- **HNSW**: да, плюс IVF, DiskANN, SCANN.
- **Metadata filtering**: scalar filters через выражения (`field == "x"`),
  поддержка hybrid search.
- **Multi-collection с разными dim**: ОК.
- **Incremental upsert**: ОК для Lite. Полный Milvus имеет лаги между insert
  и searchable (флашится через MQ), что для нашего курации-цикла нежелательно.
- **Dev cost**: `pymilvus` норм. Filter DSL через строки выражений (как у
  ElasticSearch, чуть менее красиво, чем Qdrant).
- **Ops cost**: Lite — нулевая. Полный — самая высокая среди всех кандидатов;
  для single-instance демо это overkill.
- **Вердикт по полному Milvus**: **отбрасываем** для нашего сценария
  (overkill). Lite остаётся в рассмотрении.

### 2.5. LanceDB (embedded, columnar, Rust)

- **Что**: embedded vector DB, основан на формате Lance (columnar, OLAP-friendly,
  замена Parquet для ML). Идея: вместо отдельного сервиса — файлы на диске,
  читаются in-process. Развивается компанией Lance/Eto Labs.
- **Лицензия**: Apache 2.0.
- **Deployment**: pip install, библиотека, никакого сервера. Persistence — папка
  с lance-файлами. Идеально для docker-compose: монтируешь том, и всё.
- **HNSW**: есть, плюс IVF_PQ. По умолчанию они продвигают IVF_PQ; HNSW
  поддержка добавлена позже и менее зрелая, но **рабочая** на наших объёмах.
- **Metadata filtering**: SQL-выражения через DataFusion (Apache Arrow
  query engine). Pre-filter работает корректно благодаря columnar storage —
  фильтр по метадате не требует full scan вектора.
- **Multi-collection с разными dim**: каждая коллекция = отдельный table в
  одной db (папке), с своим schema.
- **Incremental upsert**: есть `merge_insert`/`upsert`, но Lance — append-friendly
  format; частые мелкие upserts создают мелкие фрагменты, нужен periodic
  `optimize()` (compaction). Для курации (1 update / минуту) — приемлемо,
  если запускать optimize в фоне раз в N минут.
- **Dev cost**: API простой и приятный, async-обертки появились. Меньше
  boilerplate, чем Qdrant.
- **Ops cost**: нулевая (нет сервиса). Бэкап = `tar` папки.
- **Прод-зрелость**: средняя — растёт, но младше Qdrant/Milvus. Для read-heavy
  embedded use-case (наш) — подходит.

### 2.6. Infinity (search engine)

- **Что**: AI-native поисковый движок от InfiniFlow (создатели RAGFlow).
  Hybrid search (vector + sparse + full-text), columnar storage. Ставится как
  отдельный сервис или embedded.
- **Лицензия**: Apache 2.0.
- **Deployment**: docker image; embedded mode заявлен.
- **HNSW**: да, плюс IVF, FullText (BM25). Главный selling point — native
  combo «vector + BM25 + sparse» в одном запросе.
- **Metadata filtering**: SQL.
- **Multi-collection с разными dim**: ОК.
- **Incremental upsert**: есть, но движок относительно новый.
- **Dev cost**: Python client есть; качество async, типизация — `[нужно
  проверить руками]`. Знаю проект как часть RAGFlow-стека, отдельно
  использовался реже.
- **Ops cost**: ещё один сервис; меньше прод-инсталляций, чем у Qdrant/Milvus.
- **Релевантность нам**: интересен, **если** мы в R2 захотим hybrid search
  (vector + BM25 на русском). Тогда Infinity становится одним из немногих
  кандидатов, где это «из коробки». Иначе — Qdrant + ручной BM25 проще.

### 2.7. Chroma (embedded/server, Python)

- **Что**: embedded vector store, ставший популярным благодаря интеграции с
  LangChain. Server-mode тоже есть.
- **Лицензия**: Apache 2.0.
- **Deployment**: pip install, single-process; server mode — docker image.
- **HNSW**: да, через `hnswlib` под капотом.
- **Metadata filtering**: where-DSL (dict-подобный).
- **Multi-collection с разными dim**: ОК.
- **Incremental upsert**: есть, но **исторически** были проблемы с persistence
  и случаями потери данных при unclean shutdown (на 2023–24); по моему cutoff
  ситуация улучшилась, но репутация осталась. `[проверить руками текущий
  статус 0.5+]`.
- **Dev cost**: API очень простой, отличный «прототипер».
- **Ops cost**: нулевой (embedded), но prod-зрелость я бы оценил ниже Qdrant
  и Milvus.
- **Релевантность нам**: хорош для прототипов, но для финального выбора в R2
  — рискованно.

### 2.8. Weaviate (standalone, Go)

- **Что**: серьёзный opensource vector DB с GraphQL/REST API, модулями для
  embedding-pipelines.
- **Лицензия**: BSD-3.
- **Deployment**: docker, single binary, persistence на диск.
- **HNSW**: да.
- **Metadata filtering**: where-фильтры в GraphQL/REST.
- **Multi-collection с разными dim**: classes c разными vectorizer'ами.
- **Incremental upsert**: ОК.
- **Dev cost**: Python-клиент (`weaviate-client`) развит, но GraphQL DSL
  тяжелее, чем Qdrant filters. Modules-архитектура иногда мешает (хотим
  чистый vector store, а получаем opinionated framework).
- **Ops cost**: средний — отдельный сервис.
- **Релевантность нам**: пересекается с Qdrant по нише, но **сложнее на
  ровном месте** для нашего use-case.

### 2.9. Vespa (standalone, JVM)

- **Что**: poweful поисковый/ranking-движок от Yahoo. Vector + ranking +
  ML-ranking + structured data в одном.
- **Лицензия**: Apache 2.0.
- **Deployment**: JVM, требует config-app, отдельный admin-cycle. Есть docker.
- **HNSW**: да, плюс много других индексов.
- **Metadata filtering**: YQL — собственный язык.
- **Multi-collection с разными dim**: schemas с разными tensor types.
- **Incremental upsert**: ОК, индекс online-mutable.
- **Dev cost**: **высокий** — Vespa имеет крутую кривую обучения, JVM-стек,
  config-pack модель. Для команды без Vespa-опыта — это месяц на освоение.
- **Ops cost**: высокий — JVM, отдельный operator, специфичные тулинги.
- **Прод-зрелость**: максимальная (Yahoo, Spotify ranking, многие LLM-search
  prod-инсталляции).
- **Релевантность нам**: **отбрасываем** — пушка по воробьям. Vespa имеет
  смысл, когда нужен сложный ranking pipeline на сотнях миллионов докуметов.

### 2.10. Typesense (для сравнения)

- **Что**: search engine, в первую очередь полнотекстовый, с vector-search в
  довесок.
- **Лицензия**: GPL-3 (важно для OSS-распространения!).
- **Deployment**: single binary, docker.
- **HNSW**: да, но не основной фокус.
- **Metadata filtering**: ОК.
- **Multi-collection с разными dim**: collections.
- **Incremental upsert**: ОК.
- **Dev cost**: API простой.
- **Ops cost**: средний.
- **Релевантность нам**: GPL-3 для OSS-проекта в репозитории — нюанс
  лицензионной чистоты (заражает производные, если линкуем). Для vector-only
  use-case проигрывает Qdrant. **Отбрасываем.**

### 2.11. FAISS + SQLite (DIY)

- **Что**: библиотека от Facebook AI (CPU/GPU ANN), один из самых быстрых
  индексов. SQLite — для метаданных и id-mapping.
- **Лицензия**: MIT (FAISS).
- **Deployment**: pip install, всё в процессе.
- **HNSW**: да (`IndexHNSWFlat`), плюс куча других.
- **Metadata filtering**: **нет нативного** — фильтры реализуются вручную
  через `IDSelector` или post-filter после search.
- **Multi-collection**: каждая коллекция — отдельный `Index`, в память
  загружаешь сам.
- **Incremental upsert**: HNSW в FAISS **add-only** для большинства сценариев;
  delete возможен через `IDSelector`, но индекс degradates со временем →
  rebuild периодически. Для нашей курации (частые точечные delete + reinsert)
  это **минус**.
- **Dev cost**: сами пишем persistence (pickle/np.save/sqlite), сами решаем
  concurrency, сами обрабатываем filters. **2–4 недели качественной работы**
  для нормального wrap'а.
- **Ops cost**: низкий по запуску, но багованность собственной обвязки —
  риск.
- **Релевантность нам**: имеет смысл, **только если** все остальные
  не подойдут по перформансу. Для 50k векторов это не наш случай.

---

## 3. Сравнительная таблица

| Кандидат | License | Single-binary | Compose-friendly | Multi-dim | Filter perf | HNSW recall | Incr. upsert | ~Disk @ 50k×1024 fp32 | RAM idle | Python client | Prod-зрелость |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pgvector 0.7+ | PG-License | embedded в PG | да (PG уже есть) | да (per-table) | OK с iterative scans, было плохо до 0.6 | хорошая | дешёвый | ~250 MB (vec+ind) | в общем PG | `pgvector-python` | высокая |
| pgvecto.rs / vectorchord | Apache-2 | в PG + bg-worker | да | да | хорошая | хорошая | дешёвый | ~250 MB | +200–400 MB | ОК | средняя |
| Qdrant | Apache-2 | да | да | да | **отличная** (payload index) | хорошая | дешёвый | ~250–400 MB | ~150–300 MB | отличный, async | высокая |
| Milvus Lite | Apache-2 | embedded | да (или embedded) | да | хорошая | хорошая | ОК | ~300 MB | ~100 MB | `pymilvus` | средняя (Lite); полный — высокая |
| Milvus full | Apache-2 | НЕТ (etcd+MQ+S3) | сложно | да | хорошая | хорошая | с лагом | overkill | 1–2 GB | `pymilvus` | высокая |
| LanceDB | Apache-2 | embedded | да | да | хорошая | средняя (HNSW моложе IVF_PQ) | ОК + compaction | ~250 MB | ~50 MB | хороший, async | средняя |
| Infinity | Apache-2 | да | да | да | хорошая | хорошая | ОК | ~300 MB | ~200 MB | средний | средняя |
| Chroma | Apache-2 | embedded/server | да | да | средняя | средняя | ОК | ~300 MB | ~100 MB | простой | средняя (с оговорками) |
| Weaviate | BSD-3 | да | да | да | хорошая | хорошая | дешёвый | ~300 MB | ~300–500 MB | OK, GraphQL-привкус | высокая |
| Vespa | Apache-2 | НЕТ (config-app) | сложно | да | отличная | отличная | дешёвый | overkill | 1+ GB JVM | средний | максимальная |
| Typesense | GPL-3 | да | да | да | средняя | средняя | ОК | ~300 MB | ~200 MB | OK | средняя |
| FAISS+SQLite | MIT+PD | embedded | да | руками | руками | отличная | плохой (rebuild) | ~200 MB | ~150 MB | сами пишем | высокая (lib), низкая (наша обвязка) |

Цифры по диску — оценки `50000 × 1024 × 4 байт ≈ 195 MB на raw vectors`,
плюс HNSW-граф добавляет ~30–80% сверху. Это близко для всех и не должно
влиять на выбор. **`[все цифры RAM/disk — порядок величины, не точные;
проверить руками на mini-benchmark]`**.

---

## 4. Бенчмарки

Ниже — что я **помню** из публичных источников по моему cutoff. Все числа —
порядок величины, а не точные. Перед финальным выбором прогнать локально.

### 4.1. ann-benchmarks.com

Канонический сравнительный сайт (Erik Bernhardsson + сообщество). Датасеты:
glove-100, sift-1M, deep-image-96, gist-960. На профиле, близком к нашему
(<1M vectors, recall@10 ≥ 0.95):
- **HNSWlib / FAISS HNSW** — стабильно в топе по QPS/recall trade-off.
- **Qdrant** — близко к топу, в реальных условиях с фильтрами часто лучше
  per-engine за счёт filter-aware index.
- **pgvector до 0.5** — заметно слабее остальных; с 0.5+ (HNSW) подтянулся.

`[нужно проверить актуальную версию results.html — конкретные QPS меняются
от прогона к прогону]`.

### 4.2. qdrant /benchmarks (vendor-published, но open-source code)

Qdrant публикует filterable-ann-benchmark с отрытым кодом. Их выводы
(с учётом vendor-bias):
- При фильтре с низкой селективностью (мало вариантов значений) Qdrant
  держит p95 в десятках мс на 1M; при высокой селективности (много фильтров,
  малая доля результатов) — преимущество ещё больше.
- pgvector в их прогонах исторически проигрывал в 3–10 раз на filtered
  search. Но это **до 0.7** и до iterative scans.

### 4.3. vectordb-bench (Zilliz, с поправкой на vendor-bias)

Zilliz (Milvus) публикует vectordb-bench. Их прогоны на 1M cohere-768:
- Milvus / Qdrant / Weaviate / Pinecone — все в одной лиге на recall=0.95.
- Latency p99 < 10 мс на 1M для топ-3.

Для 50k вся группа лидеров фактически одинакова — bottleneck становится
не ANN, а round-trip и сериализация.

### 4.4. lancedb-блог

LanceDB публиковал прогоны на columnar-friendly workload (read-heavy, мало
upsert'ов). На 1M dim=768 заявляют p95 < 10 мс с фильтрами. На 50k у нас
запас минимум 2–3x.

### 4.5. Что важно для нас

На **50k векторов** ВСЕ кандидаты, кроме совсем экзотики, спокойно дают
p95 < 50 мс (наш target). Bottleneck перестаёт быть ANN-движок и становится:
1. **Network/IPC overhead** (для standalone) — RTT до localhost обычно 0.2–1 мс.
2. **Filter pre/post**: если backend делает post-filter, recall падает,
   приходится увеличивать k → растёт latency. Это критично для pgvector
   <0.7 и для FAISS-DIY.
3. **Сериализация python-клиента** (pickle/protobuf/msgpack).

### 4.6. Что НЕ работает в нашу пользу

- pgvector до 0.6 показывал плохие результаты на filtered-HNSW; в 0.7+ всё
  улучшилось, но публичных бенчмарков «pgvector 0.7 vs Qdrant с фильтрами»
  по моему cutoff было мало. **Это главный пункт, который надо проверить
  руками** в рамках 0.7.
- LanceDB HNSW — относительно молодая фича; их «main» индекс — IVF_PQ.

---

## 5. PostgreSQL-интеграция

У нас уже стоит PG для всего: domain model (Corpus / GraphVariant / Node /
Edge / Suggestion / Run / JournalEntry — см. `plan.md` § 0.1), prompt history,
Alembic миграции. Это ключевой контекст.

### 5.1. Сценарий (а): pgvector в той же БД

**Плюсы**:
- 0 новых сервисов в compose.
- JOIN'ы между `nodes` и `node_embeddings` — нативный SQL, без ручной
  синхронизации id.
- Транзакционность: вставил Node + embedding в одной транзакции — оба
  закоммитились вместе. **Огромный плюс** для журнала курации (никаких
  «embedding сделался, а node не сохранился»).
- Бэкап один — `pg_dump`.
- Метаданные `(graph_variant_id, layer, node_type)` — те же самые столбцы,
  по которым у нас уже есть btree-индексы для других запросов. Reuse.

**Минусы**:
- Перформанс vs специализированных движков (см. § 4).
- При большом write-volume vector-операции могут начать конкурировать с
  OLTP-нагрузкой. У нас нагрузка низкая → не проблема.

**Когда выбираем**: **по умолчанию для нашего профиля.** 50k векторов,
филтр всегда по 2–3 столбцам с высокой селективностью (один graph_variant
из ~20 в среднем = ~5% выборки), курация → точечные upserts → PG это
переварит. ВАЖНО: использовать pgvector **0.7+** ради `iterative_scan` для
filtered HNSW.

### 5.2. Сценарий (б): pgvecto.rs / vectorchord в той же БД

**Плюсы**:
- Производительность ближе к standalone Qdrant.
- Всё ещё в PG — транзакции, бэкапы, JOIN'ы.

**Минусы**:
- Менее зрелое расширение, отдельный bg-worker, риск рассинхрона при крашах.
- Переименование/миграция (pgvecto.rs → vectorchord) добавляет
  неопределённости.
- ROI неочевиден: если pgvector 0.7 переваривает наши 50k за < 50 мс p95,
  то выигрыш от pgvecto.rs — теоретический.

**Когда выбираем**: если **mini-benchmark в DoD 0.7** покажет, что pgvector
не справляется. Тогда pgvecto.rs/vectorchord — упрощённый шаг (всё ещё PG,
не отдельный сервис).

### 5.3. Сценарий (в): внешний vector store (Qdrant) + PG для метаданных

**Плюсы**:
- Лучший filter performance на сегодня (Qdrant payload index).
- Изоляция от PG (vector load не мешает OLTP).
- Отдельный backup-цикл, отдельный мониторинг.

**Минусы**:
- **Нет распределённых транзакций между PG и Qdrant.** Если node вставлен
  в PG, а embedding в Qdrant упал — рассинхрон. Решается outbox-паттерном
  (запись в PG outbox-таблицу + воркер, переносящий в Qdrant), но это
  +кода.
- **Курация-цикл** (merge → пересчитать community → пересчитать embedding
  → upsert) теряет атомарность. Падающие частично-пересчитанные операции
  — мусор в индексе.
- +1 сервис в compose, +1 том, +1 backup.
- На 50k векторов перф-выигрыш не оправдывает сложности.

**Когда выбираем**: если хочется hybrid-search или планируется рост
до 1M+ векторов. У нас по тз-roadmap этого не ожидается.

### 5.4. Сценарий (г): LanceDB embedded рядом с PG

**Плюсы**:
- Нет отдельного сервиса.
- Отличная скорость на 50k.
- Файлы лежат на диске, можно периодически копировать (бэкап).

**Минусы**:
- **Та же проблема атомарности**, что в (в): PG и LanceDB — два разных
  storage, единой транзакции нет. Outbox / 2PC / event log как митигация.
- Меньше прод-зрелости.
- Lance-формат — append-friendly, нужны periodic compactions; для нашего
  курация-цикла это +фоновая задача.

**Когда выбираем**: если pgvector проигрывает по latency, **и** мы готовы
платить за двухстораджную атомарность. Промежуточный вариант между
«всё в PG» и «отдельный сервис».

### 5.5. Вердикт по интеграции

В порядке предпочтения для нашего профиля:
1. **pgvector 0.7+ в той же БД** (а) — default.
2. pgvecto.rs/vectorchord (б) — fallback, если (а) не вытянет.
3. Qdrant standalone (в) — fallback второго уровня, если (а) и (б) не
   подходят и нужен hybrid search.
4. LanceDB (г) — нишевый вариант, в первую очередь при росте read-heavy
   нагрузки и желании уйти от server-сайдеров.

---

## 6. VectorStoreProtocol

Сразу строим интерфейс, чтобы выбор бэкенда не пропитывал код. Все
backend-специфичные особенности скрываем.

### 6.1. Базовые типы

```python
# backend/api/vector_store/types.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence

Metric = Literal["cosine", "l2", "ip"]


@dataclass(frozen=True, slots=True)
class VecItem:
    id: str                          # UUID или f"{graph_variant_id}:{node_id}:{model}"
    vector: Sequence[float]
    metadata: dict[str, Any]         # {"graph_variant_id": "...", "layer": "entity",
                                     #  "node_type": "Person", "model": "e5-large"}


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: str
    score: float                     # higher is better для cosine/ip;
                                     # для l2 переворачиваем в адаптере
    metadata: dict[str, Any]
    vector: Sequence[float] | None   # опционально, по запросу


# Filter DSL (см. § 6.2)
@dataclass(frozen=True, slots=True)
class Eq:
    field: str
    value: Any

@dataclass(frozen=True, slots=True)
class In:
    field: str
    values: Sequence[Any]

@dataclass(frozen=True, slots=True)
class And:
    clauses: Sequence["Filter"]

@dataclass(frozen=True, slots=True)
class Or:
    clauses: Sequence["Filter"]

@dataclass(frozen=True, slots=True)
class Not:
    clause: "Filter"

Filter = Eq | In | And | Or | Not
```

### 6.2. Filter DSL — почему не SQL и не raw dict

**Не SQL**, потому что:
1. Qdrant/Weaviate/Chroma не понимают SQL — нужен переводчик на их DSL.
2. SQL injection surface при ручной конкатенации.
3. SQL слишком выразителен (joins, subqueries, functions) — backend'ы это
   не покроют, превратится в leaky abstraction.

**Не raw dict** (как у Chroma), потому что:
1. Без типов легко напороться на runtime-ошибки.
2. Нет статического анализа.

**Алгебраический ADT** (`Eq | In | And | Or | Not`) — минимальное достаточное
ядро. Все наши кейсы покрываются:

```python
# WHERE graph_variant_id = 'g1' AND layer = 'entity' AND node_type IN ('Person', 'Org')
And([
    Eq("graph_variant_id", "g1"),
    Eq("layer", "entity"),
    In("node_type", ["Person", "Org"]),
])
```

Каждый адаптер бэкенда реализует `_translate(filter: Filter) -> BackendNative`:
- pgvector: → SQL `WHERE` clause + parameter list.
- Qdrant: → `qdrant_client.models.Filter` (must / should / must_not).
- LanceDB: → SQL-выражение для DataFusion.
- Milvus: → `expr` строка.

Если в будущем понадобятся `Range`, `Contains`, `IsNull` — добавляем в ADT
и в каждый адаптер. Range проектируем заранее (нужен будет для timestamp-filter):

```python
@dataclass(frozen=True, slots=True)
class Range:
    field: str
    gte: Any | None = None
    lte: Any | None = None
```

### 6.3. Сам Protocol

```python
# backend/api/vector_store/protocol.py
from typing import Protocol, Sequence
from .types import VecItem, SearchHit, Filter, Metric


class VectorStoreProtocol(Protocol):
    async def create_collection(
        self,
        name: str,
        dim: int,
        metric: Metric = "cosine",
        # backend-specific tunings — опционально, через **opts;
        # дефолты держим в адаптере.
    ) -> None: ...

    async def drop_collection(self, name: str) -> None: ...

    async def list_collections(self) -> list[str]: ...

    async def upsert(
        self,
        collection: str,
        items: Sequence[VecItem],
        *,
        batch_size: int = 256,
    ) -> None:
        """Идемпотентно: если id уже есть — переписывает."""

    async def delete(
        self,
        collection: str,
        ids: Sequence[str],
    ) -> None: ...

    async def search(
        self,
        collection: str,
        vector: Sequence[float],
        k: int = 20,
        filter: Filter | None = None,
        *,
        with_vectors: bool = False,
        ef_search: int | None = None,   # backend-hint, ignored если не HNSW
    ) -> list[SearchHit]: ...

    async def count(
        self,
        collection: str,
        filter: Filter | None = None,
    ) -> int: ...

    async def health(self) -> dict: ...   # для /readyz
```

### 6.4. Что НЕ кладём в протокол в R2

- **Hybrid search (vec + BM25)**. R2-MVP не требует. Если позднее
  добавим — отдельный метод `search_hybrid` или новый Protocol
  `HybridVectorStoreProtocol`, чтобы не ломать текущий контракт.
- **Multi-vector / late-interaction (ColBERT-style)**. Вне scope.
- **Reranking**. Отдельный сервис, не внутри vector store.
- **Streaming search results (server-sent)**. У нас k=20, всё помещается.

### 6.5. Транзакционность и batching

- **Не пытаемся** делать кросс-стораджные транзакции PG ↔ vector store
  (если выберем внешний бэкенд). Вместо этого — **outbox pattern**:
  пишем `pending_embedding(node_id, op, payload)` в PG в одной транзакции
  с node-write; отдельный воркер дренирует outbox в vector store с
  retries. Идемпотентность гарантируется одинаковыми `VecItem.id`.
- **Batching**: `upsert` принимает Sequence; внутри адаптера — разбиение
  на чанки по `batch_size` (256 default). Для pgvector — один `INSERT
  ... ON CONFLICT DO UPDATE` per batch.
- **Backpressure**: search не имеет; upsert — в воркере; semaphore на
  N concurrent calls per backend instance. Дефолт 4.

### 6.6. Тестирование протокола

Один общий тест-кит (parametrize по бэкендам), запускается в CI с
docker-compose-fixture:

```python
@pytest.mark.parametrize("backend", ["pgvector", "qdrant", "lancedb"])
async def test_search_with_filter_returns_only_matching_variant(backend, vs):
    await vs.create_collection("e5_large", dim=1024)
    await vs.upsert("e5_large", [
        VecItem("a", [...], {"graph_variant_id": "g1", "layer": "entity"}),
        VecItem("b", [...], {"graph_variant_id": "g2", "layer": "entity"}),
    ])
    hits = await vs.search("e5_large", [...], k=5,
                           filter=Eq("graph_variant_id", "g1"))
    assert {h.id for h in hits} == {"a"}
```

В Phase 0.7 реализуем **минимум один** адаптер (pgvector) и тест-кит.
Остальные адаптеры — по необходимости.

---

## 7. Перформанс-симуляция (топ-3 кандидата)

Профиль: **50k векторов, dim=1024, k=20, фильтр = `graph_variant_id == 'X' AND
layer == 'entity'`** (селективность фильтра ~5%, т. е. ~2.5k подходящих
из 50k). Cosine distance. Warm cache (rss > index size).

Ниже — **прикидки**, не измеренные числа. Числа — порядок величины.

### 7.1. pgvector 0.7+ (HNSW + iterative_scan)

- HNSW-обход в самом индексе: на 50k и `ef_search=200` — ~2–5 ms.
- Iterative scan для pre-filter (5% селективность): множитель 1.5–3x
  на ANN-проход → 4–15 ms.
- SQL planner overhead, prepared statement cache hit: 1–2 ms.
- Network через unix socket / localhost: < 0.5 ms.
- Сериализация asyncpg → Python: 1 ms.
- **Итого p95 ≈ 8–25 ms**. Запас до нашего лимита 50 ms — 2x.

Источник прикидок: знание архитектуры HNSW и порядка величины из
pgvector benchmark issues на github (`[нужно прогнать локально на своём
железе]`). Главный риск — селективность фильтра. Если будут запросы с
фильтром «один graph_variant из 100», iterative scan может расширяться до
10x bigger ef → latency 30–60 ms. Это близко к лимиту, нужно держать в
голове.

### 7.2. Qdrant standalone

- Filterable HNSW (payload-index): фильтр учитывается **внутри** обхода
  графа → лишних расходов нет.
- HNSW обход на 50k и `hnsw_ef=128`: ~2–4 ms.
- gRPC сериализация (protobuf): 1–3 ms на k=20 с 1024-dim возвратом.
- Localhost network: < 0.5 ms.
- **Итого p95 ≈ 4–10 ms**. Очень комфортно.

Источник: qdrant /benchmarks для filtered-ann на cohere-1M, экстраполяция
на 50k. На малых N разница с pgvector нивелируется до round-trip.

### 7.3. LanceDB embedded (HNSW)

- HNSW в LanceDB: ~3–6 ms.
- DataFusion фильтр на columnar metadata: 0.5–2 ms.
- Никакой сериализации, in-process.
- **Итого p95 ≈ 4–10 ms**. Сопоставимо с Qdrant.

Источник: lancedb блог-посты с замерами на 1M, экстраполяция. Главное
ограничение — частые upserts создают фрагменты, search latency растёт
без compaction. Если запускать `optimize()` раз в 5 минут или после
N upserts — ОК.

### 7.4. Вывод по перформансу

**Все три кандидата проходят наш target 50 ms с большим запасом** на
50k векторов. Перф-разница < 20 ms между ними, что несущественно для
демо-демонстрации. Решение **должно идти от dev/ops cost**, а не от перфа.

---

## 8. Russian-specific: embeddings и их размерности

Что важно для русского + наших vector store кандидатов:

### 8.1. Кандидаты embedding-моделей для русского

| Модель | dim | Длина контекста | Лицензия | Заметки |
|---|---|---|---|---|
| `intfloat/multilingual-e5-large` | 1024 | 512 tok | MIT | Хороший baseline, поддержка ru. Использовать с префиксами `query: ` / `passage: `. |
| `intfloat/multilingual-e5-base` | 768 | 512 tok | MIT | Дешевле, recall чуть ниже. |
| `sentence-transformers/LaBSE` | 768 | 512 tok | Apache-2 | 100+ языков, цит. cross-lingual sentence sim. |
| `BAAI/bge-m3` | 1024 | 8192 tok | MIT | Best-in-class по моему cutoff, **dense+sparse+colbert** в одной модели. Для длинных чанков — лучший выбор. |
| `cointegrated/rubert-tiny2` | 312 | 512 tok | MIT | Очень дешёвый, для baseline / draft. |
| `ai-forever/sbert_large_nlu_ru` | 1024 | 512 tok | MIT | Спец. для русского. |
| Yandex SearchAPI text-search | 256/512 | API | proprietary | Платный, через API (latency ~300 ms на запрос). |

В R2 я бы рекомендовал стартовать с `multilingual-e5-large` (1024) как
default, и сразу зарезервировать слот для `bge-m3` (1024), т. к. он
лучше держит длинные чанки (важно для transcript-based корпуса HSE
podcast, где фрагменты бывают длинными).

### 8.2. Влияние на vector store

- **dim=1024** — все кандидаты переваривают без проблем. Memory footprint
  (50k × 1024 × 4 byte ≈ 200 MB raw) не критичен ни для одного.
- **Multiple models одновременно** — у нас целевая поддержка нескольких
  моделей (e5-large 1024, LaBSE 768, BGE-m3 1024). Решение:
    - pgvector / pgvecto.rs / lancedb / milvus / qdrant — все поддерживают
      «collection per model» из коробки. **Ок.**
    - Convention: имя коллекции = `embeddings_{model_short_name}`,
      например `embeddings_e5_large`, `embeddings_bge_m3`.
- **Length-3000+ vectors** для каких-нибудь экзотических моделей —
  не наш случай, но если понадобится: pgvector ограничен 16000-dim в
  типе `vector`, а индекс HNSW работает до 2000-dim (для больше — IVFFlat
  или quantization). У нас 1024 — далеко от потолков.
- **Quantization для русского** — не требуется на 50k. На 1M+ имеет
  смысл смотреть scalar quantization (PQ ухудшает recall на агглютинативно-
  богатых языках сильнее, чем на английском, по эмпирическим наблюдениям;
  `[нужно проверить руками]`).

### 8.3. Hybrid search (vec + BM25 для русского)

Если в R2 решим делать hybrid:
- Нужен правильный токенайзер для русского (морфология). PG `tsvector`
  с `'russian'` config — рабочий baseline. Qdrant поддерживает sparse
  vectors, можно загнать BM25 туда. Infinity и Vespa делают это «из
  коробки», но overkill.
- В R2-MVP **не делаем**. Если стартуем с pgvector, hybrid позже легко
  достраивается через `tsvector`-колонку рядом с `vector`-колонкой и
  RRF на стороне приложения.

---

## 9. Рекомендация

### 9.1. Основной выбор для R2

**pgvector 0.7+ в той же PG-инстанции (Сценарий «а» из § 5).**

Обоснование:
1. **Перф проходит target.** Даже худший прикидочный p95 (~25 ms) с запасом
   2x относительно лимита 50 ms на нашем профиле 50k × 1024 dim. См. § 7.1.
2. **Транзакционность.** Курация графа (`merge_nodes`, `split_node`,
   `move_to_community`) — это последовательность изменений Node + edge +
   embedding в одной семантической транзакции. С внешним vector store эта
   транзакционность теряется и приходится строить outbox-паттерн. С
   pgvector — одна `BEGIN ... COMMIT` транзакция.
3. **Ноль новых сервисов.** Docker-compose остаётся минимальным
   (frontend + backend + postgres). Это значимо для open-source
   distribution: меньше шансов, что человек попробует склонировать репо
   и сразу столкнётся с edge case в настройке Qdrant.
4. **Reuse инфры.** Бэкап PG уже есть. Мониторинг PG уже есть.
   Алертинг PG уже есть. Все эти артефакты автоматически покрывают и
   embeddings.
5. **JOIN'ы.** Запросы типа «найди k ближайших entity в graph_variant=X
   и сразу подними их Node-метаданные» — это один SQL с JOIN, без двух
   round-trip'ов «vector store → ids → PG → metadata».
6. **Простота миграции.** Если позже захочется уйти на Qdrant — за
   `VectorStoreProtocol` (§ 6) бэкенд меняется в одном файле.

### 9.2. Вариант B (если основной не зайдёт)

**Qdrant standalone** (Сценарий «в»).

Когда выбираем B:
- **Mini-benchmark** в Phase 0.7 показывает p95 > 40 ms на наших данных
  с pgvector (т. е. запас < 20%). Это маловероятно для 50k, но возможно,
  если фильтры очень рваные.
- **Появилось требование hybrid search** (vec + BM25), и мы хотим, чтобы
  это «из коробки» — Qdrant с sparse vectors стал зрелым к концу 2025.
- **Объём вырос** до >500k vectors на инсталляцию (например, добавили
  второй большой корпус) — на этом профиле Qdrant начинает показывать
  заметное преимущество.

### 9.3. Phase 0.7 — Definition of Done

Привязка к `plan.md` § 3, задача 0.7:

1. **`backend/api/vector_store/` модуль создан**:
   - `types.py` — `VecItem`, `SearchHit`, `Filter` ADT (§ 6.1, 6.2).
   - `protocol.py` — `VectorStoreProtocol` (§ 6.3).
   - `pgvector_adapter.py` — реализация на `asyncpg` + `pgvector-python`.
   - `tests/test_vector_store_contract.py` — единый contract test-suite.
2. **Alembic-миграция** добавляет:
   - `CREATE EXTENSION IF NOT EXISTS vector;`
   - таблицу `node_embeddings(id PK, collection, vector vector(N),
     graph_variant_id, layer, node_type, model, created_at)`
     (или по таблице на коллекцию — открытый под-вопрос, см. ниже).
   - `CREATE INDEX ... USING hnsw (vector vector_cosine_ops)
     WITH (m=16, ef_construction=200);`
   - btree-индексы по `graph_variant_id`, `layer`, `node_type`.
3. **Mini-benchmark** в `tests/perf/test_vector_store_perf.py`:
   - заполняем 50k случайных vec dim=1024 в pgvector,
   - 1000 запросов k=20 с фильтром по 1 случайному `graph_variant_id`
     из 20,
   - assert p95 < 50 ms.
   - Если упадёт — открываем рассмотрение Qdrant в той же PR.
4. **ADR `0002-vector-store-choice.md`** фиксирует решение и числа из
   mini-benchmark.
5. **README**: «как поднять» (одна команда — pgvector в общем PG-контейнере
   через `init-db` script).

#### Открытый под-вопрос: одна таблица или несколько

**Вариант A**: одна таблица `embeddings` со столбцом `model` + partial
HNSW indexes на каждую модель. Минусы: HNSW в pgvector требует **одного
типа `vector(N)` на колонку**, разных размерностей в одной колонке нет.
Значит, вариант A не работает для multi-dim.

**Вариант B**: таблица per `(model)`: `embeddings_e5_large(vector vector(1024))`,
`embeddings_labse(vector vector(768))` и т. д. Создаётся динамически при
первом `create_collection`. **Default.**

**Вариант C**: таблица per `(graph_variant)` — overkill, отброшено.

В адаптере `pgvector_adapter` имя таблицы выводится из имени коллекции:
`embeddings_{collection_name}`. Названия коллекций — `e5_large`, `labse`,
`bge_m3`, `yandex_text_search`.

### 9.4. Топ-3 риска и митигации

1. **pgvector 0.7 на filtered HNSW окажется медленнее ожиданий.**
   - Митигация: mini-benchmark в DoD 0.7 (см. § 9.3). Если падает —
     пробуем поднять `ef_construction` / `ef_search`, потом пробуем
     iterative scan tuning. В крайнем случае — fallback на Qdrant за
     уже готовый `VectorStoreProtocol`.
2. **Курация-цикл создаёт write-spike, конкурирующий с OLTP.**
   - Митигация: курация-операции делать batch'ами в фоне (Celery/arq из
     `plan.md` § 2). Не делать online recompute embedding на UI-нажатии.
     Кеш embedding по hash(node_state) — уже в плане Phase 2.
3. **Multi-dim коллекций оказывается больше, чем планировали** (например,
   добавляется десятый эксперимент с новой моделью).
   - Митигация: вариант B (таблица-per-модель) масштабируется до
     десятков моделей без боли. PG переваривает сотни таблиц без
     проблем. Limit — operational sanity, а не PG-limit.

Дополнительный риск (не топ-3, но запоминаем):
- **Бэкап с `pg_dump` на embeddings: размер растёт.** На 50k × 1024 ×
  4 байта raw — 200 MB на коллекцию. С 5 коллекциями — 1 GB. Это
  всё ещё smell-test ОК для single-instance. Если перерастёт, включаем
  `pg_dump --exclude-table=embeddings_*` + отдельный snapshot vec-tables.

### 9.5. План миграции на другой backend

«Если потом захотим сменить» — стандартный путь:

1. Реализовать новый адаптер (`qdrant_adapter.py`), удовлетворяющий
   `VectorStoreProtocol`. Прогнать contract test-kit (§ 6.6).
2. Включить **dual-write** через factory: писать одновременно в pgvector и
   Qdrant (новый код пишет в оба, старый читает из pgvector). Период —
   1–2 недели на стабилизацию.
3. Backfill: одноразовый скрипт `scripts/migrate_embeddings.py` копирует
   все коллекции через `read_pgvector → write_qdrant` чанками.
4. Сверка: для случайной выборки из 1000 запросов сравнить top-20 hits
   из обоих backend'ов на >95% совпадения. Где НЕ совпадает — дебаг.
5. Переключить читалки на Qdrant (фича-флаг `VECTOR_STORE_BACKEND=qdrant`).
6. Период «обратимости»: 1 неделя — продолжать dual-write.
7. Удалить pgvector-таблицы и расширение по итогам ADR `0003`.

Важно: **outbox-pattern** надо не оставлять «на потом»; если решим в R3
переходить на Qdrant — outbox добавляется в Phase 2 одновременно с
курация-журналом. Тогда переход в R3 будет вопросом «дренировать outbox
вторым воркером», а не рефакторингом всего write-path.

### 9.6. Сводный чек-лист для Phase 0.7

- [ ] Создан `backend/api/vector_store/` с `types.py`, `protocol.py`,
      `pgvector_adapter.py`.
- [ ] Alembic-миграция: extension + первая таблица embeddings + HNSW index.
- [ ] Contract test-kit (parametrize-готовый, пока с одним бэкендом).
- [ ] Mini-benchmark (50k×1024, p95 < 50 ms) — пройден на CI железе или
      на dev-машине автора.
- [ ] ADR `docs/redesign/decisions/0002-vector-store-choice.md` — записан.
- [ ] `docker-compose.yml` обновлён: `init-db.sh` ставит `vector` extension.
- [ ] README docs обновлены: «как поднять с pgvector».
- [ ] (опционально) skeleton `qdrant_adapter.py` с TODO — на случай B.

---

## 10. Ссылки

Все URL — канонические репо/доки страницы. Я не валидировал их в момент
написания (WebFetch заблокирован). Версии и наличие фич перепроверять
перед интеграцией.

### Vector store kandidaты

- pgvector: <https://github.com/pgvector/pgvector>
- pgvector-python (asyncpg/SQLAlchemy bridge): <https://github.com/pgvector/pgvector-python>
- pgvecto.rs / vectorchord: <https://github.com/tensorchord/pgvecto.rs>,
  <https://github.com/tensorchord/VectorChord>
- Qdrant: <https://github.com/qdrant/qdrant>, доки <https://qdrant.tech/documentation/>
- Qdrant Python client: <https://github.com/qdrant/qdrant-client>
- Milvus: <https://github.com/milvus-io/milvus>, Milvus Lite —
  <https://github.com/milvus-io/milvus-lite>
- LanceDB: <https://github.com/lancedb/lancedb>, доки
  <https://lancedb.github.io/lancedb/>
- Lance format: <https://github.com/lancedb/lance>
- Infinity: <https://github.com/infiniflow/infinity>
- Chroma: <https://github.com/chroma-core/chroma>
- Weaviate: <https://github.com/weaviate/weaviate>
- Vespa: <https://github.com/vespa-engine/vespa>
- Typesense: <https://github.com/typesense/typesense>
- FAISS: <https://github.com/facebookresearch/faiss>

### Бенчмарки (источники, на которые я ссылался по памяти)

- ann-benchmarks: <https://ann-benchmarks.com/>,
  репо <https://github.com/erikbern/ann-benchmarks>
- Qdrant benchmark: <https://qdrant.tech/benchmarks/>,
  репо <https://github.com/qdrant/vector-db-benchmark>
- VectorDBBench (Zilliz): <https://github.com/zilliztech/VectorDBBench>
- LanceDB benchmark blog: <https://blog.lancedb.com/> (фильтр по тегу
  benchmark)

### Embeddings для русского

- multilingual-e5: <https://huggingface.co/intfloat/multilingual-e5-large>
- LaBSE: <https://huggingface.co/sentence-transformers/LaBSE>
- BGE-M3: <https://huggingface.co/BAAI/bge-m3>
- ruBERT (DeepPavlov): <https://huggingface.co/DeepPavlov/rubert-base-cased>
- sbert_large_nlu_ru: <https://huggingface.co/ai-forever/sbert_large_nlu_ru>
- Yandex Search API (text-search): <https://yandex.cloud/ru/docs/search-api/>

### Близкие к нам ADR / discussions (ориентиры)

- pgvector 0.5 HNSW release: <https://github.com/pgvector/pgvector/releases>
- pgvector iterative scans: см. CHANGELOG.md в репо pgvector
- Qdrant payload index: <https://qdrant.tech/documentation/concepts/indexing/>

---

## Приложение A. Минимальный пример pgvector-адаптера (skeleton)

Не финальный код, только чтобы показать форму. Полный код — в Phase 0.7.

```python
# backend/api/vector_store/pgvector_adapter.py
from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector

from .protocol import VectorStoreProtocol
from .types import VecItem, SearchHit, Filter, Eq, In, And, Or, Not, Metric


class PgvectorAdapter(VectorStoreProtocol):
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                init=register_vector,
                min_size=2,
                max_size=8,
            )
        return self._pool

    @staticmethod
    def _table(collection: str) -> str:
        # safe: имя коллекции из enum, валидация на API
        return f"embeddings_{collection}"

    async def create_collection(
        self, name: str, dim: int, metric: Metric = "cosine"
    ) -> None:
        op = {"cosine": "vector_cosine_ops",
              "l2": "vector_l2_ops",
              "ip": "vector_ip_ops"}[metric]
        sql = f"""
            CREATE TABLE IF NOT EXISTS {self._table(name)} (
                id TEXT PRIMARY KEY,
                vector vector({dim}) NOT NULL,
                graph_variant_id TEXT NOT NULL,
                layer TEXT NOT NULL,
                node_type TEXT,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_{name}_hnsw
              ON {self._table(name)}
              USING hnsw (vector {op})
              WITH (m=16, ef_construction=200);
            CREATE INDEX IF NOT EXISTS idx_{name}_gv
              ON {self._table(name)} (graph_variant_id);
            CREATE INDEX IF NOT EXISTS idx_{name}_layer
              ON {self._table(name)} (layer);
        """
        async with (await self._get_pool()).acquire() as conn:
            await conn.execute(sql)

    @staticmethod
    def _translate(f: Filter) -> tuple[str, list]:
        # Рекурсивный обход ADT → SQL fragment + params
        params: list = []
        def go(node: Filter) -> str:
            match node:
                case Eq(field, value):
                    params.append(value)
                    return f"{field} = ${len(params)}"
                case In(field, values):
                    params.append(list(values))
                    return f"{field} = ANY(${len(params)})"
                case And(clauses):
                    return "(" + " AND ".join(go(c) for c in clauses) + ")"
                case Or(clauses):
                    return "(" + " OR ".join(go(c) for c in clauses) + ")"
                case Not(c):
                    return f"NOT ({go(c)})"
                case _:
                    raise ValueError(f"unknown filter {node!r}")
        return go(f), params

    async def search(
        self,
        collection: str,
        vector,
        k: int = 20,
        filter: Filter | None = None,
        *,
        with_vectors: bool = False,
        ef_search: int | None = None,
    ) -> list[SearchHit]:
        where_sql, params = ("TRUE", []) if filter is None else self._translate(filter)
        params.append(list(vector))
        vec_param = f"${len(params)}"
        params.append(k)
        k_param = f"${len(params)}"
        cols = "id, graph_variant_id, layer, node_type, metadata, " \
               "1 - (vector <=> " + vec_param + ") AS score"
        if with_vectors:
            cols += ", vector"
        sql = f"""
            SET LOCAL hnsw.ef_search = {ef_search or 100};
            SET LOCAL hnsw.iterative_scan = strict_order;
            SELECT {cols}
            FROM {self._table(collection)}
            WHERE {where_sql}
            ORDER BY vector <=> {vec_param}
            LIMIT {k_param};
        """
        async with (await self._get_pool()).acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            SearchHit(
                id=r["id"],
                score=float(r["score"]),
                metadata={
                    "graph_variant_id": r["graph_variant_id"],
                    "layer": r["layer"],
                    "node_type": r["node_type"],
                    **(r["metadata"] or {}),
                },
                vector=list(r["vector"]) if with_vectors else None,
            )
            for r in rows
        ]
    # upsert / delete / count / health — аналогично; см. Phase 0.7 PR.
```

Заметка по `iterative_scan = strict_order` vs `relaxed_order`: первое
гарантирует правильный порядок результатов (для нашего kNN — хотим),
второе — быстрее, но порядок может быть не строго возрастающим.
По умолчанию для нас — `strict_order`. **`[проверить актуальный синтаксис
для pgvector 0.7+ перед merge]`.**

---

_Конец документа. Решение по 0.7 принимается после mini-benchmark,
ADR `0002-vector-store-choice.md` фиксирует итог._
