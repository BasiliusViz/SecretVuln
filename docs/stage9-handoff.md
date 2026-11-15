# Этап 9 «Память команды» — передача после сессии 1 (бэкенд)

Дата: 16.11.2026. Спека — `docs/superpowers/specs/2026-11-15-stage9-team-memory.md`,
план — `docs/superpowers/plans/2026-11-15-stage9-team-memory.md` (дальше — раздел «Сессия 2»).

## Сделано (задачи 1–11 сессии 1)

`pytest`: 445 passed. Закоммичено в `main` (не запушено), не ревьюилось (ревью `sv-reviewer` — одно, в конце этапа).
Миграция 0019 на dev-БД не применялась: `cd backend; .\.venv\Scripts\python -m alembic upgrade head`,
затем `python -m app.cli seed-roles` (право `memory:manage` во встроенных ролях).

| Что | Где |
|---|---|
| Модель `TriageMemory`, `findings.memory_id`, `decision_requests.memory_id`, событие `memory_hint` | `models/triage_memory.py`, `migrations/versions/0019_triage_memories.py` |
| Право `memory:manage` (на поддерево): Инженер ИБ, Администратор | `authz/permissions.py`, `cli.py` |
| Сопоставление, выбор самого точного, пересчёт, предложения | `services/memories.py` |
| Подсказка новым и переоткрытым при импорте (`stats.memory_hints`) | `services/import_processing.py` |
| REST правил | `api/memories.py`, `schemas/memory.py` |
| Видимость «сверху» (`allows_from_above`, `filter_from_above`) | `services/access.py` |
| `has_memory` и краткое `memory` в находках | `api/findings.py`, `schemas/finding.py` |
| Запрос по правилу, предложение после одобрения | `services/decisions.py`, `schemas/decision.py` |
| MCP `list_memories`, `memory` в `get_finding` | `services/agent_tools.py`, `mcp_server.py` |
| Промпт `triage-v3` | `services/llm/prompts.py`, `services/builtin_triage.py` |
| Тесты | `tests/test_memories_matching.py`, `tests/test_memories_api.py`, `tests/test_llm_prompts.py`, фабрика `make_memory` |

## API для фронтенда

**`GET /api/v1/memories`** (`finding:read`) — параметры: `status` (`suggested|approved|disabled`),
`entity_id` (правила проекта и его предков), `include_descendants` (плюс правила поддерева),
`manageable=true` (только те, что можно менять — для счётчика предложенных в сайдбаре:
`?status=suggested&manageable=true`), `limit`, `offset`.

**`GET /api/v1/memories/{id}`**, **`POST /api/v1/memories`**, **`PATCH /api/v1/memories/{id}`** (`memory:manage`).

Ответ `MemoryRead`: `id, entity_id, entity_path, entity_name, scanner, rule_id, cwe, path_glob,
decision, reason_tag, reason, status, source (manual|suggested), created_by, approved_by, approved_at,
created_at, updated_at, open_findings, can_manage`.

- `POST`: `{entity_id, scanner?, rule_id?, cwe?, path_glob?, decision, reason_tag?, reason?}` —
  создаётся сразу `approved` и применяется к открытым находкам.
- `PATCH`: только переданные поля; `status: "approved" | "disabled"` — утвердить / выключить (отклонить
  предложенное = `disabled`). Условие можно очистить, передав `null`.
- Проверки (422, текст на русском в `detail`): хотя бы одно условие; для `false_positive` нужен
  `reason_tag` (для `other` — ещё и текст); для `risk_accepted` — текст `reason`.
- Чужое правило — 404; видно, но нет `memory:manage` — 403 (в ответе `can_manage: false`).
- Маска пути: `*` и `?` — внутри каталога, `**` — через каталоги (`tests/**`, `**/test_*.py`).

**Находки**: `GET /findings?has_memory=true|false`; в `FindingRead`/`FindingDetail` — `memory_id` и
`memory: {id, decision, reason_tag, reason} | null`. Область правила для блока в окне SV-N —
`GET /memories/{memory_id}` (`entity_path`).

**Запрос по правилу**: `POST /findings/{id}/decisions` с `memory_id`. Правило должно быть
действующей подсказкой именно этой находки, `decision_type` — совпадать с `decision` правила (иначе 422).
Для `risk_accepted` срок `expires_at` вводит человек. В `DecisionRead` — `memory_id`.

**История находки**: новый тип события `memory_hint` (payload `{memory_id, decision}`, `reason`,
`reason_tag`); в `request_created` / `request_decided` при запросе по правилу — `payload.memory_id`.

**Журнал аудита**: действия `memory.create`, `memory.update`, `memory.approve`, `memory.disable`,
`memory.suggest` (система, без автора); `target_type = "memory"`, подпись — условие правила;
в `changes` — `hints_changed` (сколько находок изменили подсказку), при переносе — `entity_path: [было, стало]`.

## Что осталось фронтенду (сессия 2 плана) — в том числе строки

- `ru.json`: `perm.action` / ресурс `memory` (`memory:manage`), событие истории `memory_hint`,
  пять действий аудита `memory.*`, тип объекта аудита `memory`, статусы и источник правила.
- Страница `/memories`, пункт и счётчик в сайдбаре, блок в окне SV-N, значок и фильтр в «Уязвимостях», e2e.
- В конце этапа: `/sv-check`, ревью `sv-reviewer` по диффу этапа, обновить `CLAUDE.md` и `docs/architecture.md`.

## Решения, принятые по ходу (нет в спеке — проверить на ревью)

1. Событие `memory_hint` пишется не только при импорте, но и когда подсказка появилась после
   утверждения / правки правила (автор — тот, кто менял правило). При утверждении широкого правила
   это по событию на каждую подошедшую открытую находку.
2. Сравнение `scanner` и `cwe` — без учёта регистра, `rule_id` — точное.
3. Выключение / правка правила снимает `memory_id` и у закрытых находок (их статус не трогается).
4. Запрос по правилу принимается только если правило — текущая подсказка находки и тип решения совпадает.
5. Предложение считает одобренные решения с точным совпадением `(entity_id, scanner, rule_id)`;
   находки без `rule_id` не предлагаются. Предложение создаётся и при массовом «ложное» (bulk), если оно
   идёт через одобрение запроса.
6. `open_findings` — по всему поддереву, без учёта прав читателя (число, не список).
7. MCP `list_memories(project)` принимает UUID или путь проекта.

## Открытое

- Пересчёт при утверждении правила на корне грузит все подходящие открытые находки поддерева в память
  (грубый отбор по `scanner`/`rule_id`/`cwe` — в SQL, маска пути — в Python). Для правила с одной
  только маской пути на большом дереве может быть тяжело — при необходимости вынести в воркер.
- Нет теста, что `builtin_triage` передаёт правило в промпт (сам промпт покрыт в `test_llm_prompts.py`).
- Перенос находки/проекта в другое место дерева подсказки не пересчитывает (пересчёт — только при
  импорте и при изменении правил).
- Проверка `triage-v3` на живой модели — когда она будет.
- Хук сессии сообщил: установленный Node.js 22.17.1 уязвим (в т. ч. CVE-2026-111497), советует
  обновить до 22.23.4+. Не трогал — решение за владельцем машины.
