# Этап 6 — передача после сессии A (бэкенд)

Спека: `docs/superpowers/specs/2026-10-10-stage6-ai-agent-output.md`. Бэкенд сделан, тесты — `tests/test_ai_agents.py`.

## Что сделано

- **Права**: `finding:analyze`, `token:manage` (глобальное). Роль «ИИ-агент» (`entity:read`, `finding:read`, `finding:analyze`) в `cli.py`; Администратору добавлены `finding:analyze`, `token:manage`. После деплоя — `python -m app.cli seed-roles`.
- **Сервисные аккаунты**: `AuthSource.service`, email `<name>@service.local`, без пароля. Вход по паролю и JWT для них — 401. `SERVICE_DENIED` (`authz/permissions.py`) срезает `finding:write/delete/triage/approve` и `token:manage`, даже если выданы привязкой; суперпользователем сервисный аккаунт не бывает.
- **Токены** `sv_…` (`services/api_tokens.py`): sha256 в БД, показ один раз, `last_used_at` — не чаще раза в минуту. Отзыв — мягкий (`revoked_at`).
- **Миграция 0016**: `api_tokens`, `ai_analyses`, `findings.ai_verdict` (последний неотклонённый triage-вердикт, пересчёт при записи и рассмотрении).
- **Аудит**: `service_account.create/update`, `token.create/revoke` (строки в `ru.json` уже есть). Выводы ИИ — в EXEMPT: запись сама хранит автора и ревьюера.
- **MCP**: `python -m app.mcp_server` (из `backend/`), `http://127.0.0.1:8002/mcp`, stateless streamable HTTP, `Authorization: Bearer sv_…`. Инструменты `search_findings`, `get_finding` (UUID или `SV-N`), `get_stats`, `submit_analysis`; логика — `services/agent_tools.py` (те же запросы, что у REST). Тексты SARIF — в блоке `untrusted` + `notice`.

## API для фронтенда (сессия B)

| Метод | Путь | Право | Заметки |
|---|---|---|---|
| GET | `/service-accounts` | `token:manage` | аккаунты + `tokens[]` (без самого токена) |
| POST | `/service-accounts` | `token:manage` | `{name, full_name?}`, name: `[a-z0-9._-]`; 409 — занято |
| PATCH | `/service-accounts/{id}` | `token:manage` | `{full_name?, is_active?}` |
| POST | `/service-accounts/{id}/tokens` | `token:manage` | `{name, expires_in_days?}` → `token` один раз; 409 у отключённого |
| DELETE | `/service-accounts/{id}/tokens/{token_id}` | `token:manage` | отзыв |
| GET | `/findings/{id}/analyses` | `finding:read` | новые сверху; `author`, `reviewer` |
| POST | `/findings/{id}/analyses` | `finding:analyze` | `kind` summary/triage, triage требует `verdict` |
| POST | `/analyses/{id}/review` | `finding:triage` | `{decision: accept/reject, comment?}`; 409 — уже рассмотрен, 403 — свой вывод |
| GET | `/findings?ai_verdict=…&no_ai_verdict=true` | — | в `FindingRead` поле `ai_verdict` |
| PATCH | `/findings/{id}` и POST `/findings/{id}/decisions` | — | необязательный `ai_analysis_id` → в payload события |

Добавить сервисный аккаунт в группу — обычный `POST /groups/{id}/members/{user_id}`.

## Дальше (сессия B)

Пункты «Фронтенд» спеки: админка «Сервисные аккаунты», блок «Анализ ИИ» в окне находки (после «Принять» — предложить действие со статусом с `ai_analysis_id`), колонка и фильтр «Вердикт ИИ», строки в `ru.json`, e2e. Затем одно ревью `sv-reviewer` по диффу этапа.
