from datetime import datetime, timedelta, timezone

from app.models.finding import FindingStatus, Severity
from tests.factories import make_entity, make_finding, make_group

URL = "/api/v1/metrics/aggregate"
NOW = datetime.now(timezone.utc)


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
    await make_finding(db, prod, "fixed", status=FindingStatus.fixed,
                       first_seen=NOW - 6 * d, resolved_at=NOW - 2 * d)
    await make_finding(db, dev, "fp", status=FindingStatus.false_positive,
                       first_seen=NOW - 5 * d, resolved_at=NOW - 1 * d)
    await make_finding(db, dev, "old", status=FindingStatus.fixed,
                       first_seen=NOW - 400 * d, resolved_at=NOW - 200 * d)
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
