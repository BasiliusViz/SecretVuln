from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding


async def test_developer_takes_finding_in_progress(client, developer, db):
    user, headers = developer
    f = await make_finding(db, await make_entity(db))
    r = await client.patch(
        f"/api/v1/findings/{f.id}",
        json={"status": "in_progress", "reason": "Чиню в MR !42"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"

    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=headers)).json()
    last = events[-1]
    assert last["event_type"] == "status_changed"
    assert last["actor_type"] == "user"
    assert last["actor_id"] == str(user.id)
    assert last["from_status"] == "new"
    assert last["to_status"] == "in_progress"
    assert last["reason"] == "Чиню в MR !42"


async def test_decision_statuses_go_through_requests(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    for st in ("false_positive", "risk_accepted"):
        r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": st}, headers=headers)
        assert r.status_code == 400
        assert "decisions" in r.json()["detail"]


async def test_fixed_cannot_be_set_manually(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "fixed"}, headers=headers)
    assert r.status_code == 400


async def test_only_appsec_can_undo_decision(client, developer, appsec, db):
    f = await make_finding(db, await make_entity(db), status=FindingStatus.false_positive)
    _, dev_h = developer
    _, sec_h = appsec
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "new"}, headers=dev_h)
    assert r.status_code == 403
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "new"}, headers=sec_h)
    assert r.status_code == 200
    assert r.json()["status"] == "new"


async def test_same_status_is_noop(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    r = await client.patch(f"/api/v1/findings/{f.id}", json={"status": "new"}, headers=headers)
    assert r.status_code == 200
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=headers)).json()
    assert events == []
