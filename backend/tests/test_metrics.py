from datetime import datetime, timedelta, timezone

from app.models import ActorType, FindingEvent, FindingEventType
from app.models.finding import FindingStatus, Severity
from tests.factories import make_entity, make_finding, make_group

URL = "/api/v1/metrics/aggregate"
NOW = datetime.now(timezone.utc)


async def _event(db, finding, to, at, frm=FindingStatus.new):
    db.add(FindingEvent(
        finding_id=finding.id, event_type=FindingEventType.status_changed,
        actor_type=ActorType.system, from_status=frm, to_status=to, created_at=at,
    ))
    await db.flush()


async def _data(db):
    team = await make_group(db, "pay")
    prod = await make_entity(db, "prod", tags=["env:prod"])
    dev = await make_entity(db, "dev")
    d = timedelta(days=1)
    # открытые: одна просрочена, одна в сроке, одна без срока
    await make_finding(db, prod, "late", severity=Severity.critical, due_at=NOW - d,
                       first_seen=NOW - 10 * d, assignee_group_id=team.id)
    await make_finding(db, prod, "ok", severity=Severity.high, due_at=NOW + d, first_seen=NOW - 3 * d)
    await make_finding(db, dev, "nodue", severity=Severity.info, first_seen=NOW - 100 * d)
    # закрытые: исправлена за 4 дня, ложная, исправлена давно
    # метрики закрытий считаются по истории — у каждой закрытой есть событие
    fixed = await make_finding(db, prod, "fixed", status=FindingStatus.fixed,
                               first_seen=NOW - 6 * d, resolved_at=NOW - 2 * d)
    await _event(db, fixed, FindingStatus.fixed, NOW - 2 * d)
    fp = await make_finding(db, dev, "fp", status=FindingStatus.false_positive,
                            first_seen=NOW - 5 * d, resolved_at=NOW - 1 * d)
    await _event(db, fp, FindingStatus.false_positive, NOW - 1 * d)
    old = await make_finding(db, dev, "old", status=FindingStatus.fixed,
                             first_seen=NOW - 400 * d, resolved_at=NOW - 200 * d)
    await _event(db, old, FindingStatus.fixed, NOW - 200 * d)
    await db.commit()
    return team, prod


async def _q(client, headers, **body):
    r = await client.post(URL, json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["rows"]


async def test_each_metric(client, developer, db):
    _, h = developer
    await _data(db)
    assert (await _q(client, h, metric="count"))[0]["value"] == 3
    assert (await _q(client, h, metric="opened", period="30d"))[0]["value"] == 4
    assert (await _q(client, h, metric="resolved", period="30d"))[0]["value"] == 2
    assert (await _q(client, h, metric="overdue"))[0]["value"] == 1
    assert (await _q(client, h, metric="sla_ratio"))[0]["value"] == 0.5
    assert (await _q(client, h, metric="mttr_days", period="30d"))[0]["value"] == 4.0


async def test_reopened_keeps_past_closure(client, developer, db):
    """Переоткрытие обнуляет resolved_at, но закрытие за период остаётся в метриках."""
    _, h = developer
    e = await make_entity(db, "svc")
    d = timedelta(days=1)
    f = await make_finding(db, e, "again", first_seen=NOW - 10 * d)  # сейчас открыта
    await _event(db, f, FindingStatus.fixed, NOW - 4 * d)
    await _event(db, f, FindingStatus.new, NOW - 3 * d, frm=FindingStatus.fixed)
    await _event(db, f, FindingStatus.fixed, NOW - 2 * d)
    # «ложное → исправлено» — не новое закрытие
    await _event(db, f, FindingStatus.fixed, NOW - 1 * d, frm=FindingStatus.false_positive)
    await db.commit()
    assert (await _q(client, h, metric="resolved", period="30d"))[0]["value"] == 1
    # закрытия через 6 и 8 дней после появления
    assert (await _q(client, h, metric="mttr_days", period="30d"))[0]["value"] == 7.0
    rows = await _q(client, h, metric="resolved", group_by="week", period="30d")
    assert sum(r["value"] for r in rows) >= 1


async def test_grouping_and_filters(client, developer, db):
    _, h = developer
    team, prod = await _data(db)
    rows = await _q(client, h, metric="count", group_by="severity")
    assert {r["key"]: r["value"] for r in rows} == {"critical": 1, "high": 1, "info": 1}
    rows = await _q(client, h, metric="count", group_by="team")
    assert {r["label"]: r["value"] for r in rows} == {"pay": 1, None: 2}
    rows = await _q(client, h, metric="count", group_by="entity")
    assert {r["label"]: r["value"] for r in rows} == {"prod": 2, "dev": 1}
    rows = await _q(client, h, metric="count", filters={"tag": "env:prod"})
    assert rows[0]["value"] == 2
    rows = await _q(client, h, metric="count", filters={"entity_id": str(prod.id), "severity": ["critical"]})
    assert rows[0]["value"] == 1
    rows = await _q(client, h, metric="opened", group_by="week", period="30d")
    assert sum(r["value"] for r in rows) == 4
    assert all(len(r["key"]) == 10 for r in rows)
    assert [r["key"] for r in rows] == sorted(r["key"] for r in rows)


async def test_empty_and_whitelists(client, developer):
    _, h = developer
    assert (await _q(client, h, metric="mttr_days"))[0]["value"] is None
    assert (await _q(client, h, metric="count"))[0]["value"] == 0
    for body in (
        {"metric": "count", "group_by": "title"},
        {"metric": "sum"},
        {"metric": "count", "period": "1d"},
        {"metric": "count", "filters": {"status": "new"}},
    ):
        r = await client.post(URL, json=body, headers=h)
        assert r.status_code == 422, body
