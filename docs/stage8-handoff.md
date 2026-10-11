# Этап 8 «Векторная база» — записка после сессии 1 (бэкенд)

Дата: 2026-10-11. Спека: `docs/superpowers/specs/2026-10-11-stage8-vector-db.md`, план: `docs/superpowers/plans/2026-10-11-stage8-vector-db.md`. Подробно — `docs/architecture.md`, раздел «Векторы».

## Сделано (задачи 1–12)

- Образ Postgres → `pgvector/pgvector:pg16` (pgvector 0.8.7), dev-данные пережили смену образа. Тесты и e2e берут тот же сервис compose. Пакет `pgvector` в `pyproject.toml`.
- `SV_AI_EMBED_MODEL` / `_BASE_URL` / `_DIM`, `settings.embeddings_enabled`, `.env.example`.
- Миграция `0017`: `finding_embeddings` (HNSW), `ai_analyses.similar_ids`.
- `services/masking.py` (сюда переехал `is_secret_finding`; `llm/prompts.py` его реэкспортирует), маскирование в промпте триажёра.
- `LlmClient.embed`, `get_embed_client`; `services/embeddings.py`; задача воркера `embed_pending` (+ cron `embed_cron`).
- `services/similarity.py`: `find_similar`, `nearest`, `human_decisions`, `search_by_text(db, base_query, text, client)` — принимает готовый `findings_query`, а не фильтры (так нет импорта api из services).
- API `GET /api/v1/findings/{id}/similar?limit=5`, `/ai/status.embeddings_enabled`, `similar_ids` в `AiAnalysisRead`.
- MCP `find_similar(finding, k)` (параметр назван `finding`, как у `get_finding`), `search_findings(query=…)`; заголовок находки — в `untrusted`.
- Триажёр `triage-v2`.
- Тесты: `test_masking`, `test_embeddings`, `test_similarity`, `test_similar_api`, `test_mcp_similar`, дополнены `test_llm_client`, `test_llm_prompts`, `test_builtin_triage`. Заглушка модели — `FakeEmbedClient` (`tests/factories.py`), фикстура `embeddings_on` (`conftest.py`). Весь pytest зелёный.

## Сессия 2 — фронтенд (задачи 13–16)

- Ответ `GET /findings/{id}/similar`: `{pending: bool, items: [{id, number: "SV-N", title, entity_path, status, severity, similarity: 0..1, decision: {status, reason, reason_tag, at} | null}]}`. 503 — векторы выключены (блок не показывать: смотреть `GET /ai/status` → `embeddings_enabled`).
- `similar_ids` в выводе ИИ — строки UUID; для «На основе похожих: SV-12, SV-40» номера нужно получить (например, из того же ответа `/similar` или `GET /findings/{id}`).
- e2e: на стенде векторы выключены (`SV_AI_EMBED_MODEL` не задан) — проверять, что блока нет.
- После — `/sv-check`, ревью `sv-reviewer` по диффу всего этапа 8 (бэкенд + фронтенд), коммит.

## Не проверено

- Живая модель эмбеддингов (`bge-m3`) — когда будет; на малых таблицах планировщик идёт мимо HNSW, путь с индексом и `iterative_scan` в тестах не нагружен.
