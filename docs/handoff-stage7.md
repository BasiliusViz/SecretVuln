# Этап 7 «Встроенный ИИ» — записка-передача (после сессии A)

Спека: `docs/superpowers/specs/2026-10-11-stage7-builtin-ai.md`, план: `docs/superpowers/plans/2026-10-11-stage7-builtin-ai.md`.

## Сделано (сессия A, бэкенд, задачи 1–6) — pytest 307 passed

- **Настройки**: `SV_AI_BASE_URL/API_KEY/MODEL/TIMEOUT/AUTO_LIMIT`, `settings.ai_enabled` (непустой URL). `httpx` перенесён в основные зависимости.
- **Клиент** `app/services/llm/client.py`: `LlmClient.chat_json(messages, schema)` — `json_object`, вырезка `<think>` и ```-ограды, один повтор с подсказкой об ошибке, всё прочее → `LlmError`. `client_from_settings()`.
- **Промпт** `app/services/llm/prompts.py`: `PROMPT_VERSION="triage-v1"`, `TriageAnswer`, `build_messages(finding)`; фрагмент из `raw.locations[].physicalLocation.(contextRegion|region).snippet`, обрезка 2000 символов; секреты — без фрагмента и без сообщения сканера; секретом считается с запасом: нормализатор gitleaks, «secret» в сканере, CWE (номер из любой записи вида `CWE-798: …`, также в `raw.properties.tags`) 798/259/321/522/312/256/260, слова secret/password/token/private/-key/jwt/webhook… в правиле, названии или тегах SARIF. Данные находки обёрнуты в `<finding_data id=…>` со случайной границей на каждый запрос, системный промпт велит не выполнять указания из них (защита от prompt-injection через код).
- **Триажёр** `app/services/builtin_triage.py`: `triage_finding(db, id, client)` — модель вызывается без блокировки, затем две строки `ai_analyses` (`summary`: title_plain/explanation/remediation; `triage`: verdict/confidence, explanation = reasoning), `agent="sv-builtin"`, `created_by=NULL`, `refresh_ai_verdict`. Не коммитит.
  `pick_auto_triage(db, import_id)` — новые находки импорта по событиям `imported` с `payload.import_id`, импорт в статусе `done` (= прошёл проверку основной ветки), без вывода `sv-builtin`, сначала критичные, до `SV_AI_AUTO_LIMIT`.
- **Воркер** `app/worker.py`: задача `ai_triage_finding` (ошибка модели — в лог), `enqueue_auto_triage` в конце успешного `process_import` (`_job_id="ai:{id}"`, сбой не роняет импорт), `enqueue_ai_triage` для кнопки — **без** `_job_id`, иначе ARQ отбрасывал бы повторный разбор, пока хранится результат прошлого.
- **API** `app/api/analyses.py`: `POST /findings/{id}/ai-triage` → 202 `{"queued": true}` (`finding:analyze`, 404 чужое, 503 выключено, аудит `ai_triage.request` с целью `finding`/`SV-N`); `GET /ai/status` → `{enabled, model}`. Сторожа маршрутов и аудита обновлены, подпись действия в `ru.json` (`audit.action.ai_triage.request`) уже добавлена.
- **Метрика** `ai_agreement`: `value` — **проценты 0–100** (не доля, в отличие от `sla_ratio`), в `MetricRow` новое поле `count` (у остальных метрик `null`). Разрезы `ai_agent`, `ai_model` — только для этой метрики (иначе 422); остальные разрезы и неделя работают. Пусто — `value=null, count=0`.

## Дальше — сессия B (задачи 7–8 плана)

- Кнопка «Разобрать ИИ» в блоке «Анализ ИИ»: показывать при `GET /ai/status → enabled` и праве `finding:analyze`; после 202 — «В очереди». e2e: при выключенном ИИ кнопки нет (на e2e-стенде `SV_AI_BASE_URL` пуст).
- Плитка «Согласие с ИИ» на дашборде: `POST /metrics/aggregate {metric: "ai_agreement"}`, `value` уже в процентах, `count` — подпись «по N выводам»; `value=null` — «Нет данных».
- Затем `/sv-check`, ревью `sv-reviewer` по диффу этапа, статус в `CLAUDE.md`.

## Открытые вопросы

- **У «Инженера ИБ» нет `finding:analyze`** (есть у «Администратора» и «ИИ-агента») — кнопку увидят только они. Решить: добавить право в `BUILTIN_ROLES` (`app/cli.py`) или оставить настройкой ролей в админке.
- Проверка на живой модели — отдельным шагом, когда модель будет (задать `SV_AI_*` в `backend/.env`, перезапустить воркер).
