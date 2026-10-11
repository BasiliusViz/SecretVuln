"""Этап 7: метрика `ai_agreement` — согласие людей с вердиктами ИИ."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AiAnalysis, AiAnalysisKind, FindingEvent
from app.models.ai_analysis import AiReviewStatus, AiVerdict
from app.models.finding import FindingStatus, Severity
from app.models.finding_event import FindingEventType
from app.services.events import record_event
from tests.factories import make_entity, make_finding

URL = "/api/v1/metrics/aggregate"
NOW = datetime.now(timezone.utc)
FP, TP, UN = AiVerdict.false_positive, AiVerdict.true_positive, AiVerdict.uncertain
S = FindingStatus


async def _case(db, entity, fp, status, verdict, review=AiReviewStatus.pending, *,
                agent="sv-builtin", model="m1", kind=AiAnalysisKind.triage, at=None,
                severity=Severity.high, auto_fixed=False):
    finding = await make_finding(db, entity, fp, status=status, severity=severity)
    if status == S.fixed:  # «исправлено» человеком — или автозакрытием при импорте
        record_event(
            db, finding.id,
            FindingEventType.auto_fixed if auto_fixed else FindingEventType.status_changed,
            from_status=S.confirmed, to_status=S.fixed,
        )
    db.add(AiAnalysis(
        finding_id=finding.id, kind=kind, verdict=verdict, review_status=review,
        agent=agent, model=model, created_at=at or NOW - timedelta(days=1),
    ))
    await db.flush()
    return finding


async def _q(client, headers, **body):
    r = await client.post(URL, json={"metric": "ai_agreement", **body}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["rows"]


async def test_explicit_and_implicit_agreement(client, developer, db):
    e = await make_entity(db)
    # явное: принято — согласие, отклонено — несогласие (статус находки не важен)
    await _case(db, e, "acc", S.new, FP, AiReviewStatus.accepted)
    await _case(db, e, "rej", S.false_positive, FP, AiReviewStatus.rejected)
    # неявное по итоговому статусу
    await _case(db, e, "fp-fp", S.false_positive, FP)  # согласие
    await _case(db, e, "tp-fixed", S.fixed, TP)  # согласие
    await _case(db, e, "tp-conf", S.confirmed, TP)  # согласие
    await _case(db, e, "fp-prog", S.in_progress, FP)  # несогласие
    await _case(db, e, "tp-fp", S.false_positive, TP)  # несогласие
    # не учитываются: открытые без решения, uncertain, summary, вне периода
    await _case(db, e, "tp-new", S.new, TP)
    await _case(db, e, "fp-triaged", S.triaged, FP)
    await _case(db, e, "un", S.fixed, UN, AiReviewStatus.accepted)
    await _case(db, e, "sum", S.fixed, None, AiReviewStatus.accepted, kind=AiAnalysisKind.summary)
    await _case(db, e, "old", S.fixed, TP, at=NOW - timedelta(days=60))
    await db.commit()

    [row] = await _q(client, developer[1], period="30d")
    assert row["count"] == 7
    assert row["value"] == round(4 / 7 * 100, 4)


async def test_autofixed_is_not_a_human_decision(client, developer, db):
    e = await make_entity(db)
    await _case(db, e, "human", S.fixed, TP)  # согласие
    await _case(db, e, "auto", S.fixed, FP, auto_fixed=True)  # не учитывается
    # закрыл человек, скан переоткрыл, потом автозакрытие — решает последнее закрытие
    f = await _case(db, e, "reopened", S.fixed, FP, auto_fixed=True)
    record_event(db, f.id, FindingEventType.status_changed, from_status=S.confirmed,
                 to_status=S.fixed)
    await db.flush()
    for ev in (await db.scalars(select(FindingEvent).where(FindingEvent.finding_id == f.id))):
        ev.created_at = NOW - timedelta(days=5 if ev.event_type == FindingEventType.status_changed else 1)
    await db.commit()

    [row] = await _q(client, developer[1])
    assert row["count"] == 1 and row["value"] == 100.0


async def test_only_latest_verdict_per_agent(client, developer, db):
    e = await make_entity(db)
    f = await _case(db, e, "x", S.false_positive, TP, at=NOW - timedelta(days=3))
    # повторные разборы той же находки: голос — только у последнего вывода агента
    for days, verdict in ((2, TP), (1, FP)):
        db.add(AiAnalysis(finding_id=f.id, kind=AiAnalysisKind.triage, verdict=verdict,
                          review_status=AiReviewStatus.pending, agent="sv-builtin", model="m1",
                          created_at=NOW - timedelta(days=days)))
    # другой агент по той же находке — свой голос
    db.add(AiAnalysis(finding_id=f.id, kind=AiAnalysisKind.triage, verdict=TP,
                      review_status=AiReviewStatus.pending, agent="claude-code",
                      created_at=NOW - timedelta(days=1)))
    await db.commit()

    by_agent = {r["key"]: (r["value"], r["count"]) for r in
                await _q(client, developer[1], group_by="ai_agent")}
    assert by_agent == {"sv-builtin": (100.0, 1), "claude-code": (0.0, 1)}


async def test_empty(client, developer, db):
    e = await make_entity(db)
    await _case(db, e, "tp-new", S.new, TP)
    await db.commit()

    [row] = await _q(client, developer[1])
    assert row["value"] is None and row["count"] == 0


async def test_group_by_agent_model_and_severity(client, developer, db):
    e = await make_entity(db)
    await _case(db, e, "a", S.fixed, TP, agent="sv-builtin", model="m1")
    await _case(db, e, "b", S.fixed, FP, agent="sv-builtin", model="m2",
                severity=Severity.critical)
    await _case(db, e, "c", S.false_positive, FP, agent="claude-code", model="opus")
    await db.commit()

    by_agent = {r["key"]: (r["value"], r["count"]) for r in
                await _q(client, developer[1], group_by="ai_agent")}
    assert by_agent == {"sv-builtin": (50.0, 2), "claude-code": (100.0, 1)}

    by_model = {r["key"]: r["value"] for r in await _q(client, developer[1], group_by="ai_model")}
    assert by_model == {"m1": 100.0, "m2": 0.0, "opus": 100.0}

    by_sev = {r["key"]: r["value"] for r in await _q(client, developer[1], group_by="severity")}
    assert by_sev == {"high": 100.0, "critical": 0.0}

    weeks = await _q(client, developer[1], group_by="week")
    assert sum(r["count"] for r in weeks) == 3


async def test_scope_hides_foreign_projects(client, db, two_teams):
    await _case(db, two_teams.a_svc, "a", S.fixed, TP)
    await _case(db, two_teams.b_svc, "b", S.false_positive, TP)
    await db.commit()

    [row] = await _q(client, two_teams.dev_a[1])
    assert row == {"key": "all", "label": "all", "value": 100.0, "count": 1}


async def test_old_metrics_have_no_count(client, developer, db):
    await make_finding(db, await make_entity(db), "x")
    r = await client.post(URL, json={"metric": "count"}, headers=developer[1])
    assert r.json()["rows"][0]["count"] is None


async def test_ai_groups_only_for_ai_metric(client, developer):
    r = await client.post(URL, json={"metric": "count", "group_by": "ai_model"},
                          headers=developer[1])
    assert r.status_code == 422
