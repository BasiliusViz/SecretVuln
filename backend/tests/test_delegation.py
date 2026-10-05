"""Делегирование доступа: access:manage и правило «не сильнее своих»."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Role, RoleBinding
from tests.factories import make_entity, make_group


async def _role_id(db, name: str):
    return (await db.scalar(select(Role).where(Role.name == name))).id


async def test_lead_grants_weaker_role_and_second_lead(client, db, two_teams):
    t = two_teams
    team = await make_group(db, "team-x")
    _, h = t.lead_a
    r = await client.post(
        f"/api/v1/entities/{t.a_svc.id}/bindings",
        json={"group_id": str(team.id), "role_id": str(await _role_id(db, "Разработчик"))},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["entity_path"] == "a/svc"
    # второй тимлид на ветке — можно
    r = await client.post(
        f"/api/v1/entities/{t.a.id}/bindings",
        json={"group_id": str(team.id), "role_id": str(await _role_id(db, "Руководитель команды"))},
        headers=h,
    )
    assert r.status_code == 201, r.text


async def test_stronger_role_forbidden(client, db, two_teams):
    t = two_teams
    team = await make_group(db, "team-x")
    _, h = t.lead_a
    r = await client.post(
        f"/api/v1/entities/{t.a.id}/bindings",
        json={"group_id": str(team.id), "role_id": str(await _role_id(db, "Инженер ИБ"))},
        headers=h,
    )
    assert r.status_code == 403
    assert "finding:approve" in r.json()["detail"]
    # чужая ветка — 404
    r = await client.post(
        f"/api/v1/entities/{t.b.id}/bindings",
        json={"group_id": str(team.id), "role_id": str(await _role_id(db, "Разработчик"))},
        headers=h,
    )
    assert r.status_code == 404


async def test_cannot_revoke_stronger_binding_or_global(client, db, two_teams):
    t = two_teams
    team = await make_group(db, "appsec")
    strong = RoleBinding(group_id=team.id, role_id=await _role_id(db, "Инженер ИБ"), entity_id=t.a.id)
    glob = RoleBinding(group_id=team.id, role_id=await _role_id(db, "Разработчик"), entity_id=None)
    weak = RoleBinding(group_id=team.id, role_id=await _role_id(db, "Разработчик"), entity_id=t.a.id)
    db.add_all([strong, glob, weak])
    await db.commit()
    _, h = t.lead_a
    assert (await client.delete(f"/api/v1/bindings/{strong.id}", headers=h)).status_code == 403
    assert (await client.delete(f"/api/v1/bindings/{glob.id}", headers=h)).status_code == 403
    assert (await client.delete(f"/api/v1/bindings/{weak.id}", headers=h)).status_code == 204
    _, hb = t.lead_b
    assert (await client.delete(f"/api/v1/bindings/{strong.id}", headers=hb)).status_code == 404


async def test_entity_bindings_listing_and_grantable(client, two_teams):
    t = two_teams
    _, h = t.lead_a
    r = await client.get(f"/api/v1/entities/{t.a_svc.id}/bindings", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["own"] == []
    assert {(b["role_name"], b["entity_path"]) for b in body["inherited"]} == {
        ("Руководитель команды", "a"), ("Разработчик", "a"),
    }
    roles = {x["name"]: x for x in body["roles"]}
    assert roles["Разработчик"]["grantable"] is True
    assert roles["Инженер ИБ"]["grantable"] is False
    assert "finding:approve" in roles["Инженер ИБ"]["missing"]
    # глобальные права роли не учитываются
    assert "role:write" not in roles["Администратор"]["missing"]
    # без access:manage — без списка ролей
    _, dev = t.dev_a
    r = await client.get(f"/api/v1/entities/{t.a_svc.id}/bindings", headers=dev)
    assert r.json()["roles"] is None


async def test_global_bindings_only_group_write(client, db, two_teams, admin):
    t = two_teams
    team = await make_group(db, "team-x")
    rid = str(await _role_id(db, "Разработчик"))
    _, h = t.lead_a
    r = await client.post(f"/api/v1/groups/{team.id}/bindings", json={"role_id": rid}, headers=h)
    assert r.status_code == 403
    _, ah = admin
    r = await client.post(f"/api/v1/groups/{team.id}/bindings", json={"role_id": rid}, headers=ah)
    assert r.status_code == 201
    assert r.json()["entity_path"] is None
    r = await client.post(f"/api/v1/groups/{team.id}/bindings", json={"role_id": rid}, headers=ah)
    assert r.status_code == 409
    # админ выдаёт на проект любую роль без «не сильнее своих»
    r = await client.post(
        f"/api/v1/groups/{team.id}/bindings",
        json={"role_id": str(await _role_id(db, "Инженер ИБ")), "entity_id": str(t.b.id)},
        headers=ah,
    )
    assert r.status_code == 201
    bid = r.json()["id"]
    # lead_a не видит привязку на b в списке группы
    items = (await client.get(f"/api/v1/groups/{team.id}/bindings", headers=h)).json()
    assert [b["entity_path"] for b in items] == [None]
    r = await client.delete(f"/api/v1/groups/{team.id}/bindings/{bid}", headers=ah)
    assert r.status_code == 204


async def test_binding_gives_access_and_cascade_on_delete(client, db, two_teams, make_user, grant):
    t = two_teams
    extra = await make_entity(db, "extra", parent_id=t.a.id)
    user, h = await make_user("n@test.local")
    await grant(user, "Разработчик", extra)
    assert (await client.get(f"/api/v1/entities/{extra.id}", headers=h)).status_code == 200
    extra_id = extra.id
    await db.delete(extra)
    await db.commit()
    assert await db.scalar(select(RoleBinding).where(RoleBinding.entity_id == extra_id)) is None


async def test_any_binding_perms_count_in_not_stronger_rule(client, db, two_teams, make_user, grant):
    """Роль с group:read выдать нельзя, если у выдающего group:read нет нигде."""
    from app.authz.enforcer import set_role_permissions
    from app.models import Role, UserGroup
    from app.models.user_group import GroupSource

    t = two_teams
    role = Role(name="Только справочник групп")
    team = UserGroup(name="Цель", source=GroupSource.manual)
    db.add_all([role, team])
    await db.commit()
    set_role_permissions(role.name, [("group", "read")])
    lead, h = await make_user("lead-no-groups@test.local")
    # access:manage без group:read
    mgr = Role(name="Только доступ")
    db.add(mgr)
    await db.commit()
    set_role_permissions(mgr.name, [("access", "manage"), ("entity", "read")])
    await grant(lead, "Только доступ", t.a)
    r = await client.post(
        f"/api/v1/entities/{t.a.id}/bindings",
        json={"group_id": str(team.id), "role_id": str(role.id)},
        headers=h,
    )
    assert r.status_code == 403, r.text
