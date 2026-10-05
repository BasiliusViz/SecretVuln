# Этап 5а — передача во фронтенд-сессию (задачи 11–15)

Бэкенд (задачи 1–10) сделан и в `main`: 239 тестов зелёные. Спека — `docs/superpowers/specs/2026-10-05-stage5a-audit-log-design.md`, план — `docs/superpowers/plans/2026-10-05-stage5a-audit-log.md`.

## Что есть на бэкенде

- Таблица `audit_log` (миграция `0015`), модель `app/models/audit_log.py`.
- `app/services/audit.py`: `record_audit`, `snapshot`/`diff` с белыми списками `FIELDS`, константы действий, `ACTIONS` — полный список.
- Право `audit:read` (на поддерево) — в ролях Аудитор, Руководитель команды, Администратор. **Стенд:** выполнить `alembic upgrade head` и `python -m app.cli seed-roles`.
- Сторож `tests/test_audit_coverage.py`: новый POST/PUT/PATCH/DELETE без `record_audit` роняет тест (исключения — в `EXEMPT` с причиной).

## API для фронта

`GET /api/v1/audit` → `{items, total}`, новые сверху. Параметры: `entity_id`, `subtree` (по умолчанию true), `actor` (подстрока email), `action` (точно или префикс с точкой: `binding.`; можно несколько — `?action=entity.&action=ownership.` — объединяются через ИЛИ), `target_type`, `target_id`, `date_from`, `date_to` (ISO), `limit` (1–500, по умолчанию 50), `offset`. Без права — 403; чужой/невидимый проект в `entity_id` — 404.

Строка: `id, created_at, actor_type (user|system), actor_id, actor_label, action, target_type, target_id, target_label, entity_id, entity_path, ip, changes`.

**Формат `changes`** (важно для раскрытия строки):
- значение — массив из двух элементов `[было, стало]` → строка «Поле / Было / Стало»;
- иначе — просто значение (create/delete — ключевые поля; `{"user": email}` у состава групп; `{"reason": ...}` у неудачного входа; `{"added": [...], "removed": [...]}` у прав роли; `{"reassigned": N}`). Показывать в колонке «Стало» или одной ячейкой.
- Значения бывают списками и объектами (`tags`, правила владельцев `rules: [[{pattern, group_id}], [...]]`) — выводить компактно (JSON/через запятую).

**Импорты:** в `ImportRead` поле `uploaded_by: {id, email, display_name} | null`; `GET /api/v1/imports?uploaded_by=me` — только мои (другие значения → 422).

## Действия (для `t("audit.action.<action>")` и групп фильтра)

| Группа фильтра | Префикс | Действия |
|---|---|---|
| Вход | `auth.` | `login`, `login_failed` (reason: `bad_password` / `unknown_user` / `inactive`) |
| Проекты | `entity.`, `ownership.`, `findings.` | `entity.create`, `entity.update`, `entity.move`, `entity.delete`, `entity.settings_update`, `entity.unpin`, `ownership.rules_update`, `findings.reassign` |
| Доступ | `binding.` | `binding.create`, `binding.delete` |
| Группы | `group.` | `create`, `update`, `delete`, `member_add`, `member_remove`, `sync` |
| Роли | `role.` | `create`, `update`, `delete`, `permissions_update` |
| SLA | `sla_policy.` | `create`, `update`, `delete` |
| Импорты | `import.` | `import.create` |

Группа фильтра = список её префиксов в повторяющемся `action`: «Проекты» → `action=entity.&action=ownership.&action=findings.`.

`actor_type=system` (LDAP-синхронизация состава) — показывать как «Система». `entity_id=null` при непустом `entity_path` — проект удалён.

## Что ещё учесть во фронте

- Матрица прав в «Ролях» строится по каталогу — нужен перевод ресурса `audit` и права `audit:read` в `ru.json`.
- Пункт сайдбара `/audit` — `perm: "audit:read"`; вкладка «Журнал» в настройках проекта — `can("audit:read", path)`, запрос с `entity_id` и `subtree=true`.

## Дальше (сессия 2)

Задачи 11–15 по плану: типы и клиент → импорты («Загрузил», «Только мои») → `AuditTable` + страница `/audit` → вкладка «Журнал» → проверка в браузере, ревью `sv-reviewer` по всему этапу (`git diff 55cd1f8..HEAD`), статус в `CLAUDE.md` и `docs/architecture.md`, замер `/usage`.
