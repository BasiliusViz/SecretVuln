# План этапа 4 «Права на поддерево проектов»

Спека: `docs/superpowers/specs/2026-10-05-subtree-access-design.md`. Каждый пункт: сначала тест, затем код, `/sv-test` зелёный, коммит. Пути бэкенда — от `backend/app/`, фронтенда — от `frontend/src/`.

## Сессия 1 — бэкенд

1. Модель `RoleBinding` (`created_by`, уникальность с `NULLS NOT DISTINCT`), миграция: `group_roles` → глобальные привязки, удалить `group_roles`; тест миграции на данных — `models/role_binding.py`, `models/user_group.py`, `models/__init__.py`, `../migrations/versions/`, `tests/test_bindings_migration.py`.
2. Каталог: `sla:assign`, `access:manage`, пометка «только глобально» и исключение `group:read`/`sla:read`; роль «Руководитель команды» в `seed-roles` — `authz/permissions.py`, `cli.py`.
3. `services/access.py`: `Access` (право → «везде» или префиксы, схлопывание), `load_access` одним запросом с правами ролей из `casbin_rule`, `allows`/`filter`/`anywhere`/`visible_stub_ids`; юнит-тесты — `tests/test_access.py`.
4. `deps.py`: `get_access`, новый смысл `require_permission`, `ensure` (404/403); убрать роли из JWT и подмешивание `"superuser"`; `/auth/me` с `scoped_permissions`, каталог с пометкой глобальных; тест «правка роли действует без перелогина» — `api/deps.py`, `api/auth.py`, `api/roles.py`, `core/security.py`.
5. Перевести `conftest`/`factories` на привязки (фикстуры «команда A на ветке a», «команда B на ветке b»), починить существующие тесты — `tests/conftest.py`, `tests/factories.py`.
6. Проекты: список с заглушками, точечные `ensure`, создание (корень — глобально), перенос (обе ветки, `sla:assign` при смене эффективной политики), удаление, `by-path`, `GET /tags` — `api/entities.py`, `api/entity_settings.py`, `services/entity_paths.py`, `tests/test_scoped_entities.py`.
7. Настройки проекта: `sla_policy_id` → `sla:assign`; 409 по `repo_url` без чужого пути — `api/entity_settings.py`, `services/config_file.py`.
8. Находки: список, stats, noisy-rules, by-number, get/events/patch/assign/help, bulk «всё или ничего», `entity_id` по заглушке — `api/findings.py`, `tests/test_scoped_findings.py`.
9. Решения и метрики: `/decisions` по `finding:read`, approve/reject по `finding:approve` на проекте; `/metrics/aggregate` с фильтром — `api/decisions.py`, `services/metrics.py`, `api/metrics.py`.
10. Импорты: загрузка по узлу, автосоздание по пути (ближайший предок), `config.yml` → `entity:write` на узле, списки и get — `api/imports.py`, `tests/test_scoped_imports.py`.
11. API привязок: `GET/POST /entities/{id}/bindings` (свои, унаследованные, `roles` с `grantable`/`missing`), `DELETE /bindings/{id}`, `/groups/{id}/bindings` (фильтр по видимым), `GET /groups?entity_id=` с `has_access`; убрать add/remove ролей группы; тесты делегирования — `api/bindings.py`, `schemas/binding.py`, `services/bindings.py`, `api/groups.py`, `main.py`, `tests/test_delegation.py`.
12. Тест покрытия маршрутов: каждый маршрут из `app.routes` есть в таблице классификации — `tests/test_route_coverage.py`.
13. Смоук `/sv-smoke`, записка `docs/handoff-stage4-backend.md`, коммит.

## Сессия 2 — фронтенд

14. `AuthContext.can(perm, path?)` по `scoped_permissions`; типы и клиент для привязок — `auth/AuthContext.tsx`, `api/`.
15. Дерево «Проекты»: серые некликабельные заглушки — `pages/Assets.tsx`.
16. Кнопки по проекту в `FindingWindow`, `ProjectSettings`, `Findings`, `Inbox`.
17. Вкладка проекта «Доступ»: свои и унаследованные привязки, добавление и удаление, недоступные роли с подсказкой — `pages/ProjectAccess.tsx`, `pages/ProjectSettings.tsx`.
18. «Группы»: привязки «роль → область» вместо ролей; «Роли»: значок «только глобально» — `pages/Groups.tsx`, `pages/Roles.tsx`.
19. Диалог назначения: предупреждение «у группы нет доступа к проекту» — `pages/FindingWindow.tsx`.
20. Строки в `i18n/ru.json`, проверка в браузере (админ, тимлид ветки, участник чужой ветки), `npm run build`.
21. Ревью `sv-reviewer` по диффу этапа, исправления, статус в `CLAUDE.md`, `docs/architecture.md` (раздел «Права»), замер `/usage`.
