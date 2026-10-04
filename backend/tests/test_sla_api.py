"""API /sla-policies и настройки проекта (политика, теги)."""

from datetime import datetime, timedelta, timezone

from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding, make_policy

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
URL = "/api/v1/sla-policies"


async def test_developer_reads_but_cannot_manage(client, developer, db):
    _, headers = developer
    await make_policy(db, "def", is_default=True)
    r = await client.get(URL, headers=headers)
    assert r.status_code == 200 and r.json()[0]["is_default"]
    r = await client.post(URL, json={"name": "x"}, headers=headers)
    assert r.status_code == 403


async def test_create_validation_and_unique_name(client, appsec):
    _, headers = appsec
    r = await client.post(URL, json={"name": "a", "days_high": 0}, headers=headers)
    assert r.status_code == 422
    r = await client.post(URL, json={"name": "a", "days_high": 10}, headers=headers)
    assert r.status_code == 201 and r.json()["days_high"] == 10
    r = await client.post(URL, json={"name": "a"}, headers=headers)
    assert r.status_code == 409


async def test_switch_default_keeps_single_and_recomputes(client, appsec, db):
    _, headers = appsec
    old = await make_policy(db, "old", is_default=True)
    entity = await make_entity(db)
    f = await make_finding(db, entity, sla_start_at=T0)
    r = await client.post(URL, json={"name": "new", "days_high": 5}, headers=headers)
    new_id = r.json()["id"]
    r = await client.patch(f"{URL}/{new_id}", json={"is_default": True}, headers=headers)
    assert r.status_code == 200 and r.json()["is_default"]
    policies = {p["name"]: p["is_default"] for p in (await client.get(URL, headers=headers)).json()}
    assert policies == {"old": False, "new": True}
    await db.refresh(f)
    assert f.due_at == T0 + timedelta(days=5)

    r = await client.patch(f"{URL}/{new_id}", json={"is_default": False}, headers=headers)
    assert r.status_code == 409
    r = await client.delete(f"{URL}/{new_id}", headers=headers)
    assert r.status_code == 409
    assert (await client.delete(f"{URL}/{old.id}", headers=headers)).status_code == 204


async def test_change_days_recomputes_only_open(client, appsec, db):
    _, headers = appsec
    policy = await make_policy(db, "def", is_default=True)
    entity = await make_entity(db)
    open_f = await make_finding(db, entity, "a", sla_start_at=T0)
    closed_f = await make_finding(db, entity, "b", sla_start_at=T0, status=FindingStatus.fixed)
    r = await client.patch(f"{URL}/{policy.id}", json={"days_high": 7}, headers=headers)
    assert r.status_code == 200
    await db.refresh(open_f)
    await db.refresh(closed_f)
    assert open_f.due_at == T0 + timedelta(days=7)
    assert closed_f.due_at is None


async def test_delete_assigned_policy_conflicts(client, appsec, db):
    _, headers = appsec
    policy = await make_policy(db, "p")
    await make_entity(db, sla_policy_id=policy.id)
    r = await client.delete(f"{URL}/{policy.id}", headers=headers)
    assert r.status_code == 409
    listed = (await client.get(URL, headers=headers)).json()
    assert listed[0]["entities_count"] == 1


async def test_settings_policy_inheritance_and_subtree_recompute(client, appsec, db):
    _, headers = appsec
    await make_policy(db, "def", is_default=True)
    fast = await make_policy(db, "fast", high=3)
    root = await make_entity(db, "root")
    child = await make_entity(db, "child", parent_id=root.id)
    f = await make_finding(db, child, sla_start_at=T0)

    r = await client.patch(
        f"/api/v1/entities/{root.id}/settings", json={"sla_policy_id": str(fast.id)}, headers=headers
    )
    assert r.status_code == 200 and r.json()["sla"]["own"] is True
    assert "sla" not in r.json()["pinned_fields"]
    s = (await client.get(f"/api/v1/entities/{child.id}/settings", headers=headers)).json()
    assert s["sla"] == {
        "policy_id": str(fast.id), "policy_name": "fast", "own": False,
        "inherited_from": "root", "is_default": False,
    }
    await db.refresh(f)
    assert f.due_at == T0 + timedelta(days=3)

    r = await client.patch(
        f"/api/v1/entities/{root.id}/settings", json={"sla_policy_id": None}, headers=headers
    )
    assert r.json()["sla"]["is_default"] is True
    await db.refresh(f)
    assert f.due_at == T0 + timedelta(days=30)


async def test_settings_tags_validation_and_listing(client, appsec, db):
    _, headers = appsec
    root = await make_entity(db, "root")
    child = await make_entity(db, "child", parent_id=root.id)
    url = f"/api/v1/entities/{root.id}/settings"
    r = await client.patch(url, json={"tags": ["Env:Prod", "pci", "pci"]}, headers=headers)
    assert r.status_code == 200 and r.json()["tags"] == ["env:prod", "pci"]
    r = await client.patch(url, json={"tags": ["bad tag"]}, headers=headers)
    assert r.status_code == 422 and "bad tag" in r.json()["detail"]
    r = await client.patch(url, json={"tags": [f"t{i}" for i in range(21)]}, headers=headers)
    assert r.status_code == 422

    await client.patch(
        f"/api/v1/entities/{child.id}/settings", json={"tags": ["team:pay"]}, headers=headers
    )
    s = (await client.get(f"/api/v1/entities/{child.id}/settings", headers=headers)).json()
    assert s["effective_tags"] == [
        {"tag": "env:prod", "inherited_from": "root"},
        {"tag": "pci", "inherited_from": "root"},
        {"tag": "team:pay", "inherited_from": None},
    ]
    assert (await client.get("/api/v1/tags", headers=headers)).json() == ["env:prod", "pci", "team:pay"]


async def test_patch_duplicate_name_with_days_or_default_is_409(client, appsec, db):
    _, headers = appsec
    await make_policy(db, "def", is_default=True)
    other = await make_policy(db, "other")
    await make_entity(db, sla_policy_id=other.id)
    for body in ({"name": "def", "days_high": 10}, {"name": "def", "is_default": True}):
        r = await client.patch(f"{URL}/{other.id}", json=body, headers=headers)
        assert r.status_code == 409, body


async def test_move_entity_recomputes_inherited_due(client, appsec, db):
    _, headers = appsec
    await make_policy(db, "def", is_default=True)
    strict = await make_policy(db, "strict", high=3)
    a = await make_entity(db, "a", sla_policy_id=strict.id)
    b = await make_entity(db, "b")
    x = await make_entity(db, "x", parent_id=a.id)
    leaf = await make_entity(db, "leaf", parent_id=x.id)
    f = await make_finding(db, leaf, sla_start_at=T0)
    r = await client.patch(f"/api/v1/entities/{x.id}", json={"parent_id": str(b.id)}, headers=headers)
    assert r.status_code == 200
    await db.refresh(f)
    assert f.due_at == T0 + timedelta(days=30)
