"""Фильтры списка уязвимостей: мои, без владельца, команда, несколько статусов, сортировка."""

from datetime import datetime, timezone

from app.models import user_group_members
from app.models.finding import FindingStatus, Severity
from tests.factories import make_entity, make_finding, make_group


async def _numbers(client, h, query):
    r = await client.get(f"/api/v1/findings?{query}", headers=h)
    assert r.status_code == 200, r.text
    return sorted(x["fingerprint"] for x in r.json())


async def test_mine_unassigned_and_team(client, developer, db):
    user, h = developer
    team = await make_group(db, "team")
    other = await make_group(db, "other")
    await db.execute(user_group_members.insert().values(group_id=team.id, user_id=user.id))
    await db.commit()
    e = await make_entity(db, "svc")
    await make_finding(db, e, "team", assignee_group_id=team.id)
    await make_finding(db, e, "other", assignee_group_id=other.id)
    await make_finding(db, e, "personal", assignee_group_id=other.id, assignee_user_id=user.id)
    await make_finding(db, e, "nobody")

    assert await _numbers(client, h, "mine=true") == ["personal", "team"]
    assert await _numbers(client, h, "unassigned=true") == ["nobody"]
    assert await _numbers(client, h, f"assignee_group_id={other.id}") == ["other", "personal"]


async def test_multi_status_help_and_order(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    await make_finding(db, e, "low", severity=Severity.low, status=FindingStatus.confirmed)
    await make_finding(db, e, "crit", severity=Severity.critical, status=FindingStatus.in_progress)
    await make_finding(db, e, "new", status=FindingStatus.new,
                       help_requested_at=datetime.now(timezone.utc))

    assert await _numbers(client, h, "status=confirmed&status=in_progress") == ["crit", "low"]
    assert await _numbers(client, h, "help_requested=true") == ["new"]
    r = await client.get("/api/v1/findings?order=severity&status=confirmed&status=in_progress", headers=h)
    assert [x["fingerprint"] for x in r.json()] == ["crit", "low"]


async def test_pending_decision_filter(client, developer, db):
    _, h = developer
    e = await make_entity(db, "svc")
    a = await make_finding(db, e, "asked")
    await make_finding(db, e, "quiet")
    r = await client.post(
        f"/api/v1/findings/{a.id}/decisions",
        json={"decision_type": "false_positive", "reason_tag": "test_code"},
        headers=h,
    )
    assert r.status_code == 201
    assert await _numbers(client, h, "pending_decision=true") == ["asked"]
