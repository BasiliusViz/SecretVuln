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
