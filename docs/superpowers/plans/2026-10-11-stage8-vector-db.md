# Этап 8 «Векторная база» — план

Спека: `docs/superpowers/specs/2026-10-11-stage8-vector-db.md`. Две сессии: бэкенд → фронтенд. TDD, тесты — `/sv-test`.

## Сессия 1 — бэкенд

1. Образ `pgvector/pgvector:pg16` в compose и стендах (тесты, e2e), пакет `pgvector` в зависимости — `docker-compose.yml`, `scripts/e2e.ps1`, `backend/pyproject.toml`/requirements.
2. Настройки `SV_AI_EMBED_*` + `embeddings_enabled` — `core/config.py`, `backend/.env.example`.
3. Модель `finding_embeddings`, `ai_analyses.similar_ids`, миграция с `CREATE EXTENSION vector` и HNSW — `models/finding_embedding.py`, `models/__init__.py`, `models/ai_analysis.py`, `alembic/versions/`.
4. Маскирование, перенос `is_secret_finding` — `services/masking.py`, `services/llm/prompts.py`, `tests/test_masking.py`.
5. `embed()` и `get_embed_client()` — `services/llm/client.py`, тест клиента.
6. Канонический текст, `embed_pending`, `ensure_embedding` — `services/embeddings.py`, `tests/test_embeddings.py`.
7. Задача `embed_pending`: после импорта и cron раз в час — `worker.py`, тест воркера.
8. `find_similar` и `search_by_text` с фильтром прав и `iterative_scan` — `services/similarity.py`, `tests/test_similarity.py`.
9. Эндпоинт `/findings/{id}/similar`, `embeddings_enabled` в `/ai/status`, `similar_ids` в схеме — `api/findings.py`, `api/analyses.py` (или где `/ai/status`), `schemas/`.
10. MCP: `find_similar`, `query` в `search_findings` — `services/agent_tools.py`, `mcp_server.py`, тесты MCP.
11. Триажёр `triage-v2`: похожие решённые из того же корня, маскирование, `similar_ids` — `services/builtin_triage.py`, `services/llm/prompts.py`, тесты триажёра.
12. Доки: `docs/architecture.md` (раздел «Векторы»), карта файлов и статус в `CLAUDE.md`; записка-передача `docs/stage8-handoff.md`.

## Сессия 2 — фронтенд

13. Блок «Похожие находки» в окне SV-N — `pages/Findings` (окно), `api/`, `i18n/ru.json`.
14. «На основе похожих» в блоке «Анализ ИИ».
15. e2e: при выключенных векторах блока нет — `frontend/e2e/`.
16. `/sv-check`, ревью `sv-reviewer` по диффу этапа, исправления, коммит.
