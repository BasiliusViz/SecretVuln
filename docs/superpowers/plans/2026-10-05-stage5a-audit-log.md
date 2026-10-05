# Этап 5а: аудит-лог + `uploaded_by` — план

**Спека:** `docs/superpowers/specs/2026-10-05-stage5a-audit-log-design.md`
**Исполнение:** основная сессия сама, TDD, `/sv-test`; коммит после каждой задачи. Ревью `sv-reviewer` — одно, в конце сессии 2.

## Сессия 1 — бэкенд

1. **Модель и миграция `audit_log`** (clock_timestamp, индексы, enum actor_type) — `app/models/audit_log.py`, `app/models/__init__.py`, `migrations/versions/0015_audit_log.py`.
2. **Сервис `record_audit` + `diff` с белыми списками полей, константы действий** — `app/services/audit.py`, `tests/test_audit_service.py`.
3. **Право `audit:read` (на поддерево) + встроенные роли Аудитор/Руководитель команды/Администратор** — `app/authz/permissions.py`, `app/cli.py`.
4. **API `GET /audit`: фильтры, видимость (entity_scope / is_global для NULL), 404 на чужой проект** — `app/api/audit.py`, `app/schemas/audit.py`, `app/main.py`, `tests/test_audit_api.py`.
5. **Вход: login ok / failed (явный коммит до 401), LDAP-синк групп только при изменениях** — `app/api/auth.py`, `tests/test_audit_auth.py`.
6. **Проекты: create/update/move/delete (delete → родитель), создание по пути при импорте, настройки, правила владельцев, unpin, reassign** — `app/api/entities.py`, `app/api/entity_settings.py`, `app/api/imports.py`, тесты в `tests/test_audit_api.py`.
7. **Доступ: группы, состав, sync; роли и права; привязки (проект/глобальные); SLA-политики** — `app/api/groups.py`, `app/api/roles.py`, `app/api/bindings.py`, `app/api/sla_policies.py`, тесты там же.
8. **Импорты: `import.create` в журнал; `uploaded_by` в `ImportRead` (selectinload), фильтр `uploaded_by=me`** — `app/api/imports.py`, `app/schemas/import_.py`, `tests/test_imports*.py`.
9. **Тест-сторож по `app.routes` + `EXEMPT` с причинами** — `tests/test_audit_coverage.py`.
10. **Полный `/sv-test`, записка-передача** — `docs/stage5a-frontend-handoff.md`.

## Сессия 2 — фронтенд

11. **Типы и API-клиент для аудита и `uploaded_by`** — `frontend/src/api/`.
12. **Импорты: колонка «Загрузил», переключатель «Только мои»** — `pages/Imports.tsx`, `i18n/ru.json`.
13. **Компонент `AuditTable` (раскрытие изменений, пагинация) + страница `/audit` с фильтрами, маршрут и пункт сайдбара** — `components/AuditTable.tsx`, `pages/Audit.tsx`, `App.tsx`, `components/Layout.tsx`, `i18n/ru.json`.
14. **Вкладка «Журнал» в настройках проекта (`can("audit:read", path)`)** — `pages/ProjectSettings.tsx`.
15. **Проверка в браузере, ревью `sv-reviewer`, исправления, статус в `CLAUDE.md` и `docs/architecture.md`, замер `/usage`**.
