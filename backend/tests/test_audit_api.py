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
