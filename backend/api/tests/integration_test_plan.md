# План интеграционных тестов GraphRAG Explorer R2

**Дата:** 2026-05-09
**Цель:** покрыть кросс-роутерные пайплайны и lifecycle, которых нет в существующем сьюте.

## Что уже покрыто

`tests/test_routes_curation.py`, `test_routes_agents.py`, `test_routes_reason.py`,
`test_routes_tools.py`, `test_auth.py`, `test_health.py` — каждый покрывает свой
роутер с мок-NER + InMemoryRepo. Это integration-тесты на уровне
`router + repo + strategies registry`. Что отсутствует:

1. полный сквозной user journey (auth → corpus → eda → build → agent → accept → reason);
2. реальное приложение `api.__main__:app` с пробросом всех роутеров;
3. кросс-роутерная согласованность (например `EdaReport.recommendation.builder`
   действительно даёт собираемый вариант);
4. lifecycle вариации: множественные journal-операции + undo + журнал-экспорт +
   `/api/graphs/{id}/state.version`;
5. фильтры списков (variant ids, suggestions filter combos, journal limit, edges/nodes
   layer/type filters);
6. health endpoint + сценарий "data_dir прокинули — persistence indicator корректный";
7. drill-down документа после билда (текст не теряется в Document.text);
8. **multi-variant** — два варианта одного корпуса, MoE по обоим, согласованность
   `list_variants(corpus_id=…)`.

## План интеграционных тестов (`tests/test_integration_pipeline.py`)

### Группа A — Real-app smoke
Используем `api.__main__:app` напрямую (как `test_health.py`). Override only `get_ner`
и `_maybe_llm`, всё остальное — реальный wire-up.

| ID | Тест | Покрытие |
|----|------|----------|
| A1 | `test_health_via_real_app` | роутер mounting + persistence indicator |
| A2 | `test_strategies_aggregator_all_kinds_populated` | catalog endpoint + registries загружены при импорте `__main__` |
| A3 | `test_eda_recommendation_yields_buildable_variant` | EDA → build с тем же builder/cleaner_chain/clusterer не падает |

### Группа B — Полный journey
Сборный flow на InMemoryRepository, проверяем что данные текут между подсистемами.

| ID | Тест | Покрытие |
|----|------|----------|
| B1 | `test_full_journey_corpus_to_reason` | corpora → docs → eda → preview → build → state → reason single |
| B2 | `test_journey_two_variants_then_moe` | два варианта одного корпуса → MoE evidence_union; вариант-листинг по corpus_id |
| B3 | `test_journey_agent_proposes_then_accept_increments_version` | agent run → suggestion → accept → variant.version+=1 → journal содержит запись |
| B4 | `test_journey_multiple_undo_only_pops_last_each_time` | 3 op → undo → undo → state version продолжает расти, journal сжимается |

### Группа C — Кросс-роутер согласованность

| ID | Тест | Покрытие |
|----|------|----------|
| C1 | `test_journal_export_csv_contains_accepted_suggestion_op` | accept-suggestion даёт запись в /journal/export?format=csv |
| C2 | `test_journal_export_json_round_trips_payloads` | JSON-экспорт парсится; payload-поля не потеряны |
| C3 | `test_tool_invocation_persists_and_lists` | run tool → list invocations → результат сохранён |
| C4 | `test_drill_down_document_text_survives_build` | после build корпуса doc.text всё ещё доступен через GET |

### Группа D — Фильтры и pagination

| ID | Тест | Покрытие |
|----|------|----------|
| D1 | `test_list_variants_filters_by_corpus_id` | вариант c1 не виден при `?corpus_id=c2` |
| D2 | `test_list_nodes_layer_filter_returns_only_layer` | `?layer=entity` отдаёт только entity |
| D3 | `test_list_journal_respects_limit` | `?limit=N` обрезает |
| D4 | `test_list_suggestions_filter_combos` | status+agent одновременно |

### Группа E — Контракты ошибок (404/409/422)

| ID | Тест | Покрытие |
|----|------|----------|
| E1 | `test_unknown_variant_id_returns_404_consistently` | /state, /nodes, /edges, /journal, /undo, /journal/export — все 404 на чужой UUID |
| E2 | `test_journal_append_payload_validation_per_op` | пустой merge_nodes payload → 422 на каждой операции |
| E3 | `test_concurrent_accept_returns_409` | accept-suggestion со stale version → 409 |
| E4 | `test_invalid_format_journal_export_422` | format=xml → 422 |

### Группа F — Auth integration

| ID | Тест | Покрытие |
|----|------|----------|
| F1 | `test_logged_in_user_can_use_curation_routes` | register → cookie → POST /corpora работает |
| F2 | `test_patch_language_persists_across_me` | PATCH /me?language=en → GET /me показывает en |

## Стратегия моков

- NER: `_FakeNer` с пред-заданными mentions для русских текстов.
- LLM: либо `None` (где есть optional), либо `_FakeLLM` (детерминированный JSON).
- Repository: `InMemoryRepository` — продакшен-семантика (concurrent edit / 409),
  без I/O.
- Природа теста = **integration** (реальные HTTP-запросы через TestClient,
  все слои кроме NER/LLM настоящие).

## Acceptance

- ≥ 16 новых тестов, организованных в 6 групп.
- `pytest tests/test_integration_pipeline.py -q` зелёный.
- Не ломаем существующий сьют.
- Каждый тест занимает < 1 с (NER fake; никаких сетевых вызовов).
