"""Права на поддерево: проекты (список с заглушками, точечные, структура дерева)."""

from __future__ import annotations

from tests.factories import make_entity, make_policy


def _by_path(items):
    return {e["path"]: e for e in items}


async def test_list_shows_own_branch_and_ancestor_stubs(client, db, two_teams, make_user, grant):
    t = two_teams
    deep = await make_entity(db, "api", parent_id=t.a_svc.id)
    # роль на a/svc — a видна заглушкой, b не видна
    dev, h = await make_user("dev2@test.local")
    await grant(dev, "Разработчик", t.a_svc)
    items = _by_path((await client.get("/api/v1/entities", headers=h)).json())
    assert set(items) == {"a", "a/svc", deep.path_cache}
    assert items["a"]["stub"] is True
    assert set(items["a"]) == {"id", "name", "slug", "path", "parent_id", "stub"}
    assert items["a/svc"]["stub"] is False

    _, lead_b = t.lead_b
    paths = set(_by_path((await client.get("/api/v1/entities", headers=lead_b)).json()))
    assert paths == {"b", "b/svc"}


async def test_point_access_404_and_403(client, two_teams, make_user, grant):
    t = two_teams
    _, lead_a = t.lead_a
    assert (await client.get(f"/api/v1/entities/{t.b.id}", headers=lead_a)).status_code == 404
    assert (await client.get(f"/api/v1/entities/{t.a_svc.id}", headers=lead_a)).status_code == 200
    # заглушка-предок в деталях не открывается
    dev, h = await make_user("x@test.local")
    await grant(dev, "Разработчик", t.a_svc)
    assert (await client.get(f"/api/v1/entities/{t.a.id}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/entities/{t.a.id}/settings", headers=h)).status_code == 404
    assert (await client.get("/api/v1/entities/by-path/a", headers=h)).status_code == 404
    assert (await client.get("/api/v1/entities/by-path/a/svc", headers=h)).status_code == 200
    # чтение есть, записи нет → 403
    r = await client.patch(f"/api/v1/entities/{t.a_svc.id}", json={"name": "z"}, headers=h)
    assert r.status_code == 403
    # чужая ветка → 404 и на запись
    r = await client.patch(f"/api/v1/entities/{t.b_svc.id}", json={"name": "z"}, headers=lead_a)
    assert r.status_code == 404


async def test_create_root_only_global(client, two_teams, appsec):
    _, lead_a = two_teams.lead_a
    r = await client.post("/api/v1/entities", json={"name": "root2"}, headers=lead_a)
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/entities", json={"name": "child", "parent_id": str(two_teams.a.id)}, headers=lead_a
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/v1/entities", json={"name": "c", "parent_id": str(two_teams.b.id)}, headers=lead_a
    )
    assert r.status_code == 404
    _, sec = appsec
    assert (await client.post("/api/v1/entities", json={"name": "r"}, headers=sec)).status_code == 201


async def test_upsert_by_path_needs_write_on_nearest_ancestor(client, two_teams):
    _, lead_a = two_teams.lead_a
    r = await client.put("/api/v1/entities/by-path/a/new/deep", json={}, headers=lead_a)
    assert r.status_code == 200
    r = await client.put("/api/v1/entities/by-path/b/new", json={}, headers=lead_a)
    # невидимый предок b неотличим от отсутствующего корня: оба 403
    assert r.status_code == 403
    r = await client.put("/api/v1/entities/by-path/zzz", json={}, headers=lead_a)
    assert r.status_code == 403


async def test_move_needs_both_branches_and_root_is_global(client, two_teams, grant):
    t = two_teams
    lead, h = t.lead_a
    # только ветка a — нельзя перенести под b и в корень
    r = await client.patch(
        f"/api/v1/entities/{t.a_svc.id}", json={"parent_id": str(t.b.id)}, headers=h
    )
    assert r.status_code == 404
    r = await client.patch(f"/api/v1/entities/{t.a_svc.id}", json={"parent_id": None}, headers=h)
    assert r.status_code == 403
    # с правами на обе ветки — можно
    await grant(lead, "Руководитель команды", t.b)
    r = await client.patch(
        f"/api/v1/entities/{t.a_svc.id}", json={"parent_id": str(t.b.id), "slug": "svc2", "name": "svc2"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "b/svc2"


async def test_move_changing_sla_needs_sla_assign(client, db, two_teams, make_user, grant):
    from app.authz.enforcer import set_role_permissions

    t = two_teams
    policy = await make_policy(db, "Строгая", critical=3)
    t.b.sla_policy_id = policy.id
    await db.commit()
    set_role_permissions("Писатель", [("entity", "read"), ("entity", "write")])
    leaf = await make_entity(db, "leaf", parent_id=t.a.id)
    user, h = await make_user("w@test.local")
    await grant(user, "Писатель", t.a)
    await grant(user, "Писатель", t.b)
    r = await client.patch(f"/api/v1/entities/{leaf.id}", json={"parent_id": str(t.b.id)}, headers=h)
    assert r.status_code == 403
    assert "sla:assign" in r.json()["detail"]
    # lead_a (есть sla:assign на a) с правом записи на b — ок
    lead, lh = t.lead_a
    await grant(lead, "Писатель", t.b)
    r = await client.patch(f"/api/v1/entities/{leaf.id}", json={"parent_id": str(t.b.id)}, headers=lh)
    assert r.status_code == 200, r.text


async def test_sla_policy_change_needs_sla_assign(client, db, two_teams):
    t = two_teams
    policy = await make_policy(db, "P")
    _, dev = t.dev_a
    r = await client.patch(
        f"/api/v1/entities/{t.a_svc.id}/settings", json={"sla_policy_id": str(policy.id)},
        headers=dev,
    )
    assert r.status_code == 403
    _, lead = t.lead_a
    r = await client.patch(
        f"/api/v1/entities/{t.a_svc.id}/settings", json={"sla_policy_id": str(policy.id)},
        headers=lead,
    )
    assert r.status_code == 200, r.text


async def test_repo_conflict_hides_foreign_path(client, db, two_teams):
    t = two_teams
    t.b_svc.repo_url = "https://git.example/x/y"
    await db.commit()
    _, lead = t.lead_a
    r = await client.patch(
        f"/api/v1/entities/{t.a_svc.id}/settings", json={"repo_url": "https://git.example/x/y"},
        headers=lead,
    )
    assert r.status_code == 409
    assert "b/svc" not in r.json()["detail"]
    assert "другому проекту" in r.json()["detail"]


async def test_tags_only_from_readable(client, db, two_teams):
    t = two_teams
    t.a.tags = ["pci"]
    t.b.tags = ["secret-b"]
    await db.commit()
    _, lead = t.lead_a
    assert (await client.get("/api/v1/tags", headers=lead)).json() == ["pci"]
