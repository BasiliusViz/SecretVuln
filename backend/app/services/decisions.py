"""Запросы «ложное срабатывание» / «риск принят» и их рассмотрение."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_request import DecisionRequest, DecisionStatus
from app.models.finding import Finding, FindingStatus
from app.models.finding_event import ActorType, FindingEventType
from app.schemas.decision import DecisionCreate
from app.services.events import record_event
from app.services.finding_state import set_status

# Находка в этих статусах уже не нуждается в решении
CLOSED_STATUSES = (FindingStatus.false_positive, FindingStatus.risk_accepted, FindingStatus.fixed)


class DecisionError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _tag(req: DecisionRequest) -> str | None:
    return req.reason_tag.value if req.reason_tag else None


async def create_request(
    db: AsyncSession,
    finding: Finding,
    data: DecisionCreate,
    *,
    user_id: uuid.UUID,
    can_approve: bool,
) -> DecisionRequest:
    if finding.status in CLOSED_STATUSES:
        raise DecisionError(409, "Находка уже закрыта — решение не требуется")
    pending = await db.scalar(
        select(DecisionRequest).where(
            DecisionRequest.finding_id == finding.id,
            DecisionRequest.status == DecisionStatus.pending,
        )
    )
    if pending is not None:
        raise DecisionError(409, "По находке уже есть запрос на рассмотрении")

    req = DecisionRequest(
        id=uuid.uuid4(),
        finding_id=finding.id,
        decision_type=data.decision_type,
        status=DecisionStatus.pending,
        reason_tag=data.reason_tag,
        reason=data.reason,
        expires_at=data.expires_at,
        requested_by_id=user_id,
    )
    db.add(req)
    record_event(
        db, finding.id, FindingEventType.request_created,
        actor_type=ActorType.user, actor_id=user_id,
        reason=req.reason, reason_tag=_tag(req),
        payload={"decision_id": str(req.id), "decision_type": req.decision_type.value},
    )
    if can_approve:
        await approve_request(db, req, finding, user_id=user_id, comment=None)
    return req


async def approve_request(
    db: AsyncSession,
    req: DecisionRequest,
    finding: Finding,
    *,
    user_id: uuid.UUID,
    comment: str | None,
) -> None:
    if req.status != DecisionStatus.pending:
        raise DecisionError(409, "Запрос уже рассмотрен")
    req.status = DecisionStatus.approved
    req.decided_by_id = user_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_comment = comment
    previous = await set_status(db, finding, FindingStatus(req.decision_type.value))
    record_event(
        db, finding.id, FindingEventType.request_decided,
        actor_type=ActorType.user, actor_id=user_id,
        from_status=previous, to_status=finding.status,
        reason=req.reason, reason_tag=_tag(req),
        payload={"decision_id": str(req.id), "result": "approved", "comment": comment},
    )


async def reject_request(
    db: AsyncSession,
    req: DecisionRequest,
    finding: Finding,
    *,
    user_id: uuid.UUID,
    comment: str,
) -> None:
    if req.status != DecisionStatus.pending:
        raise DecisionError(409, "Запрос уже рассмотрен")
    req.status = DecisionStatus.rejected
    req.decided_by_id = user_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_comment = comment
    record_event(
        db, finding.id, FindingEventType.request_decided,
        actor_type=ActorType.user, actor_id=user_id,
        reason=comment,
        payload={"decision_id": str(req.id), "result": "rejected"},
    )
