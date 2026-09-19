from datetime import datetime, timedelta, timezone

from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding


def _fp(tag="test_code", reason=None):
    body = {"decision_type": "false_positive", "reason_tag": tag}
    if reason is not None:
        body["reason"] = reason
    return body


async def test_developer_request_waits_for_appsec(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 201
    assert r.json()["status"] == "pending"
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=headers)).json()
    assert finding["status"] == "new"
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=headers)).json()
    assert events[-1]["event_type"] == "request_created"
    assert events[-1]["reason_tag"] == "test_code"


async def test_second_pending_request_conflicts(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 409


async def test_validation(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    url = f"/api/v1/findings/{f.id}/decisions"
    assert (await client.post(url, json=_fp(tag="other"), headers=headers)).status_code == 422
    assert (await client.post(url, json={"decision_type": "false_positive"}, headers=headers)).status_code == 422
    risk = {"decision_type": "risk_accepted", "reason": "Сервис выводим из эксплуатации"}
    assert (await client.post(url, json=risk, headers=headers)).status_code == 422
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert (await client.post(url, json={**risk, "expires_at": past}, headers=headers)).status_code == 422


async def test_appsec_approves(client, developer, appsec, db):
    _, dev_h = developer
    sec_user, sec_h = appsec
    f = await make_finding(db, await make_entity(db))
    req = (await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)).json()

    r = await client.post(f"/api/v1/decisions/{req['id']}/approve", json={"comment": "Ок"}, headers=sec_h)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["decided_by_id"] == str(sec_user.id)
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=sec_h)).json()
    assert finding["status"] == "false_positive"
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=sec_h)).json()
    assert events[-1]["event_type"] == "request_decided"
    assert events[-1]["to_status"] == "false_positive"


async def test_developer_cannot_approve(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db))
    req = (await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)).json()
    r = await client.post(f"/api/v1/decisions/{req['id']}/approve", json={}, headers=headers)
    assert r.status_code == 403


async def test_appsec_decision_applies_immediately(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 201
    assert r.json()["status"] == "approved"
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=headers)).json()
    assert finding["status"] == "false_positive"


async def test_reject_requires_comment_and_keeps_status(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db))
    req = (await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)).json()
    url = f"/api/v1/decisions/{req['id']}/reject"
    assert (await client.post(url, json={}, headers=sec_h)).status_code == 422
    r = await client.post(url, json={"comment": "Данные приходят из query-параметра"}, headers=sec_h)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=sec_h)).json()
    assert finding["status"] == "new"
    # после отклонения можно подать новый запрос
    again = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)
    assert again.status_code == 201


async def test_request_on_closed_finding_conflicts(client, developer, db):
    _, headers = developer
    f = await make_finding(db, await make_entity(db), status=FindingStatus.fixed)
    r = await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=headers)
    assert r.status_code == 409


async def test_risk_acceptance_with_expiry(client, appsec, db):
    _, headers = appsec
    f = await make_finding(db, await make_entity(db))
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = await client.post(
        f"/api/v1/findings/{f.id}/decisions",
        json={"decision_type": "risk_accepted", "reason": "Компенсирующий WAF", "expires_at": expires},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["expires_at"] is not None
    finding = (await client.get(f"/api/v1/findings/{f.id}", headers=headers)).json()
    assert finding["status"] == "risk_accepted"


async def test_pending_list(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db))
    await client.post(f"/api/v1/findings/{f.id}/decisions", json=_fp(), headers=dev_h)
    r = await client.get("/api/v1/decisions", params={"status": "pending"}, headers=sec_h)
    assert r.status_code == 200
    assert [d["finding_id"] for d in r.json()] == [str(f.id)]
