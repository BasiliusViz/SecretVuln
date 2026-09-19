from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import DecisionRequest, FindingEvent
from app.models.decision_request import DecisionStatus, DecisionType
from app.models.finding import FindingStatus
from app.models.finding_event import FindingEventType
from app.services.risk_expiry import expire_risk_acceptances
from tests.factories import make_entity, make_finding


async def _accepted(db, entity, fp, expires_at):
    f = await make_finding(db, entity, fp, status=FindingStatus.risk_accepted)
    req = DecisionRequest(
        finding_id=f.id,
        decision_type=DecisionType.risk_accepted,
        status=DecisionStatus.approved,
        reason="WAF",
        expires_at=expires_at,
    )
    db.add(req)
    await db.commit()
    return f, req


async def test_expired_risk_reopens(db):
    entity = await make_entity(db)
    now = datetime.now(timezone.utc)
    old, old_req = await _accepted(db, entity, "a", now - timedelta(hours=1))
    fresh, fresh_req = await _accepted(db, entity, "b", now + timedelta(days=10))

    assert await expire_risk_acceptances(db, now=now) == 1

    for obj in (old, old_req, fresh, fresh_req):
        await db.refresh(obj)
    assert old.status == FindingStatus.new
    assert old_req.status == DecisionStatus.expired
    assert fresh.status == FindingStatus.risk_accepted
    assert fresh_req.status == DecisionStatus.approved
    ev = await db.scalar(
        select(FindingEvent).where(
            FindingEvent.finding_id == old.id, FindingEvent.event_type == FindingEventType.reopened
        )
    )
    assert ev is not None and ev.from_status == FindingStatus.risk_accepted


async def test_expiry_is_idempotent(db):
    entity = await make_entity(db)
    now = datetime.now(timezone.utc)
    await _accepted(db, entity, "a", now - timedelta(hours=1))
    assert await expire_risk_acceptances(db, now=now) == 1
    assert await expire_risk_acceptances(db, now=now) == 0
