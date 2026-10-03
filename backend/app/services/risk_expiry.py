"""Истечение срока принятого риска: находка возвращается в «Новая»."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_request import DecisionRequest, DecisionStatus, DecisionType
from app.models.finding import Finding, FindingStatus
from app.models.finding_event import FindingEventType
from app.services.events import record_event
from app.services.finding_state import set_status


async def expire_risk_acceptances(db: AsyncSession, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    requests = await db.scalars(
        select(DecisionRequest).where(
            DecisionRequest.decision_type == DecisionType.risk_accepted,
            DecisionRequest.status == DecisionStatus.approved,
            DecisionRequest.expires_at <= now,
        )
    )
    reopened = 0
    for req in list(requests):
        req.status = DecisionStatus.expired
        finding = await db.get(Finding, req.finding_id)
        if finding is not None and finding.status == FindingStatus.risk_accepted:
            await set_status(db, finding, FindingStatus.new, now=now)
            record_event(
                db, finding.id, FindingEventType.reopened,
                from_status=FindingStatus.risk_accepted, to_status=FindingStatus.new,
                reason="Истёк срок принятия риска",
                payload={"decision_id": str(req.id)},
            )
            reopened += 1
    await db.commit()
    return reopened
