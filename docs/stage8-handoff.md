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
- Триажёр `triage-v2`: похожие — только из поддерева проекта находки (спека была «тот же корень», сужено по проверке безопасности, решение пользователя 11.10). Поэтому все `similar_ids` видны любому, кто видит саму находку. Маскирование: значение без кавычек пропускается, только если это цепочка идентификаторов перед `(` или с точкой.
- Тесты: `test_masking`, `test_embeddings`, `test_similarity`, `test_similar_api`, `test_mcp_similar`, дополнены `test_llm_client`, `test_llm_prompts`, `test_builtin_triage`. Заглушка модели — `FakeEmbedClient` (`tests/factories.py`), фикстура `embeddings_on` (`conftest.py`). Весь pytest зелёный.

## Сессия 2 — фронтенд (задачи 13–16)

- Ответ `GET /findings/{id}/similar`: `{pending: bool, items: [{id, number: "SV-N", title, entity_path, status, severity, similarity: 0..1, decision: {status, reason, reason_tag, at} | null}]}`. 503 — векторы выключены (блок не показывать: смотреть `GET /ai/status` → `embeddings_enabled`).
- `similar_ids` в выводе ИИ — строки UUID; для «На основе похожих: SV-12, SV-40» номера нужно получить (например, из того же ответа `/similar` или `GET /findings/{id}`).
- e2e: на стенде векторы выключены (`SV_AI_EMBED_MODEL` не задан) — проверять, что блока нет.
- После — `/sv-check`, ревью `sv-reviewer` по диффу всего этапа 8 (бэкенд + фронтенд), коммит.

## Проверка безопасности коммита — итог

Все 3 замечания закрыты (`15c8016`, `18e1e5b`): похожие для ИИ — только поддерево находки, `similar_ids` поэтому не раскрывают чужого, маскирование значений без кавычек сужено. Полный pytest зелёный.

## Открытое (не исправлено — сессии 2 знать)

- Маскирование: `password=hunter2.secret` (без кавычек, вид `a.b`) не маскируется — неотличимо от `obj.attr` в коде. Осознанно; в кавычках маскируется всегда.
- HNSW + `iterative_scan` под нагрузкой не проверены: на малых тестовых таблицах планировщик идёт мимо индекса.
- Живая модель эмбеддингов (`bge-m3`) — проверить, когда будет.
- Ревью `sv-reviewer` по этапу 8 ещё не было — в конце сессии 2, по диффу всего этапа.
