"""Журнал аудита: API чтения, видимость и запись по действиям над проектами и доступом."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import audit


async def _seed(db, t):
    """По событию на a, a/svc, b и одно глобальное."""
    audit.record_audit(db, t.lead_a[0], audit.ENTITY_UPDATE, entity=t.a)
    audit.record_audit(db, t.lead_a[0], audit.BINDING_CREATE, entity=t.a_svc)
    audit.record_audit(db, t.lead_b[0], audit.ENTITY_UPDATE, entity=t.b)
    audit.record_audit(db, None, audit.ROLE_UPDATE, target=("role", None, "Аудитор"))
    await db.commit()


async def test_audit_requires_permission(client, two_teams):
    r = await client.get("/api/v1/audit", headers=two_teams.dev_a[1])
    assert r.status_code == 403


async def test_scoped_auditor_sees_only_subtree(client, db, two_teams):
    t = two_teams
    await _seed(db, t)
    r = await client.get("/api/v1/audit", headers=t.lead_a[1])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {i["entity_path"] for i in body["items"]} == {"a", "a/svc"}
    # новее — выше
    assert body["items"][0]["action"] == audit.BINDING_CREATE


async def test_global_auditor_sees_everything(client, db, two_teams, make_user):
    await _seed(db, two_teams)
    _, headers = await make_user("aud@test.local", roles=("Аудитор",))
    body = (await client.get("/api/v1/audit", headers=headers)).json()
    assert body["total"] == 4


async def test_entity_filter_subtree_and_404(client, db, two_teams):
    t = two_teams
    await _seed(db, t)
    h = t.lead_a[1]
    r = await client.get("/api/v1/audit", params={"entity_id": str(t.a.id)}, headers=h)
    assert r.json()["total"] == 2
    r = await client.get(
        "/api/v1/audit", params={"entity_id": str(t.a.id), "subtree": "false"}, headers=h
    )
    assert r.json()["total"] == 1
    r = await client.get("/api/v1/audit", params={"entity_id": str(t.b.id)}, headers=h)
    assert r.status_code == 404


async def test_filters_actor_action_dates_paging(client, db, two_teams, admin):
    t = two_teams
    await _seed(db, t)
    _, h = admin
    get = lambda **p: client.get("/api/v1/audit", params=p, headers=h)  # noqa: E731

    assert (await get(actor="LEAD-B")).json()["total"] == 1
    assert (await get(action="entity.update")).json()["total"] == 2
    assert (await get(action="binding.")).json()["total"] == 1
    assert (await get(action=["binding.", "role.update"])).json()["total"] == 2
    assert (await get(action=["entity.", "binding.create"])).json()["total"] == 3
    assert (await get(target_type="role")).json()["total"] == 1
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert (await get(date_from=future)).json()["total"] == 0
    assert (await get(date_to=future)).json()["total"] == 4
    page = (await get(limit=3, offset=3)).json()
    assert page["total"] == 4 and len(page["items"]) == 1


async def test_item_shape(client, db, two_teams, admin):
    t = two_teams
    audit.record_audit(
        db,
        t.lead_a[0],
        audit.ENTITY_UPDATE,
        target=("entity", t.a.id, "a"),
        entity=t.a,
        changes={"name": ["a", "A"]},
        ip="1.2.3.4",
    )
    await db.commit()
    item = (await client.get("/api/v1/audit", headers=admin[1])).json()["items"][0]
    assert item["actor_type"] == "user"
    assert item["actor_id"] == str(t.lead_a[0].id)
    assert item["actor_label"] == "lead-a@test.local"
    assert item["target_type"] == "entity" and item["target_id"] == str(t.a.id)
    assert item["entity_id"] == str(t.a.id)
    assert item["changes"] == {"name": ["a", "A"]}
    assert item["ip"] == "1.2.3.4"
    assert "created_at" in item


# --- запись: проекты ---


async def _log(db, action=None):
    from sqlalchemy import select

    from app.models import AuditLog

    q = select(AuditLog).order_by(AuditLog.created_at)
    if action:
        q = q.where(AuditLog.action == action)
    return (await db.scalars(q)).all()


async def test_entity_create_update_move_delete(client, db, admin):
    user, h = admin
    a = (await client.post("/api/v1/entities", json={"name": "A"}, headers=h)).json()
    b = (await client.post("/api/v1/entities", json={"name": "B"}, headers=h)).json()
    svc = (
        await client.post("/api/v1/entities", json={"name": "Svc", "parent_id": a["id"]}, headers=h)
    ).json()
    (created,) = [r for r in await _log(db, audit.ENTITY_CREATE) if r.target_label == "a/svc"]
    assert created.actor_id == user.id
    assert str(created.entity_id) == svc["id"]
    assert created.changes["parent_id"] == a["id"]
    assert created.changes["parent"] == "a"
    assert created.ip

    await client.patch(f"/api/v1/entities/{svc['id']}", json={"description": "d"}, headers=h)
    (upd,) = await _log(db, audit.ENTITY_UPDATE)
    assert upd.changes == {"description": [None, "d"]}

    r = await client.patch(f"/api/v1/entities/{svc['id']}", json={"parent_id": b["id"]}, headers=h)
    assert r.status_code == 200
    mv, mv_old = await _log(db, audit.ENTITY_MOVE)
    assert str(mv.entity_id) == svc["id"] and str(mv_old.entity_id) == a["id"]
    assert mv_old.changes == mv.changes
    assert mv.changes["path_cache"] == ["a/svc", "b/svc"]
    assert mv.changes["parent_id"] == [a["id"], b["id"]]
    assert mv.changes["parent"] == ["a", "b"]

    # пустая правка — без записи
    await client.patch(f"/api/v1/entities/{svc['id']}", json={"description": "d"}, headers=h)
    assert len(await _log(db, audit.ENTITY_UPDATE)) == 1

    assert (await client.delete(f"/api/v1/entities/{svc['id']}", headers=h)).status_code == 204
    (dl,) = await _log(db, audit.ENTITY_DELETE)
    assert str(dl.entity_id) == b["id"]  # удаление пишется на родителя
    assert dl.target_label == "b/svc" and dl.entity_path == "b"
    assert (await client.delete(f"/api/v1/entities/{b['id']}", headers=h)).status_code == 204
    root_del = (await _log(db, audit.ENTITY_DELETE))[-1]
    assert root_del.entity_id is None and root_del.target_label == "b"


async def test_entity_move_visible_to_old_parent_auditor(client, db, two_teams, admin):
    t, h = two_teams, admin[1]
    x = (await client.post("/api/v1/entities", json={"name": "X", "parent_id": str(t.a.id)}, headers=h)).json()
    deep = (await client.post("/api/v1/entities", json={"name": "Deep", "parent_id": x["id"]}, headers=h)).json()
    z = (await client.post("/api/v1/entities", json={"name": "Z", "parent_id": x["id"]}, headers=h)).json()
    # перенос вглубь ветки старого родителя — одна запись, её и так видно из a/x
    r = await client.patch(f"/api/v1/entities/{deep['id']}", json={"parent_id": z["id"]}, headers=h)
    assert r.status_code == 200
    assert len(await _log(db, audit.ENTITY_MOVE)) == 1
    r = await client.patch(f"/api/v1/entities/{x['id']}", json={"parent_id": str(t.b.id)}, headers=h)
    assert r.status_code == 200
    for lead in (t.lead_a, t.lead_b):
        items = (await client.get("/api/v1/audit", headers=lead[1])).json()["items"]
        assert any(i["action"] == audit.ENTITY_MOVE and i["target_label"] == "b/x" for i in items)


async def test_entity_delete_visible_to_parent_auditor(client, db, two_teams, admin):
    t = two_teams
    await client.delete(f"/api/v1/entities/{t.a_svc.id}", headers=admin[1])
    body = (await client.get("/api/v1/audit", headers=t.lead_a[1])).json()
    assert [i["action"] for i in body["items"]] == [audit.ENTITY_DELETE]


async def test_entity_delete_logs_subtree_bindings(client, db, two_teams, admin):
    from app.models import Role, RoleBinding, UserGroup
    from sqlalchemy import select

    t = two_teams
    role = await db.scalar(select(Role).where(Role.name == "Наблюдатель"))
    g = UserGroup(name="G")
    db.add(g)
    await db.flush()
    db.add_all([
        RoleBinding(group_id=g.id, role_id=role.id, entity_id=t.a_svc.id),
        RoleBinding(group_id=g.id, role_id=role.id, entity_id=t.a.id),  # выше — не сносится
    ])
    await db.commit()

    await client.delete(f"/api/v1/entities/{t.a_svc.id}", headers=admin[1])
    (cascaded,) = await _log(db, audit.BINDING_DELETE)
    # на родителя, как и само entity.delete: у удалённого проекта entity_id обнулится
    assert cascaded.entity_id == t.a.id
    assert cascaded.changes["entity"] == "a/svc"
    assert cascaded.changes["cascade"] == audit.ENTITY_DELETE
    assert cascaded.changes["group"] == "G"
    items = (await client.get("/api/v1/audit", headers=t.lead_a[1])).json()["items"]
    assert {i["action"] for i in items} == {audit.ENTITY_DELETE, audit.BINDING_DELETE}


async def test_upsert_by_path_logs_created_and_updated(client, db, admin):
    _, h = admin
    r = await client.put("/api/v1/entities/by-path/x/y", json={"name": "Y"}, headers=h)
    assert r.status_code == 200
    assert [r.target_label for r in await _log(db, audit.ENTITY_CREATE)] == ["x", "x/y"]
    await client.put("/api/v1/entities/by-path/x/y", json={"description": "z"}, headers=h)
    (upd,) = await _log(db, audit.ENTITY_UPDATE)
    assert upd.changes == {"description": [None, "z"]}


async def test_settings_rules_unpin_reassign(client, db, admin):
    from tests.factories import make_entity

    from app.models import UserGroup

    _, h = admin
    e = await make_entity(db, "p")
    g = UserGroup(name="Team")
    db.add(g)
    await db.commit()
    base = f"/api/v1/entities/{e.id}"

    r = await client.patch(f"{base}/settings", json={"default_branch": "dev"}, headers=h)
    assert r.status_code == 200
    (s,) = await _log(db, audit.ENTITY_SETTINGS_UPDATE)
    assert s.changes["default_branch"] == [None, "dev"]
    assert s.entity_id == e.id

    rules = [{"pattern": "src/**", "group_id": str(g.id)}]
    assert (await client.put(f"{base}/ownership-rules", json=rules, headers=h)).status_code == 200
    (o,) = await _log(db, audit.OWNERSHIP_RULES_UPDATE)
    assert o.changes == {
        "rules": [[], [{"pattern": "src/**", "group_id": str(g.id), "group": "Team"}]]
    }

    r = await client.patch(f"{base}/settings", json={"owner_group_id": str(g.id)}, headers=h)
    assert r.status_code == 200
    s2 = (await _log(db, audit.ENTITY_SETTINGS_UPDATE))[-1]
    assert s2.changes["owner_group_id"] == [None, str(g.id)]
    assert s2.changes["owner_group"] == [None, "Team"]

    p = (await client.post("/api/v1/sla-policies", json={"name": "Strict", "days_high": 5}, headers=h)).json()
    r = await client.patch(f"{base}/settings", json={"sla_policy_id": p["id"]}, headers=h)
    assert r.status_code == 200, r.text
    s3 = (await _log(db, audit.ENTITY_SETTINGS_UPDATE))[-1]
    assert s3.changes["sla_policy"] == [None, "Strict"]

    for token in ("t1", "t2"):
        url = f"https://ci:{token}@git.example/p.git"
        r = await client.patch(f"{base}/settings", json={"repo_url": url}, headers=h)
        assert r.status_code == 200, r.text
    s4 = (await _log(db, audit.ENTITY_SETTINGS_UPDATE))[-1]
    assert s4.changes == {"credentials_changed": ["repo_url"]}

    r = await client.post(f"{base}/settings/unpin", json={"field": "default_branch"}, headers=h)
    assert r.status_code == 200
    (u,) = await _log(db, audit.ENTITY_UNPIN)
    assert u.changes["field"] == "default_branch"

    assert (await client.post(f"{base}/reassign", headers=h)).status_code == 200
    (ra,) = await _log(db, audit.FINDINGS_REASSIGN)
    assert ra.changes == {"reassigned": 0}


async def test_import_auto_create_logs_entities(client, db, admin):
    from tests.factories import make_sarif

    _, h = admin
    files = {"file": ("r.sarif", make_sarif("Semgrep", []), "application/json")}
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "n/m", "auto_create": "true"},
        files=files,
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert [r.target_label for r in await _log(db, audit.ENTITY_CREATE)] == ["n", "n/m"]


async def test_import_with_config_logs_settings_change(client, db, admin):
    from tests.factories import make_entity, make_group, make_sarif

    _, h = admin
    await make_entity(db, "cfg")
    team = await make_group(db, "pay")
    config = b"version: 1\ndefault_branch: main\nownership:\n  - path: src/pay/\n    owner: pay\n"

    def files():
        return {
            "file": ("s.sarif", make_sarif("Semgrep", []), "application/json"),
            "config": (".secretvuln.yml", config, "application/x-yaml"),
        }

    # Ветка отклонена — импорт и настройки откатываются вместе с записью журнала
    r = await client.post(
        "/api/v1/imports", data={"project_path": "cfg", "branch": "feature"}, files=files(), headers=h
    )
    assert r.status_code == 422, r.text
    assert await _log(db, audit.ENTITY_SETTINGS_UPDATE) == []

    r = await client.post(
        "/api/v1/imports", data={"project_path": "cfg", "branch": "main"}, files=files(), headers=h
    )
    assert r.status_code == 201, r.text
    [row] = await _log(db, audit.ENTITY_SETTINGS_UPDATE)
    assert row.changes == {"source": "config", "default_branch": [None, "main"]}
    [rules] = await _log(db, audit.OWNERSHIP_RULES_UPDATE)
    assert rules.changes == {
        "source": "config",
        "rules": [[], [{"pattern": "src/pay/", "group_id": str(team.id), "group": team.name}]],
    }


# --- запись: доступ, группы, роли, SLA ---


async def test_groups_and_members(client, db, admin, make_user):
    _, h = admin
    member, _ = await make_user("m@test.local")
    g = (await client.post("/api/v1/groups", json={"name": "Team"}, headers=h)).json()
    await client.patch(f"/api/v1/groups/{g['id']}", json={"description": "x"}, headers=h)
    await client.post(f"/api/v1/groups/{g['id']}/members/{member.id}", headers=h)
    await client.post(f"/api/v1/groups/{g['id']}/members/{member.id}", headers=h)  # повтор
    await client.delete(f"/api/v1/groups/{g['id']}/members/{member.id}", headers=h)
    await client.delete(f"/api/v1/groups/{g['id']}", headers=h)

    rows = await _log(db)
    assert [r.action for r in rows] == [
        audit.GROUP_CREATE,
        audit.GROUP_UPDATE,
        audit.GROUP_MEMBER_ADD,
        audit.GROUP_MEMBER_REMOVE,
        audit.GROUP_DELETE,
    ]
    assert all(r.entity_id is None and r.target_label == "Team" for r in rows)
    assert rows[1].changes == {"description": [None, "x"]}
    assert rows[2].changes == {"user": "m@test.local"}


async def test_group_ldap_sync_logs_only_changes(client, db, admin, monkeypatch):
    from app.services.auth.ldap import LdapMember

    _, h = admin
    g = (
        await client.post(
            "/api/v1/groups", json={"name": "L", "source": "ldap", "ldap_group": "l"}, headers=h
        )
    ).json()
    monkeypatch.setattr(
        "app.api.groups.list_group_members",
        lambda name: [LdapMember(dn="uid=x", email="x@test.local", full_name="X")],
    )
    for _ in range(2):
        r = await client.post(f"/api/v1/groups/{g['id']}/sync", headers=h)
        assert r.status_code == 200
    (add,) = await _log(db, audit.GROUP_MEMBER_ADD)
    assert add.actor_id is None and add.changes == {"user": "x@test.local"}
    (sync,) = await _log(db, audit.GROUP_SYNC)
    assert sync.actor_id is not None
    assert sync.changes == {"added": 1, "removed": 0, "provisioned": 1}


async def test_roles_and_permissions(client, db, admin):
    _, h = admin
    perms = [{"resource": "entity", "action": "read"}]
    role = (
        await client.post("/api/v1/roles", json={"name": "R", "permissions": perms}, headers=h)
    ).json()
    await client.patch(f"/api/v1/roles/{role['id']}", json={"name": "R2"}, headers=h)
    new = perms + [{"resource": "audit", "action": "read"}]
    await client.put(f"/api/v1/roles/{role['id']}/permissions", json={"permissions": new}, headers=h)
    await client.put(f"/api/v1/roles/{role['id']}/permissions", json={"permissions": new}, headers=h)
    await client.delete(f"/api/v1/roles/{role['id']}", headers=h)

    rows = await _log(db)
    assert [r.action for r in rows] == [
        audit.ROLE_CREATE,
        audit.ROLE_UPDATE,
        audit.ROLE_PERMISSIONS_UPDATE,
        audit.ROLE_DELETE,
    ]
    assert rows[0].changes["permissions"] == ["entity:read"]
    assert rows[1].changes == {"name": ["R", "R2"]}
    assert rows[2].changes == {"added": ["audit:read"], "removed": []}
    assert rows[3].changes["permissions"] == ["audit:read", "entity:read"]


async def test_role_rename_to_taken_name_is_409(client, db, admin):
    from app.authz.policies import get_permissions

    _, h = admin
    perms = [{"resource": "entity", "action": "read"}]
    await client.post("/api/v1/roles", json={"name": "A", "permissions": perms}, headers=h)
    b = (await client.post("/api/v1/roles", json={"name": "B", "permissions": []}, headers=h)).json()
    r = await client.patch(f"/api/v1/roles/{b['id']}", json={"name": "A"}, headers=h)
    assert r.status_code == 409
    assert (await get_permissions(db, ["A"]))["A"] == [("entity", "read")]


async def test_role_permissions_roll_back_with_audit(client, db, admin, monkeypatch):
    """Права роли и запись журнала — одна транзакция: сбой записи не меняет права."""
    import pytest

    from app.api import roles as roles_api
    from app.authz.policies import get_permissions

    _, h = admin
    perms = [{"resource": "entity", "action": "read"}]
    role = (
        await client.post("/api/v1/roles", json={"name": "R", "permissions": perms}, headers=h)
    ).json()

    def boom(*args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(roles_api, "_record", boom)
    new = perms + [{"resource": "audit", "action": "read"}]
    with pytest.raises(RuntimeError):
        await client.put(
            f"/api/v1/roles/{role['id']}/permissions", json={"permissions": new}, headers=h
        )
    assert (await get_permissions(db, ["R"]))["R"] == [("entity", "read")]


async def test_bindings_project_and_global(client, db, two_teams, admin):
    from app.models import Role, UserGroup
    from sqlalchemy import select

    t = two_teams
    role = await db.scalar(select(Role).where(Role.name == "Разработчик"))
    g = UserGroup(name="Devs")
    db.add(g)
    await db.commit()
    body = {"group_id": str(g.id), "role_id": str(role.id)}

    r = await client.post(f"/api/v1/entities/{t.a.id}/bindings", json=body, headers=t.lead_a[1])
    assert r.status_code == 201, r.text
    await client.delete(f"/api/v1/bindings/{r.json()['id']}", headers=t.lead_a[1])
    r = await client.post(
        f"/api/v1/groups/{g.id}/bindings", json={"role_id": str(role.id)}, headers=admin[1]
    )
    assert r.status_code == 201, r.text
    await client.delete(f"/api/v1/groups/{g.id}/bindings/{r.json()['id']}", headers=admin[1])

    rows = await _log(db)
    assert [r.action for r in rows] == [audit.BINDING_CREATE, audit.BINDING_DELETE] * 2
    assert rows[0].entity_id == t.a.id and rows[0].actor_id == t.lead_a[0].id
    assert rows[0].target_label == "Devs → Разработчик @ a"
    assert rows[0].changes == {"group": "Devs", "role": "Разработчик", "entity": "a"}
    assert rows[2].entity_id is None and rows[2].target_label.endswith("@ *")
    # руководитель a видит выдачу доступа на своей ветке, но не глобальные
    items = (await client.get("/api/v1/audit", headers=t.lead_a[1])).json()["items"]
    assert len(items) == 2


async def test_sla_policies(client, db, admin):
    _, h = admin
    p = (await client.post("/api/v1/sla-policies", json={"name": "S", "days_high": 5}, headers=h)).json()
    await client.patch(f"/api/v1/sla-policies/{p['id']}", json={"days_high": 7}, headers=h)
    await client.delete(f"/api/v1/sla-policies/{p['id']}", headers=h)
    rows = await _log(db)
    assert [r.action for r in rows] == [
        audit.SLA_POLICY_CREATE,
        audit.SLA_POLICY_UPDATE,
        audit.SLA_POLICY_DELETE,
    ]
    assert rows[0].changes["days_high"] == 5
    assert rows[1].changes == {"days_high": [5, 7]}


async def test_group_and_role_delete_log_cascaded_bindings(client, db, two_teams, admin):
    from app.models import Role, RoleBinding, UserGroup

    t = two_teams
    h = admin[1]
    role = (
        await client.post(
            "/api/v1/roles",
            json={"name": "Tmp", "permissions": [{"resource": "entity", "action": "read"}]},
            headers=h,
        )
    ).json()
    g1, g2 = UserGroup(name="G1"), UserGroup(name="G2")
    db.add_all([g1, g2])
    await db.flush()
    db.add_all([
        RoleBinding(group_id=g1.id, role_id=role["id"], entity_id=t.a.id),
        RoleBinding(group_id=g2.id, role_id=role["id"], entity_id=None),
    ])
    await db.commit()

    assert (await client.delete(f"/api/v1/groups/{g1.id}", headers=h)).status_code == 204
    (cascaded,) = await _log(db, audit.BINDING_DELETE)
    assert cascaded.entity_id == t.a.id
    assert cascaded.changes == {
        "group": "G1", "role": "Tmp", "entity": "a", "cascade": audit.GROUP_DELETE,
    }
    # руководитель a видит, что доступ к его ветке пропал
    items = (await client.get("/api/v1/audit", headers=t.lead_a[1])).json()["items"]
    assert [i["action"] for i in items] == [audit.BINDING_DELETE]

    assert (await client.delete(f"/api/v1/roles/{role['id']}", headers=h)).status_code == 204
    rows = await _log(db, audit.BINDING_DELETE)
    assert len(rows) == 2
    assert rows[1].entity_id is None and rows[1].changes["cascade"] == audit.ROLE_DELETE
    assert rows[1].changes["group"] == "G2"
