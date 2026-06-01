# Отчёт о тестировании GraphRAG Explorer R2 backend

**Дата:** 2026-05-10
**Объект:** `/home/ki/repos/graphrag/backend/api`
**Файл с тестами:** `tests/test_integration_pipeline.py` (21 кейс, 6 групп)
**План:** `tests/integration_test_plan.md`

## Результаты

```
21 passed in 2.69s   (test_integration_pipeline.py)
284 passed, 1 skipped in 18.86s   (весь сьют)
```

Существующий пред-skipped тест — `test_routes_agents.py::test_run_progress_bounded`,
не имеет отношения к новому коду. Регрессий не внесено.

### Покрытие routes/ (от полного сьюта)

| Module                       | Stmts | Miss | Cover |
|------------------------------|-------|------|-------|
| routes/__init__.py           | 10    | 0    | 100%  |
| routes/journal_export.py     | 30    | 0    | 100%  |
| routes/strategies.py         | 39    | 2    | 95%   |
| routes/auth.py               | 65    | 5    | 92%   |
| routes/reason.py             | 59    | 5    | 92%   |
| routes/agents.py             | 65    | 7    | 89%   |
| routes/corpora.py            | 57    | 7    | 88%   |
| routes/tools.py              | 58    | 8    | 86%   |
| routes/eda.py                | 34    | 5    | 85%   |
| routes/graphs.py             | 199   | 35   | 82%   |
| **TOTAL**                    | **616** | **74** | **88%** |

Только новый файл (`test_integration_pipeline.py` отдельно) даёт 62 % по
`routes/+repository/+curation/` — это означает, что он самостоятельно
покрывает большую часть стека через TestClient + InMemoryRepo. Остальные
12 % в строках routes — это PostgresRepository-специфичные ветки (закрыты
гейтом POSTGRES_INTEGRATION=1) и узкие error-paths (RuntimeError → 500),
которые юнит-тесты адресовать не должны.

## Что покрыто новыми тестами

### Группа A — реальное собранное приложение (`api.__main__:app`)
| ID | Тест                                                                    | Status |
|----|-------------------------------------------------------------------------|--------|
| A1 | `test_A1_health_via_real_app`                                           | ✅ pass |
| A2 | `test_A2_strategies_aggregator_all_kinds_populated`                     | ✅ pass |
| A3 | `test_A3_eda_recommendation_references_registered_strategies`           | ✅ pass |

### Группа B — полный journey
| ID | Тест                                                                    | Status |
|----|-------------------------------------------------------------------------|--------|
| B1 | `test_B1_full_journey_corpus_to_reason` (corpus → eda → preview → build → reason) | ✅ pass |
| B2 | `test_B2_journey_two_variants_then_moe`                                 | ✅ pass |
| B3 | `test_B3_journey_agent_proposes_then_accept_increments_version`         | ✅ pass |
| B4 | `test_B4_journey_multiple_undo_pops_one_at_a_time`                      | ✅ pass |

### Группа C — кросс-роутерная согласованность
| ID | Тест                                                                    | Status |
|----|-------------------------------------------------------------------------|--------|
| C1 | `test_C1_journal_export_csv_contains_appended_op`                       | ✅ pass |
| C2 | `test_C2_journal_export_json_round_trips_payloads`                      | ✅ pass |
| C3 | `test_C3_tool_invocation_persists_and_lists`                            | ✅ pass |
| C4 | `test_C4_drill_down_document_text_survives_build`                       | ✅ pass |

### Группа D — фильтры и pagination
| ID | Тест                                                                    | Status |
|----|-------------------------------------------------------------------------|--------|
| D1 | `test_D1_list_variants_filters_by_corpus_id`                            | ✅ pass |
| D2 | `test_D2_list_nodes_layer_filter_returns_only_layer`                    | ✅ pass |
| D3 | `test_D3_list_journal_respects_limit`                                   | ✅ pass |
| D4 | `test_D4_list_suggestions_filter_status_and_agent`                      | ✅ pass |

### Группа E — error-контракты
| ID | Тест                                                                    | Status |
|----|-------------------------------------------------------------------------|--------|
| E1 | `test_E1_unknown_variant_id_returns_404_consistently`                   | ✅ pass |
| E2 | `test_E2_journal_append_payload_validation`                             | ✅ pass |
| E3 | `test_E3_concurrent_accept_returns_409`                                 | ✅ pass |
| E4 | `test_E4_invalid_journal_export_format_returns_422`                     | ✅ pass |

### Группа F — auth + curation interplay
| ID | Тест                                                                    | Status |
|----|-------------------------------------------------------------------------|--------|
| F1 | `test_F1_logged_in_user_can_use_curation_routes`                        | ✅ pass |
| F2 | `test_F2_patch_language_persists`                                       | ✅ pass |

## Найденные дефекты

**Нет.** Все 21 тест прошёл без обнаружения регрессий — что и ожидаемо для зрелого
сьюта с 263 существующими тестами. Ценность нового файла — закрытие
кросс-роутерных гэпов (на per-router сьюте они проявились бы только в виде
production-инцидента после очередного refactor).

## Что было исправлено в процессе разработки тестов

Это были ошибки в тестах, не в коде:

1. **B1/B2** — `MoEResult.experts`, не `expert_blocks`. Исправлено.
2. **A3** — изначально требовал, чтобы EDA-рекомендация запускалась как реальный
   build. Это валит тест на любых корпусах, для которых EDA выбирает
   builder, требующий реального LLM (lightrag/microsoft). Переформулировал в
   проверку cross-router согласованности: каждое имя из EDA-рекомендации
   доступно через `/api/strategies/{kind}/{name}`.
3. **B3/D4/E3** — для маленького тестового корпуса все entity-узлы
   связаны → `OrphanRescuer` с дефолтным `min_total_degree_to_skip=1` ничего
   не возвращает. Параметризовал значением 100, чтобы все 3 entity-узла
   попали в orphan-кандидаты.

## Что НЕ покрыто (намеренно)

Эти зоны я оставил вне объёма по разным причинам:

- **PostgresRepository** — гейт `POSTGRES_INTEGRATION=1`, требует docker.
  Существующий contract test (`test_repository_in_memory.py` через
  Protocol) покрывает invariant на InMemory; PG-специфичные ветки —
  отдельная задача.
- **SSE endpoint `/api/reason/stream`** — TestClient теоретически
  поддерживает SSE (см. существующий `test_reason_stream_emits_expert_then_answer`),
  но он уже покрыт в `test_routes_reason.py`. Дубликат не делал.
- **Frontend e2e (Playwright)** — отдельный сьют в `e2e/`, прогон
  требует `pnpm dev` + backend live; вне backend integration-тестов.
- **GAT ranker / FAISS persistence** — heavy (torch + faiss-cpu init),
  `pytest -m slow` зона; пред-существующие unit-тесты адекватно
  покрывают.
- **Vectorstore outbox pump** — async background loop, отдельный
  `test_vector_outbox_pump.py` справляется.

## Запуск

```sh
cd backend/api
uv run pytest tests/test_integration_pipeline.py -v       # только новые
uv run pytest tests/ -q                                    # весь сьют (~19 c)
```

Coverage:

```sh
uv run --with coverage --with pytest-cov pytest tests/ \
  --cov=api/routes --cov-report=term
```

## Артефакты

- `tests/integration_test_plan.md` — план до реализации
- `tests/test_integration_pipeline.py` — 21 интеграционный тест
- `tests/INTEGRATION_TEST_REPORT.md` — этот отчёт
