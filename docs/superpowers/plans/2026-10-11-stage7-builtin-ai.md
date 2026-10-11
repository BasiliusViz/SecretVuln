# Этап 7 «Встроенный ИИ» — план

**Спека:** `docs/superpowers/specs/2026-10-11-stage7-builtin-ai.md` (читать вместе с планом).
**Как работаем:** одна Opus-сессия пишет сама, TDD, тесты `/sv-test`. Сессия A — бэкенд (задачи 1–6), сессия B — фронтенд (7–8). Ревью одно на этап — `sv-reviewer` после задачи 8.

**Общие ограничения:** env только `SV_AI_*`; ИИ не меняет статус находки — пишет только `ai_analyses`; `agent="sv-builtin"`, `created_by=NULL`; `PROMPT_VERSION="triage-v1"`; под конкретную модель не подстраиваться; UI-строки только в `ru.json`. Если `httpx` в `pyproject.toml` лишь в dev-зависимостях — перенести в основные.

## Сессия A — бэкенд

1. **Настройки + клиент модели** — `SV_AI_*` и свойство `ai_enabled`; `chat_json(messages, schema)` на httpx: `json_object`, вырезка `<think>`, валидация Pydantic, один повтор, `LlmError`. Тесты через `httpx.MockTransport` (транспорт — параметр клиента).
   Файлы: `app/core/config.py`, `backend/.env.example`, `app/services/llm/__init__.py`, `app/services/llm/client.py`, `tests/test_llm_client.py`.
2. **Промпт и вход** — `PROMPT_VERSION`, схема ответа `TriageAnswer`, `build_messages(finding)`: правило, сообщение, сканер, severity, CWE, файл:строка, обрезанный фрагмент из `raw`; для секретов фрагмента нет (определять по нормализатору/сканеру из `services/sarif/normalizers.py`).
   Файлы: `app/services/llm/prompts.py`, `tests/test_llm_prompts.py`.
3. **Триажёр** — `triage_finding(db, finding_id, client)`: вход → модель → две строки `ai_analyses` (`summary`, `triage`) через существующий `create_analysis`/`refresh_ai_verdict` (или напрямую, если тот требует пользователя).
   Файлы: `app/services/builtin_triage.py`, `tests/test_builtin_triage.py`.
4. **Воркер и автозапуск** — задача `ai_triage_finding`, `_job_id="ai:{id}"`; после `process_import`: включено + основная ветка + новые находки без вывода `sv-builtin`, не больше `SV_AI_AUTO_LIMIT`; ошибка модели — лог. Для теста — функция отбора `pick_auto_triage(db, import_id) -> list[UUID]` отдельно от постановки в очередь.
   Файлы: `app/worker.py`, `app/services/builtin_triage.py`, `app/services/import_processing.py` (вернуть id новых находок, если ещё не возвращает), `tests/test_builtin_triage.py`.
5. **API** — `POST /findings/{id}/ai-triage` (202, `finding:analyze`, 404, 503, аудит `ai_triage.request`), `GET /ai/status`. Проверить, что сторож `test_route_coverage`/`test_audit_coverage` доволен.
   Файлы: `app/api/analyses.py`, `app/services/audit.py`, `app/main.py` (если новый роутер), `tests/test_ai_triage_api.py`.
6. **Метрика `ai_agreement`** — явное + неявное согласие по правилам спеки, разрезы `ai_agent`, `ai_model`; остальные разрезы по-прежнему работают.
   Файлы: `app/schemas/metrics.py`, `app/services/metrics.py`, `tests/test_metrics.py` (или `tests/test_ai_agreement.py`).

Конец сессии A: `/sv-test` зелёный, коммит, записка-передача `docs/handoff-stage7.md` (что сделано, что дальше).

## Сессия B — фронтенд

7. **Кнопка «Разобрать ИИ»** — в блоке «Анализ ИИ», по `GET /ai/status` и праву; после нажатия «В очереди»; строки в `ru.json`; e2e: при выключенном ИИ кнопки нет.
   Файлы: компонент блока «Анализ ИИ» (`frontend/src/...`, найти Grep'ом `ai_analyses`/`analyses`), `frontend/src/i18n/ru.json`, `frontend/e2e/ai.spec.ts` (или существующий спек окна SV-N).
8. **Плитка «Согласие с ИИ»** — на дашборде через `POST /metrics/aggregate` с `metric=ai_agreement`; пусто — «Нет данных».
   Файлы: `frontend/src/pages/Dashboard.tsx`, `frontend/src/i18n/ru.json`.

Конец этапа: `/sv-check`, ревью `sv-reviewer` по диффу этапа, правки, статус в `CLAUDE.md`, `/usage` и запись в память.
