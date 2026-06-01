# 0002 — Temporal GraphRAG Explorer: позиционирование и отстройка (resubmit 205)

> Дата: 2026-06-01
> Статус: accepted (направление resubmit SIGIR demo 205)
> Контекст: SIGIR'26 Demonstrations, submission **205** «GraphRAG Explorer: Interactive
> Diagnosis and Curation of Cascading Error in Russian GraphRAG Pipelines» — пограничник
> (R1 reject −2, R2/R3 lean-accept +1). Решение: на resubmit делаем **темпоральность
> headline-контрибуцией**, но через интерактивную диагностику/EDA, а не через
> reasoning/forecasting. Детали ревью — `project_sigir_review_205` в memory.

## Решение

Headline resubmit: **«Temporal GraphRAG Explorer: interactive diagnosis of cascading
errors in *evolving* Russian knowledge graphs»**. Вклад — **change-centric визуальная
грамматика** с тремя осями дельты (`query-delta` · `edit-delta` · `time-delta`),
делающая эволюционирующий GraphRAG-пайплайн читаемым и исправимым человеком.

## Организующая мысль

> Все соседи используют время, чтобы **машина лучше отвечала** (forecast — SiMFy;
> recall — Zep/Graphiti). Мы используем время, чтобы **человек понял и починил** граф.
> Темпоральная дельта — диагностическая линза, а не сигнал для предсказания.

Это закрывает претензию рецензентов 205 об отсутствии вклада в visualization/EDA и
остаётся ортогональным всем трём соседним линиям.

## Соседи (PDF в `docs/raw/`, цитировать в related work)

- **SiMFy** — `2023.findings-emnlp.249.pdf` (EMNLP'23 Findings). TKG *reasoning* =
  прогноз будущих квадруплетов `(s,r,?,t+1)`, MLP + историческая частота,
  бенчмарки ICEWS/GDELT. Без человека, без визуализации, на *курированных* event-графах.
- **Survey on Temporal KG** — `2403.04782v1.pdf` (ECNU, 2024). Обзор representation
  learning по TKG. Используем как каркас related work + таксономию (ответ R3 про
  «insufficient context setting»).
- **Zep / Graphiti** — `2501.13956v1.pdf` (Zep AI, 2025). Единственный реально близкий
  сосед: temporal KG, bi-temporal (T — событие, T′ — ingestion), иерархия
  episode→entity→community (≈ наши chunk→entity→community), инкрементальные апдейты,
  провенанс. **Но:** agent-memory backend, цель — recall/latency (DMR, LongMemEval),
  авто-инвалидация фактов, и по их же репозиторию — **нет ни визуализации, ни
  curation-UI, ни exploratory-анализа**.

## Отстройка (заготовки ответов рецензенту)

- **«Just Graphiti + UI»** → закрывается ходом **«Graphiti как подключаемый builder»**
  (F2.1 builder pool): мы сидим *над* любым темпоральным backend'ом, а контрибуция —
  визуальная грамматика темпорального изменения + курация ошибок, которой backend по
  определению не даёт. Плюс bi-temporal (T/T′), **выставленный визуально для
  диагностики, а не для recall**.
- **«Just XGraphRAG + time»** → XGraphRAG статичен и **не редактирует граф**; наш
  дифференциатор (его прямо назвал R3) — **persistent edit + темпоральный каскад** на
  эволюционирующем графе.
- **«Это TKG reasoning?»** → нет, мы **не прогнозируем квадруплеты**; SiMFy и survey
  цитируются именно чтобы очертить, что мы **вне линии forecasting**.

## Дополнительный диагностический угол (новизна)

В шумном русском пайплайне **авто-инвалидация (как у Graphiti) сама ошибается** —
выкидывает корректный факт из-за плохой экстракции. Demo показывает темпоральный каскад
и даёт человеку **откатить неверную инвалидацию**. Это «диагностика *темпоральных*
каскадных ошибок» — нет ни у Zep (нет человека/диагностики), ни у SiMFy (нет ошибок/
курации).

## Связь с ревью 205

- R1 («не увидел query→изменение графа», «просто большой граф») → две видимые дельты
  (query + time) + темпоральное окно само сжимает видимый граф (focus+context).
- R3 («самое интересное — downstream-эффекты правки»; «отстройтесь от XGraphRAG») →
  темпоральный каскад = тот же механизм на ingestion-событиях; bi-temporal даёт
  принципиальный «event-time vs transaction-time» угол.
- R2 (merge ломает запросы, нет error-feedback) → P0-фиксы в UI-плане.

См. план интерфейса: `docs/redesign/temporal_explorer_ui_plan.md`.
</content>
