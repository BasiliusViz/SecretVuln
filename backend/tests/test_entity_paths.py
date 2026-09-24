"""Адрес проекта: slug, полный путь, адресация и автосоздание по пути."""

import pytest

from app.services.entity_paths import slugify, split_path
from tests.factories import make_entity, make_finding


def test_slugify_transliterates_and_cleans():
    assert slugify("Платежи API") == "platezhi-api"
    assert slugify("  Backend__v2! ") == "backend__v2"
    assert slugify("!!!") == "project"


def test_split_path_validates():
    assert split_path("/fintech/payments/") == ["fintech", "payments"]
    with pytest.raises(ValueError):
        split_path("Fintech/Платежи")
    with pytest.raises(ValueError):
        split_path("a//b")
    with pytest.raises(ValueError):
        split_path("")


async def _create(client, headers, name, parent_id=None, **extra):
    body = {"name": name, "parent_id": parent_id, **extra}
    r = await client.post("/api/v1/entities", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_sets_slug_and_path(client, admin):
    _, h = admin
    root = await _create(client, h, "Финтех")
    assert root["slug"] == "fintekh"
    assert root["path"] == "fintekh"
    child = await _create(client, h, "Payments", root["id"])
    assert child["path"] == "fintekh/payments"


async def test_rename_slug_and_move_recompute_subtree(client, admin):
    _, h = admin
    a = await _create(client, h, "a")
    b = await _create(client, h, "b", a["id"])
    c = await _create(client, h, "c", b["id"])
    x = await _create(client, h, "x")

    r = await client.patch(f"/api/v1/entities/{a['id']}", json={"slug": "alpha"}, headers=h)
    assert r.status_code == 200
    assert r.json()["path"] == "alpha"
    c_now = (await client.get(f"/api/v1/entities/{c['id']}", headers=h)).json()
    assert c_now["path"] == "alpha/b/c"

    r = await client.patch(f"/api/v1/entities/{b['id']}", json={"parent_id": x["id"]}, headers=h)
    assert r.status_code == 200
    c_now = (await client.get(f"/api/v1/entities/{c['id']}", headers=h)).json()
    assert c_now["path"] == "x/b/c"


async def test_invalid_slug_rejected(client, admin):
    _, h = admin
    a = await _create(client, h, "a")
    r = await client.patch(f"/api/v1/entities/{a['id']}", json={"slug": "Bad Slug"}, headers=h)
    assert r.status_code == 422


async def test_auto_slug_is_unique_among_siblings(client, admin):
    _, h = admin
    await _create(client, h, "a")
    second = await _create(client, h, "A")
    assert second["slug"] == "a-2"
    r = await client.patch(f"/api/v1/entities/{second['id']}", json={"slug": "a"}, headers=h)
    assert r.status_code == 409


async def test_put_by_path_creates_chain_and_is_idempotent(client, admin):
    _, h = admin
    r = await client.put("/api/v1/entities/by-path/fintech/payments/api", json={}, headers=h)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["path"] == "fintech/payments/api"
    assert first["name"] == "api"

    r = await client.put("/api/v1/entities/by-path/fintech/payments/api", json={}, headers=h)
    assert r.json()["id"] == first["id"]
    all_entities = (await client.get("/api/v1/entities", headers=h)).json()
    assert len(all_entities) == 3


async def test_put_by_path_updates_name_keeps_path(client, admin):
    _, h = admin
    r = await client.put(
        "/api/v1/entities/by-path/svc",
        json={"name": "Сервис оплаты", "description": "d"},
        headers=h,
    )
    body = r.json()
    assert body["name"] == "Сервис оплаты"
    assert body["description"] == "d"
    assert body["path"] == "svc"


async def test_get_by_path(client, admin):
    _, h = admin
    await client.put("/api/v1/entities/by-path/team/app", json={}, headers=h)
    r = await client.get("/api/v1/entities/by-path/team/app", headers=h)
    assert r.status_code == 200
    assert r.json()["path"] == "team/app"
    r = await client.get("/api/v1/entities/by-path/nope/x", headers=h)
    assert r.status_code == 404
    r = await client.get("/api/v1/entities/by-path/Bad Path", headers=h)
    assert r.status_code == 422


async def test_put_by_path_conflict_returns_409(client, admin):
    """Автосоздаваемый узел цепочки называется как сегмент пути (slug); если сосед с таким
    именем уже есть под другим slug, вставка ловит IntegrityError по uq_entities_parent_name —
    должно вернуть 409, а не 500."""
    _, h = admin
    await _create(client, h, "a", slug="a-taken")
    r = await client.put("/api/v1/entities/by-path/a/b", json={}, headers=h)
    assert r.status_code == 409


async def test_put_by_path_requires_entity_write(client, developer):
    _, h = developer
    r = await client.put("/api/v1/entities/by-path/svc", json={}, headers=h)
    assert r.status_code == 403


async def test_findings_include_descendants(client, admin, db):
    _, h = admin
    parent = await make_entity(db, "p")
    child = await make_entity(db, "c", parent_id=parent.id)
    await make_finding(db, parent, "f1")
    await make_finding(db, child, "f2")

    r = await client.get(f"/api/v1/findings?entity_id={parent.id}", headers=h)
    assert len(r.json()) == 1
    r = await client.get(
        f"/api/v1/findings?entity_id={parent.id}&include_descendants=true", headers=h
    )
    assert len(r.json()) == 2
    r = await client.get(
        f"/api/v1/findings/stats?entity_id={parent.id}&include_descendants=true", headers=h
    )
    assert r.json()["total"] == 2
