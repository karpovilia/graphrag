# GraphRAG Explorer — Requirements (Redesign R2)

> Версия: draft v2, 2026-05-02 (после ответов на Q1–Q10)
> Статья: «GraphRAG Explorer: Interactive Diagnosis and Curation of Cascading Errors in Russian GraphRAG Pipelines» (SIGIR'26 demo)
> Контекст: эта переработка реализует Future Work из статьи и закрывает разрыв между «диагностический UI поверх фиксированного пайплайна» и «iterative diagnostic environment with modular pools and specialized agents».
>
> **Зафиксированные решения (см. plan.md § Открытые вопросы → Resolved):**
> - Microsoft GraphRAG-форк депрекейтится; используется как обычная PyPI-зависимость через тонкий адаптер.
> - LLM по умолчанию для разработки и тестов — Deepseek (через единый LLM gateway).
> - MoE — целевой режим для статьи; production-вопросы зафиксированы как deferred (см. plan.md § Deferred).
> - Wizard-UX в стиле afina-ai-first: явная пошаговость + свободная навигация назад + чатовый ввод вопроса в любой момент.
> - `@krainovsd/graph` форкаем и расширяем (автор пакета — соавтор проекта).
> - GNN-ranker — обязательная фича R2.
> - Vector store — pgvector под вопросом (медленный); проводится отдельный research (см. plan.md Phase 0).
> - Целевой корпус для R2 — HSE podcast (как в статье).
> - Enum типов сущностей не фиксируется — типы предлагаются EDA-шагом визарда после загрузки корпуса.
> - Деплой — локальный, single-instance.

---

## 0. Краткое резюме

Сейчас система — это фиксированный Microsoft GraphRAG (Leiden, YandexGPT, parquet-снимок графа), плюс простой 2D-граф-вьюер с merge/recolor. Future Work статьи требует двух больших шагов:
1. *modular pools of alternative algorithms* для построения, кластеризации и суммаризации,
2. *specialized agents* для обнаружения подозрительных артефактов и предложения курирующих действий.

Эта переработка добавляет к этим двум ещё пять направлений, заявленных пользователем: смесь экспертов по нескольким графам, GNN-поиск релевантных вершин, инструменты на уровне узла (вместо тулзов в системном промпте агента), переработанный многослойный «многоэтажный» визуализатор и новый UX импорта в стиле afina-ai-first.

Цель — превратить Explorer из «инспектора одного графа» в платформу для сравнительной курации семейства графов с включением активных агентов и инструментов прямо в граф.

---

## 1. Принципы

- **P1. Pluggability everywhere.** Любая стадия пайплайна (chunk → extract → cluster → summarize → retrieve → reason) — strategy/registry с явным интерфейсом. Никаких `if graph == "podcast"` в продовом коде.
- **P2. Граф как гетерогенный многослойный объект.** Канонически храним три типа узлов (Chunk, Entity, Community) и явный `layer`/`type` атрибут — модель данных близка к ToG-3 (`docs/raw/2509.21710v2.pdf`).
- **P3. Курация = first-class.** Каждое изменение графа (merge, split, move, retype, edge edit) пишется в журнал, имеет провенанс к исходному фрагменту и инкрементально пересобирает только затронутое.
- **P4. Агенты предлагают, человек решает.** Агенты курации никогда не правят граф напрямую — они открывают `Suggestion`, которые видны в UI, у каждого есть свой undo и evidence.
- **P5. Каждый узел знает о своих инструментах.** Инструменты прибиты к типу узла, агент-планировщик подбирает их через registry, а не через раздутый системный промпт.
- **P6. Воспроизводимость демо.** Любой вариант графа (комбинация extractor × cleaner × clusterer × summarizer × seed) сохраняется как снимок и может быть воспроизведён офлайн.

---

## 2. Функциональные требования

### F1. Pool курирующих агентов (User req #1)

- **F1.1.** Реестр агентов с интерфейсом `CurationAgent`: `name`, `description`, `applies_to (node_type | edge_type | community | global)`, `propose(graph_view) -> list[Suggestion]`, `cost_estimate`, `requires`.
- **F1.2.** Стартовый набор агентов:
  - `EntityDeduplicator` (морфологическая дедупликация для русского — inflected forms, abbrev),
  - `RelationConsistencyChecker` (находит spurious relations по контексту),
  - `CommunityStabilityScout` (флагает узлы, которые перепрыгивают между community при разных seed),
  - `OrphanRescuer` (находит изолированные high-degree узлы и предлагает связи),
  - `LowConfidenceTriplet` (slot-level confidence по экстрактору),
  - `TopicReportRefresher` (предлагает обновить резюме после правок).
  Этот список — стартовый, реестр расширяемый.
- **F1.3.** Каждое предложение `Suggestion` содержит: целевой объект, тип действия (merge/split/move/retype/edit/delete), evidence (chunk_id, score, объяснение от LLM/правила), стоимость отката, агент-источник.
- **F1.4.** Запуск: ручной (кнопка «Run agent X»), пакетный (queue), и периодический (после каждой загрузки нового графа).
- **F1.5.** Журнал курации: append-only, attached к графу, экспортируемый как JSON.

### F2. Пулы способов построения / очистки / ризонинга (User req #2)

- **F2.1. Builder pool.** Реестр `GraphBuilder` со стратегиями:
  - `MicrosoftGraphRAG` — тонкая обёртка вокруг PyPI-пакета `graphrag` (Microsoft). Локальный форк в `backend/graphrag/` депрекейтится в Phase 0.
  - `LightRAG` (LLM-profiling узлов с двойным набором ключей — local/global, `docs/raw/2410.05779v3.pdf`),
  - `FastRAGSchemaScript` (semi-structured режим: schema + Python-парсер, `docs/raw/2411.13773v2.pdf`),
  - `ToG3Heterogeneous` (Chunk-Triplet-Community граф с единым 1024-d embedding, `docs/raw/2509.21710v2.pdf`).
- **F2.2. Cleaner pool.** Стратегии очистки, применимые после любого Builder:
  - LLM-merge inflected duplicates,
  - threshold-pruning слабых рёбер,
  - reassign по сходству к прототипу community,
  - Bayan re-cluster (уже есть, разблокировать),
  - Leiden-BFS / Leiden-Threshold (уже в UI, добавить в backend).
- **F2.3. Reasoner pool.** Способы ризонинга:
  - `GlobalSearch` (текущий map-reduce по community reports),
  - `LocalSearch` (разблокировать; сейчас закомментирован в `backend/api/graphrag_processing.py:243-275`),
  - `LightRAG dual-keyword` (local+global keywords),
  - `MACER multi-agent` (Retriever / Constructor / Reflector / Reranker / Responder, `docs/raw/2509.21710v2.pdf`),
  - `GRAG two-view` (graph embedding + BFS-text serialization, `docs/raw/2405.16506v3.pdf`).
- **F2.4. Явное разделение low-level и high-level концептов.**
  - **Low-level**: Entity, Triplet, Chunk-span — конкретные сущности и факты с привязкой к строке источника.
  - **High-level**: Community, Topic, CommunitySummary — обобщения.
  - Хранится как `node.layer ∈ {chunk, entity, community, topic}` и `node.granularity ∈ [0..N]`. UI и reasoner используют это явно.
- **F2.5.** Любая стратегия декларирует, какие layer она требует/производит — невозможно запустить high-level reasoner на графе без community-слоя.

### F3. Mixture-of-Experts ризонинг по нескольким графам (User req #3)

- **F3.1.** На один корпус можно собрать несколько вариантов графа (разные builder/cleaner/seed) — все живут параллельно как `GraphVariant` под общим `Corpus`.
- **F3.2.** При запросе MoE-роутер выбирает k вариантов (по metadata: язык, layer-coverage, last-curation-score), параллельно запускает выбранный Reasoner на каждом, получает k ответов с evidence.
- **F3.3.** Aggregator: либо LLM-судья (по аналогии XGraphRAG inference-trace, `docs/raw/2506.13782v1.pdf`), либо weighted vote по confidence × evidence-overlap. Стратегия агрегации тоже плагин.
- **F3.4.** UI показывает: финальный ответ, разложение по экспертам (какой граф что сказал), пересечение evidence-узлов между вариантами. Это сразу даёт сравнительную курацию: пользователь видит, какой builder даёт более грязный ответ.
- **F3.5.** MoE — опциональный режим. Single-graph reasoning остаётся базовым (важно для воспроизводимости статей).

### F4. Новый UX в стиле afina-ai-first (User req #4)

> Что нравится в Afina (с твоих слов):
> 1) явный пошаговый прогон через все обязательные настройки, чтобы пользователь не пропустил ни одну,
> 2) возможность в любой момент подняться назад и поправить ответ, не теряя дальнейшие шаги,
> 3) опциональный чатовый ввод — задать вопрос ассистенту прямо во время настройки.
> Эти три свойства — обязательные требования к новому UX.

- **F4.1. Layout.** Top-bar (логотип + навигация Corpora / Graphs / Agents / Reasoning runs), правый блок профиля, центральный wizard.
- **F4.2. Wizard import (Corpus → Graph variants).**
  - Шаг 1: загрузка/dnd файлов или подключение источника (txt/md, в перспективе urls и Google Docs).
  - Шаг 2: выбор языка + extraction prompt set (русский по умолчанию).
  - **Шаг 3 — EDA & рекомендации.** После загрузки бэкенд делает быстрый exploratory pass (длина документов, плотность именованных сущностей, среднее число типов на чанк, оценка морфологического разброса для русского) и выдаёт **рекомендации**: какие типы сущностей закрепить в стартовом enum (см. F6.1), какой Builder/Cleaner/Clusterer лучше подходит к этому корпусу, какой бюджет токенов прикинуть. Пользователь принимает либо переопределяет.
  - Шаг 4: выбор Builder (radio с описанием/иконкой), параметров, LLM-провайдера/модели.
  - Шаг 5: выбор Cleaner-цепочки (multi-select с порядком).
  - Шаг 6: выбор Clusterer + опции community detection (всё с дефолтами от EDA).
  - Шаг 7: review «дерева сборки» и запуск. Прогресс — реальные SSE/WS события из бэкенда (не fake setTimeout, как сейчас в `frontend/app/pages/index.vue:227,238,263,267`).
- **F4.3. Свободная навигация.** Стрелки/breadcrumbs позволяют вернуться на любой предыдущий шаг и поправить ответ; последующие шаги, которые зависели от изменённого, помечаются «нужно подтвердить» (не сбрасываются молча). Состояние визарда живёт в URL/Pinia, обновление страницы не теряет прогресс.
- **F4.4. Чат-affordance.** На каждом шаге визарда — кнопка «спросить ассистента»; открывается боковой чат, который видит контекст текущего шага (загруженный корпус, выбранные параметры) и может ответить «подойдёт ли LightRAG для этого корпуса?» или «что значит "low-level entity"?». Чат — отдельный лёгкий reasoner поверх того же LLM gateway, не обязательно по графу.
- **F4.5. Wizard reasoning.** При построении ответа — те же три свойства: пошагово (выбрать режим single/MoE → reasoner → варианты графа → ограничивающие узлы), возврат к любому шагу, чат рядом. Заодно остаётся «быстрый» режим — chat-bar над графом, как сейчас в `frontend/app/pages/graph/[id].vue:735-742`.
- **F4.6. Стилевая система.** Минималистичная палитра, крупная типографика, карточки с тонкой тенью, чипы для статусов (running/completed/failed). Нативная поддержка тёмной темы.
- **F4.7.** Все hardcoded URL (`http://192.168.135.118:8000` в `frontend/app/pages/graph/[id].vue:494,517`) убираются в `runtimeConfig`.

### F5. GNN-поиск релевантных вершин (User req #5)

- **F5.1.** На этапе query текущий matching по точному тайтлу + embedding similarity заменяется на GNN-ранкер.
- **F5.2.** Архитектура: graph attention или relevance-aware GNN в духе GRAG (`docs/raw/2405.16506v3.pdf`, soft pruning через MLP-релевантность узел↔запрос). Вход — узловые embeddings + структура подграфа, запрос — embedding запроса; выход — relevance score и опционально score рёбер.
- **F5.3.** Обучение: bootstrap на synthetic queries (генерим из community reports), дообучение на user feedback («этот узел не должен был участвовать в ответе»). Опциональный GNN-дообучатор работает offline.
- **F5.4.** Fallback: если GNN недоступен/не обучен — возвращаемся к baseline embedding similarity. GNN тоже плагин в Reasoner.
- **F5.5.** Минимальный жизнеспособный вариант: 2-layer GAT над PyTorch Geometric, frozen sentence-encoder embeddings (multilingual), inference на CPU для графов до ~5к узлов (см. лимит из статьи: «3,000+ vertices»).

### F6. Tools-on-nodes (User req #6)

- **F6.1.** Каждый узел имеет набор инструментов, выбранных по `node.type`. Реестр `NodeToolRegistry: type -> [Tool]`. **Enum типов не фиксированный** — стартовый набор предлагается EDA-шагом визарда (F4.2 шаг 3) на основе того, что нашёл LLM-extractor в первом проходе. Пользователь может добавить свои типы и привязать к ним тулы.
- **F6.2.** Стартовые инструменты по типам (рекомендация EDA, переопределяется пользователем):
  - PERSON → biographical lookup (Wikidata sparql), коллокации в корпусе, связанные документы.
  - ORG → registry/website lookup, временная шкала упоминаний, дочерние/родительские сущности.
  - EVENT → дата-нормализация, related events.
  - PLACE → геокодирование, related entities.
  - CONCEPT → дефиниция (terminology lookup), синонимы.
  - GENERIC (универсальные, на любом узле): «show evidence chunks», «show neighbors», «summarize subgraph».
- **F6.3.** Контракт `NodeTool`: `name`, `applies_to: list[NodeType]`, `arguments_schema`, `run(node, context) -> ToolResult`, `cost_estimate`.
- **F6.4.** Системный промпт ризонера короткий и фиксированный; список доступных тулов формируется *динамически* из активных узлов в evidence-set. Это решает проблему раздувания контекста.
- **F6.5.** Результаты тула кешируются на узле (`node.tool_outputs`) и видны в side-drawer + используются как доп.evidence в следующих ризонерах.

### F7. Многослойный визуализатор графа (User req #7)

> **Решение от 2026-05-03:** 2.5D / 3D реализация (three.js / 3d-force-graph) **отклонена**. Многослойность реализуется как **opacity-focus в существующем 2D-layout `@krainovsd/graph`** — без новых render-зависимостей. См. `docs/redesign/research/layered_graph_viz.md` §6.6, §7.1–§7.5.

- **F7.1.** Каждый узел и ребро получают поле `layer` (chunk / entity / community / topic). Активный слой рендерится полностью непрозрачно, остальные — с alpha 0.15–0.25 (focus+context паттерн).
- **F7.2.** Хоткеи: `1`/`2`/`3`/`4` — фокус на конкретный слой, `Tab` — циклически переключает активный слой.
- **F7.3.** Хоткей `L` открывает **Layer Map overlay**: список слоёв с drag-reorder для визуального Z-stacking, opacity-слайдером на каждый слой, slice-toggle (показать только активный, спрятать остальные).
- **F7.4.** Drag-reorder в Layer Map меняет **только визуальный Z-stacking при отрисовке**, не семантическую иерархию `chunk → entity → community → topic` (она задаётся данными в backend).
- **F7.3.** Параллельно держим переключатель «granularity»: общие узлы (низкий уровень коммунитет 0–1) и частные (узлы entity / triplet, granularity 3–5). Регулировка слайдером показывает/скрывает частное.
- **F7.4.** Inter-layer связи (entity↔community, chunk↔entity) рисуются полупрозрачными вертикальными «лифтами». Intra-layer — обычными рёбрами в плоскости.
- **F7.5.** UI-операции: переключение активного слоя (хоткеи F7.2), Layer Map overlay (F7.3), slice (F7.3), follow node (камера-pan на узел), cross-layer selection (F7.6). «Schwenk»/3D-camera-rotate — отсутствует, не нужен в 2D.
- **F7.6.** Selection синхронизирован между слоями: выбираешь Entity — подсвечиваются её Chunks и Communities (через cross-layer-edges); неактивные слои продолжают быть полупрозрачными, но подсвеченные узлы становятся непрозрачными.
- **F7.7.** Rendering target: те же 5к узлов на ноут, что и сейчас в `@krainovsd/graph` 2D — без новых ограничений, потому что render-pipeline не меняется.
- **F7.8.** Для презентации статьи нужны два крупных скриншота: (a) layered overview с активным слоем (например, communities) и приглушёнными chunks/entities, (b) MoE-сравнение двух графов рядом. Обе позиции учесть в дизайне (split-view).

---

## 3. Нефункциональные требования

- **NF1. Языки.** Русский — first-class (морфология, токенизация, embeddings). Целевой корпус R2 — HSE podcast как в статье. Английский — best-effort, поддерживается, но не блокирует релиз.
- **NF2. Латентность.** Curation-операции — мгновенный визуальный отклик (< 100 мс), фоновый recompute < 5 с для графов до 3к узлов. Reasoning ответ < 30 с в single, < 90 с в MoE k=3.
- **NF3. Воспроизводимость.** Каждый GraphVariant хранит конфиг, версии моделей, seed. Может быть пересобран из исходников.
- **NF4. Хранилище.** Уйти от кеша «всё в памяти на старте» (`backend/api/graphrag_processing.py:144-157`) к Postgres для метаданных + FAISS per-graph для векторов + блобовый store для крупных embedding-снимков. Решение по vector store зафиксировано 2026-05-03 (override поверх R-02): **FAISS** в форме «один HNSW-индекс на `(graph_variant_id, model)`», полный rebuild на курацию, persistence через `faiss.write_index`. `VectorStoreProtocol` сохраняется как абстракция, чтобы R3 мог переключиться на Qdrant/pgvector без переписывания call-site'ов. Подробности — `docs/redesign/research/vector_store.md` (шапка «decision overrides») и `plan.md` Phase 0.7.
- **NF5. Безопасность.** Секреты только через env. Никаких токенов в логах. CORS — белый список.
- **NF6. Дев-опыт.** `uv sync && uv run api` всё ещё должен поднимать локальный stack. Docker-compose для PG + vector store + миграций.
- **NF7. Покрытие тестами.** Стратегии (Builder/Cleaner/Reasoner/Agent/Tool) — обязательные unit-тесты с фиктивным LLM (record/replay). Интеграционный smoke на HSE podcast (маленький саб-сэт) в CI. **LLM по умолчанию — Deepseek** (за единый LLM gateway).
- **NF8. Лицензии.** Зависимости MIT/Apache. Не тащим GPL.
- **NF9. Деплой.** Локальный single-instance (как `graph-rag.apsolutions.ru` сейчас). Multi-tenant и SaaS — out of scope.
- **NF10. Прослеживаемость (traceability).** Каждый ответ RAG-пайплайна должен «расследоваться» вниз по цепочке: ответ → reasoning chain (какие experts голосовали, как aggregator скомбинировал) → community → entity-узел → исходный chunk → конкретный документ → абзац (span). Provenance уже хранится на узле (`Node.provenance: list[NodeProvenance]` с `document_id` + `span_start/span_end`); требование — **никогда не разрывать эту цепочку** в новом коде: любой новый узел/ребро/ответ должен ссылаться на предшественников через стабильные id (`canonical_id`, `span_id`), а UI должен уметь раскрутить полную цепь по клику. Зафиксировано пользователем 2026-05-08 как блокирующее свойство для статьи и для ручной валидации.

---

## 4. Out of scope (для этой итерации)

- Полноценное обучение GNN с RL (только supervised + heuristic feedback).
- Realtime collaborative editing (multi-user cursor).
- SaaS-onboarding, биллинг, баланс — карточки UI оставляем декоративными до интеграции.
- Mobile.
- Поддержка не-text источников (audio/video/PDF без OCR).
- Полная автоматическая курация без человека (агенты только предлагают).

---

## 5. Связь с папером

| Раздел статьи | Что меняется в R2 |
|---|---|
| §3 Implementation: Graph Construction Pipeline | F2.1, F2.4 — pluggable builders + явные layers |
| §3 Implementation: Retrieval, QA, Incremental Updates | F1, F3, F5, NF2 — агенты + MoE + GNN + инкрементальный recompute |
| §3 Implementation: Interactive Interface | F4, F6, F7 — новый UX, tools-on-nodes, многоэтажка |
| §6 Future Work | покрыто F1+F2; добавлены F3/F5/F6/F7 как расширение скоупа |
| §5 Limitations: Scalability | NF2 + F7.7 (LOD), F5.5 (CPU-friendly GNN) |

---

## 6. Открытые вопросы (см. конец работ; ответы пользователя нужны до старта Phase 1)

См. `plan.md` § Открытые вопросы.
