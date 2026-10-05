"""Сторож журнала аудита: каждый изменяющий эндпоинт пишет в `audit_log` или объяснён в EXEMPT.

Проверка по исходнику: эндпоинт (или функция своего модуля, которую он вызывает
напрямую) содержит `record_audit(` / `record_entities_created(`. Новый
POST/PUT/PATCH/DELETE без записи в журнал роняет тест.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from fastapi.routing import APIRoute

from app.main import app

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
MARKERS = ("record_audit(", "record_entities_created(")

_FINDINGS = "уязвимости — история в finding_events"
_DECISIONS = "решения по уязвимостям — история в finding_events"

EXEMPT: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/metrics/aggregate"): "только чтение (агрегаты для дашборда)",
    ("PATCH", "/api/v1/findings/{finding_id}"): _FINDINGS,
    ("POST", "/api/v1/findings/{finding_id}/assign"): _FINDINGS,
    ("POST", "/api/v1/findings/{finding_id}/comments"): _FINDINGS,
    ("POST", "/api/v1/findings/{finding_id}/help"): _FINDINGS,
    ("POST", "/api/v1/findings/bulk"): _FINDINGS,
    ("POST", "/api/v1/findings/{finding_id}/decisions"): _DECISIONS,
    ("POST", "/api/v1/decisions/{decision_id}/approve"): _DECISIONS,
    ("POST", "/api/v1/decisions/{decision_id}/reject"): _DECISIONS,
}


def _source_with_callees(func, seen: set | None = None) -> str:
    """Исходник эндпоинта + (рекурсивно) функций его модуля, вызванных по имени."""
    seen = seen if seen is not None else set()
    seen.add(func)
    src = textwrap.dedent(inspect.getsource(func))
    module = inspect.getmodule(func)
    parts = [src]
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            callee = getattr(module, node.func.id, None)
            if (
                inspect.isfunction(callee)
                and callee.__module__ == func.__module__
                and callee not in seen
            ):
                parts.append(_source_with_callees(callee, seen))
    return "\n".join(parts)


def _api_routes(routes):
    # FastAPI оборачивает подключённые роутеры (`_IncludedRouter`): префиксы заданы
    # в самих APIRouter, поэтому путь маршрута уже полный
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def _mutating_routes():
    for route in _api_routes(app.routes):
        for method in route.methods & MUTATING:
            yield method, route.path_format, route.endpoint


def test_walker_matches_openapi():
    openapi = {
        (m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops
    }
    assert {(m, p) for m, p, _ in _mutating_routes()} == {
        (m, p) for m, p in openapi if m in MUTATING
    }


def test_every_mutating_route_is_audited_or_exempt():
    missing = [
        (method, path)
        for method, path, endpoint in _mutating_routes()
        if (method, path) not in EXEMPT
        and not any(m in _source_with_callees(endpoint) for m in MARKERS)
    ]
    assert not missing, f"Нет записи в журнал аудита (добавьте record_audit или EXEMPT): {missing}"


def test_exempt_has_no_stale_entries():
    existing = {(m, p) for m, p, _ in _mutating_routes()}
    stale = sorted(set(EXEMPT) - existing)
    assert not stale, f"Устаревшие строки в EXEMPT: {stale}"
