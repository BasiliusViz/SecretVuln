"""Права на поддерево: находки, решения, метрики, группы с has_access."""

from __future__ import annotations

from app.models import DecisionRequest, DecisionStatus, DecisionType
from tests.factories import make_finding, make_group


async def _two_findings(db, t):
    fa = await make_finding(db, t.a_svc, "fa", number=1)
    fb = await make_finding(db, t.b_svc, "fb", number=2)
    return fa, fb


async def test_lists_return_only_own_branch(client, db, two_teams):
    t = two_teams
    fa, fb = await _two_findings(db, t)
    _, h = t.dev_a
    ids = {f["id"] for f in (await client.get("/api/v1/findings", headers=h)).json()}
    assert ids == {str(fa.id)}
    stats = (await client.get("/api/v1/findings/stats", headers=h)).json()
    assert stats["total"] == 1
    r = await client.post(
        "/api/v1/metrics/aggregate",
        json={"metric": "count", "group_by": "none", "period": "30d"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert sum(row["value"] for row in r.json()["rows"]) == 1


async def test_entity_filter_on_stub_ancestor_and_invisible(client, db, two_teams, make_user, grant):
    t = two_teams
    fa = await make_finding(db, t.a_svc, "fa")
    await make_finding(db, t.a, "on-a")  # на самой a — не доступна
    user, h = await make_user("deep@test.local")
    await grant(user, "Разработчик", t.a_svc)
    r = await client.get(
        "/api/v1/findings", params={"entity_id": str(t.a.id), "include_descendants": True},
        headers=h,
    )
    assert r.status_code == 200
    assert {f["id"] for f in r.json()} == {str(fa.id)}
    r = await client.get("/api/v1/findings", params={"entity_id": str(t.b.id)}, headers=h)
    assert r.status_code == 404
    r = await client.get("/api/v1/findings/stats", params={"entity_id": str(t.b.id)}, headers=h)
    assert r.status_code == 404


async def test_point_endpoints_404_for_foreign(client, db, two_teams):
    t = two_teams
    fa, fb = await _two_findings(db, t)
    _, h = t.dev_a
    assert (await client.get(f"/api/v1/findings/{fb.id}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/findings/by-number/2", headers=h)).status_code == 404
    assert (await client.get("/api/v1/findings/by-number/1", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/findings/{fb.id}/events", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/findings/{fb.id}/decisions", headers=h)).status_code == 404
    r = await client.patch(f"/api/v1/findings/{fb.id}", json={"status": "confirmed"}, headers=h)
    assert r.status_code == 404
    r = await client.post(f"/api/v1/findings/{fb.id}/assign", json={"by_rules": True}, headers=h)
    assert r.status_code == 404
    r = await client.post(f"/api/v1/findings/{fb.id}/help", json={"text": "?"}, headers=h)
    assert r.status_code == 404
    r = await client.patch(f"/api/v1/findings/{fa.id}", json={"status": "confirmed"}, headers=h)
    assert r.status_code == 200


async def test_read_without_triage_is_403(client, db, two_teams, make_user, grant):
    t = two_teams
    fa = await make_finding(db, t.a_svc, "fa")
    user, h = await make_user("viewer@test.local")
    await grant(user, "Наблюдатель", t.a)
    await grant(user, "Разработчик", t.b)  # triage где-то есть — ворота пройдены
    r = await client.patch(f"/api/v1/findings/{fa.id}", json={"status": "confirmed"}, headers=h)
    assert r.status_code == 403


async def test_bulk_all_or_nothing(client, db, two_teams):
    t = two_teams
    fa, fb = await _two_findings(db, t)
    _, h = t.dev_a
    r = await client.post(
        "/api/v1/findings/bulk", json={"ids": [str(fa.id), str(fb.id)], "action": "confirm"},
        headers=h,
    )
    assert r.status_code == 404
    await db.refresh(fa)
    assert fa.status.value == "new"


async def test_decisions_scoped_and_approve_on_project(client, db, two_teams, make_user, grant):
    t = two_teams
    fa, fb = await _two_findings(db, t)
    reqs = []
    for f in (fa, fb):
        req = DecisionRequest(
            finding_id=f.id, decision_type=DecisionType.false_positive,
            status=DecisionStatus.pending, reason="x",
        )
        db.add(req)
        reqs.append(req)
    await db.commit()
    appsec_a, h = await make_user("sec-a@test.local")
    await grant(appsec_a, "Инженер ИБ", t.a)
    items = (await client.get("/api/v1/decisions", headers=h)).json()
    assert [(i["finding_id"], i["can_approve"], i["entity_path"]) for i in items] == [
        (str(fa.id), True, "a/svc")
    ]
    r = await client.post(f"/api/v1/decisions/{reqs[1].id}/approve", json={}, headers=h)
    assert r.status_code == 404
    r = await client.post(f"/api/v1/decisions/{reqs[0].id}/approve", json={}, headers=h)
    assert r.status_code == 200, r.text


async def test_groups_has_access_flag(client, db, two_teams):
    t = two_teams
    await make_group(db, "team-b")
    _, h = t.lead_a
    r = await client.get("/api/v1/groups", params={"entity_id": str(t.a_svc.id)}, headers=h)
    assert r.status_code == 200
    flags = {g["name"]: g["has_access"] for g in r.json()}
    assert flags["personal:dev-a@test.local"] is True
    assert flags["personal:lead-b@test.local"] is False
    assert flags["team-b"] is False
    r = await client.get("/api/v1/groups", params={"entity_id": str(t.b.id)}, headers=h)
    assert r.status_code == 404


async def test_noisy_rules_scoped(client, db, two_teams):
    from app.models import FindingStatus

    t = two_teams
    for i in range(3):
        await make_finding(db, t.b_svc, f"n{i}", rule_id="noisy", status=FindingStatus.false_positive)
    _, h = t.dev_a
    r = await client.get("/api/v1/findings/noisy-rules", params={"min_decided": 1}, headers=h)
    assert r.json() == []
    _, hb = t.lead_b
    r = await client.get("/api/v1/findings/noisy-rules", params={"min_decided": 1}, headers=hb)
    assert [x["rule_id"] for x in r.json()] == ["noisy"]


async def test_role_change_applies_without_relogin(client, db, two_teams):
    from app.authz.enforcer import set_role_permissions

    t = two_teams
    await make_finding(db, t.a_svc, "fa")
    _, h = t.dev_a
    assert (await client.get("/api/v1/findings", headers=h)).status_code == 200
    set_role_permissions("Разработчик", [("entity", "read")])
    assert (await client.get("/api/v1/findings", headers=h)).status_code == 403
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert me["scoped_permissions"] == {"entity:read": ["a"]}
    assert me["permissions"] == ["entity:read"]


async def test_me_scoped_permissions(client, two_teams):
    _, h = two_teams.lead_a
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert me["scoped_permissions"]["finding:read"] == ["a"]
    assert me["scoped_permissions"]["group:read"] == "*"
    assert "role:read" not in me["permissions"]
    assert me["roles"] == ["Руководитель команды"]
