# Этап 4, сессия 1 (бэкенд) — записка-передача

Ветка `feature/stage4-subtree-access`. Спека: `docs/superpowers/specs/2026-10-05-subtree-access-design.md`, план: `docs/superpowers/plans/2026-10-05-stage4-subtree-access.md` (пункты 1–13 сделаны). Все тесты зелёные, `/sv-smoke` проходит.

## Что сделано

- **Модель и миграция 0014**: `role_bindings` (группа + роль + проект, `NULL` = всё дерево, `NULLS NOT DISTINCT`), строки `group_roles` стали глобальными привязками, `group_roles` удалена. Миграция заодно создаёт `casbin_rule`, если её нет (права ролей теперь читаются SQL-запросом).
- **Каталог** (`authz/permissions.py`): новые `sla:assign`, `access:manage`; `GLOBAL_ONLY` (`group:write/delete`, `role:*`, `sla:manage`) и `ANY_BINDING` (`group:read`, `sla:read`). Роль «Руководитель команды» в `seed-roles`; «Инженер ИБ» и «Администратор» получили `sla:assign`, «Администратор» — ещё `access:manage`.
- **`services/access.py`**: `Access` (право → «везде» или префиксы), `load_access` одним запросом на каждый запрос. Методы: `allows`, `anywhere`, `is_global`, `filter`, `entity_scope`, `can_see`, `visible_filter`, `scoped_permissions`.
- **`api/deps.py`**: в `Principal` теперь `access` вместо `roles`; `require_permission` = «право есть хоть где-то»; `ensure(access, perm, target)` → 404/403; `has_permission` удалён. В JWT ролей больше нет.
- **Эндпоинты**: проекты (заглушки `stub: true` в `GET /entities`, перенос с проверкой обеих веток и `sla:assign`), настройки (`sla_policy_id` → `sla:assign`, путь в 409 по `repo_url` скрыт для невидимых проектов), находки (bulk — всё или ничего), решения (`entity_path`, `can_approve` в списке), метрики, импорты (автосоздание — `entity:write` на ближайшем предке).
- **Привязки** (`api/bindings.py`): `GET/POST /entities/{id}/bindings` (свои, унаследованные, `roles` с `grantable`/`missing`), `DELETE /bindings/{id}`, `GET/POST/DELETE /groups/{id}/bindings`, `GET /groups?entity_id=` с `has_access`. Эндпоинты `/groups/{id}/roles/{role_id}` удалены, в `GroupRead` нет `roles`.
- **Тесты**: `test_access`, `test_scoped_entities/findings/imports`, `test_delegation`, `test_bindings_migration`, `test_route_coverage` (каждый маршрут классифицирован; не-public без токена → 401). В `conftest`: фикстуры `grant` и `two_teams`.

## Отклонения и решения по ходу

- Видимость заглушек считается только по правам на поддерево: `group:read`/`sla:read` и глобальные справочные права дерево не открывают.
- `GET /groups/{id}/bindings` всем (включая глобальный `group:read`) отдаёт только привязки на видимых узлах и глобальные. Для админа это всё равно всё дерево.
- Ворота `require_permission` срабатывают раньше `ensure`: если права нет нигде, ответ 403, даже для чужого объекта (существование объекта при этом не раскрывается).
- `bulk` с несуществующим id теперь 404 на весь запрос (раньше этот id просто пропускался).
- `cli.py seed-roles` в консоли cp1251 падает на «✓» — запускать с `PYTHONIOENCODING=utf-8` (грабли старые, не исправлял).

## Сессия 2 — фронтенд (пункты 14–21 плана)

Ломается во фронтенде сейчас: `GroupRead.roles` (страница «Группы»), эндпоинты ролей группы, `UserRead.roles` из токена. Новое для UI: `/auth/me.scoped_permissions`, `stub` у узлов, `/permissions/catalog.global_only`, `DecisionRead.can_approve/entity_path`, `GroupRead.has_access`, API привязок выше.
