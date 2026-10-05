"""Каждый эндпоинт API классифицирован по способу проверки доступа.

Новый маршрут без строки здесь роняет тест: сначала решите, как он проверяет права.

- point   — грузит объект и вызывает `ensure` по его проекту (404/403);
- list    — SQL-фильтр по праву (`Access.filter` / `entity_scope` / `visible_filter`);
- global  — глобальное право или справочник без путей проектов;
- self    — только данные самого пользователя;
- public  — без аутентификации.
"""

from __future__ import annotations

from app.main import app

ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/login"): "public",
    ("GET", "/api/v1/health"): "public",
    ("GET", "/api/v1/auth/me"): "self",
    # проекты
    ("GET", "/api/v1/entities"): "list",
    ("POST", "/api/v1/entities"): "point",  # родитель; корень — глобально
    ("GET", "/api/v1/entities/by-path/{path}"): "point",
    ("PUT", "/api/v1/entities/by-path/{path}"): "point",  # ближайший существующий предок
    ("GET", "/api/v1/entities/{entity_id}"): "point",
    ("PATCH", "/api/v1/entities/{entity_id}"): "point",  # перенос: обе ветки + sla:assign
    ("DELETE", "/api/v1/entities/{entity_id}"): "point",
    ("GET", "/api/v1/entities/{entity_id}/settings"): "point",
    ("PATCH", "/api/v1/entities/{entity_id}/settings"): "point",
    ("PUT", "/api/v1/entities/{entity_id}/ownership-rules"): "point",
    ("POST", "/api/v1/entities/{entity_id}/settings/unpin"): "point",
    ("GET", "/api/v1/entities/{entity_id}/config.yml"): "point",
    ("POST", "/api/v1/entities/{entity_id}/reassign"): "point",
    ("GET", "/api/v1/tags"): "list",
    # импорты
    ("POST", "/api/v1/entities/{entity_id}/imports"): "point",
    ("GET", "/api/v1/entities/{entity_id}/imports"): "point",
    ("GET", "/api/v1/imports"): "list",
    ("POST", "/api/v1/imports"): "point",
    ("GET", "/api/v1/imports/{import_id}"): "point",
    # находки и решения
    ("GET", "/api/v1/findings"): "list",
    ("GET", "/api/v1/findings/stats"): "list",
    ("GET", "/api/v1/findings/noisy-rules"): "list",
    ("GET", "/api/v1/findings/by-number/{number}"): "point",
    ("GET", "/api/v1/findings/{finding_id}"): "point",
    ("PATCH", "/api/v1/findings/{finding_id}"): "point",
    ("GET", "/api/v1/findings/{finding_id}/events"): "point",
    ("POST", "/api/v1/findings/{finding_id}/assign"): "point",
    ("POST", "/api/v1/findings/{finding_id}/comments"): "point",
    ("POST", "/api/v1/findings/{finding_id}/help"): "point",
    ("POST", "/api/v1/findings/bulk"): "point",  # всё или ничего
    ("POST", "/api/v1/findings/{finding_id}/decisions"): "point",
    ("GET", "/api/v1/findings/{finding_id}/decisions"): "point",
    ("GET", "/api/v1/decisions"): "list",
    ("POST", "/api/v1/decisions/{decision_id}/approve"): "point",
    ("POST", "/api/v1/decisions/{decision_id}/reject"): "point",
    ("POST", "/api/v1/metrics/aggregate"): "list",
    ("GET", "/api/v1/audit"): "list",  # с entity_id — ensure audit:read
    # группы и пользователи (состав групп — только глобальный group:write)
    ("GET", "/api/v1/groups"): "global",  # с entity_id — узел должен быть виден
    ("POST", "/api/v1/groups"): "global",
    ("GET", "/api/v1/groups/{group_id}"): "global",
    ("PATCH", "/api/v1/groups/{group_id}"): "global",
    ("DELETE", "/api/v1/groups/{group_id}"): "global",
    ("POST", "/api/v1/groups/{group_id}/members/{user_id}"): "global",
    ("DELETE", "/api/v1/groups/{group_id}/members/{user_id}"): "global",
    ("POST", "/api/v1/groups/{group_id}/sync"): "global",
    ("GET", "/api/v1/users"): "global",
    # привязки
    ("GET", "/api/v1/entities/{entity_id}/bindings"): "point",
    ("POST", "/api/v1/entities/{entity_id}/bindings"): "point",  # access:manage + «не сильнее»
    ("DELETE", "/api/v1/bindings/{binding_id}"): "point",
    ("GET", "/api/v1/groups/{group_id}/bindings"): "list",  # только видимые узлы
    ("POST", "/api/v1/groups/{group_id}/bindings"): "global",
    ("DELETE", "/api/v1/groups/{group_id}/bindings/{binding_id}"): "global",
    # роли и SLA-политики — только глобальные права
    ("GET", "/api/v1/permissions/catalog"): "global",
    ("GET", "/api/v1/roles"): "global",
    ("POST", "/api/v1/roles"): "global",
    ("GET", "/api/v1/roles/{role_id}"): "global",
    ("PATCH", "/api/v1/roles/{role_id}"): "global",
    ("DELETE", "/api/v1/roles/{role_id}"): "global",
    ("PUT", "/api/v1/roles/{role_id}/permissions"): "global",
    ("GET", "/api/v1/sla-policies"): "global",
    ("POST", "/api/v1/sla-policies"): "global",
    ("PATCH", "/api/v1/sla-policies/{policy_id}"): "global",
    ("DELETE", "/api/v1/sla-policies/{policy_id}"): "global",
}


def _api_routes() -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        for method in ops
    }


def test_every_route_is_classified():
    missing = sorted(_api_routes() - ROUTES.keys())
    assert not missing, f"Маршруты без решения о доступе (добавьте в ROUTES): {missing}"


def test_no_stale_entries():
    stale = sorted(ROUTES.keys() - _api_routes())
    assert not stale, f"В ROUTES есть несуществующие маршруты: {stale}"


async def test_non_public_routes_require_auth(client):
    """Все маршруты, кроме public, без токена отвечают 401."""
    import re

    zero = "00000000-0000-0000-0000-000000000000"
    for (method, path), kind in sorted(ROUTES.items()):
        if kind == "public":
            continue
        url = re.sub(r"\{number\}", "1", path)
        url = re.sub(r"\{path\}", "x", url)
        url = re.sub(r"\{[a-z_]+\}", zero, url)
        r = await client.request(method, url)
        assert r.status_code == 401, (method, path, r.status_code)
