"""Комментарии, запрос помощи AppSec, массовые действия, права текущего пользователя."""

from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding, make_group


async def test_comment_listed_with_author(client, developer, db):
    user, h = developer
    f = await make_finding(db, await make_entity(db, "svc"), "fp")
    r = await client.post(f"/api/v1/findings/{f.id}/comments", json={"text": "  Смотрю  "}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["event_type"] == "comment"
    assert r.json()["reason"] == "Смотрю"
    events = (await client.get(f"/api/v1/findings/{f.id}/events", headers=h)).json()
    assert events[-1]["actor_name"] == user.email


async def test_help_request_and_resolution(client, developer, appsec, db):
    _, dev_h = developer
    _, sec_h = appsec
    f = await make_finding(db, await make_entity(db, "svc"), "fp")

    r = await client.post(f"/api/v1/findings/{f.id}/help", json={"text": "Это правда уязвимость?"}, headers=dev_h)
    assert r.status_code == 200, r.text
    assert r.json()["help_requested_at"] is not None
    r = await client.post(f"/api/v1/findings/{f.id}/help", json={"text": "ещё"}, headers=dev_h)
    assert r.status_code == 409

    r = await client.post(
        f"/api/v1/findings/{f.id}/comments", json={"text": "ok", "resolve_help": True}, headers=dev_h
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/findings/{f.id}/comments", json={"text": "Да, исправляйте", "resolve_help": True},
        headers=sec_h,
    )
    assert r.status_code == 201
    detail = (await client.get(f"/api/v1/findings/{f.id}", headers=sec_h)).json()
    assert detail["help_requested_at"] is None
    types = [e["event_type"] for e in (await client.get(f"/api/v1/findings/{f.id}/events", headers=sec_h)).json()]
    # комментарий и снятие флага пишутся в одной транзакции (одинаковый created_at) — порядок между ними не гарантирован
    assert types[-3] == "help_requested"
    assert set(types[-2:]) == {"comment", "help_resolved"}


async def test_help_on_closed_finding_rejected(client, developer, db):
    _, h = developer
    f = await make_finding(db, await make_entity(db, "svc"), "fp", status=FindingStatus.fixed)
    r = await client.post(f"/api/v1/findings/{f.id}/help", json={"text": "?"}, headers=h)
    assert r.status_code == 409


async def test_bulk_confirm_skips_closed(client, appsec, db):
    _, h = appsec
    e = await make_entity(db, "svc")
    a = await make_finding(db, e, "a")
    b = await make_finding(db, e, "b", status=FindingStatus.fixed)
    r = await client.post(
        "/api/v1/findings/bulk",
        json={"ids": [str(a.id), str(b.id), "00000000-0000-0000-0000-000000000000"], "action": "confirm"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 1
    assert {s["id"] for s in body["skipped"]} == {str(b.id), "00000000-0000-0000-0000-000000000000"}
    await db.refresh(a)
    assert a.status == FindingStatus.confirmed


async def test_bulk_false_positive_needs_approve(client, developer, appsec, db):
    e = await make_entity(db, "svc")
    a = await make_finding(db, e, "a")
    body = {"ids": [str(a.id)], "action": "false_positive", "reason_tag": "test_code"}
    _, dev_h = developer
    assert (await client.post("/api/v1/findings/bulk", json=body, headers=dev_h)).status_code == 403

    _, sec_h = appsec
    r = await client.post("/api/v1/findings/bulk", json=body, headers=sec_h)
    assert r.json()["applied"] == 1
    await db.refresh(a)
    assert a.status == FindingStatus.false_positive

    r = await client.post(
        "/api/v1/findings/bulk",
        json={"ids": [str(a.id)], "action": "false_positive", "reason_tag": "other"},
        headers=sec_h,
    )
    assert r.status_code == 422


async def test_bulk_assign(client, appsec, db):
    _, h = appsec
    team = await make_group(db, "team")
    a = await make_finding(db, await make_entity(db, "svc"), "a")
    r = await client.post(
        "/api/v1/findings/bulk",
        json={"ids": [str(a.id)], "action": "assign", "group_id": str(team.id)},
        headers=h,
    )
    assert r.json()["applied"] == 1
    await db.refresh(a)
    assert a.assignee_group_id == team.id
    assert a.assigned_manually is True
    r = await client.post("/api/v1/findings/bulk", json={"ids": [str(a.id)], "action": "assign"}, headers=h)
    assert r.status_code == 422


async def test_me_lists_permissions(client, developer):
    _, h = developer
    perms = (await client.get("/api/v1/auth/me", headers=h)).json()["permissions"]
    assert "finding:triage" in perms
    assert "finding:approve" not in perms
