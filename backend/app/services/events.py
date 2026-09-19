"""Запись истории находок."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import FindingStatus
from app.models.finding_event import ActorType, FindingEvent, FindingEventType


def record_event(
    db: AsyncSession,
    finding_id: uuid.UUID,
    event_type: FindingEventType,
    *,
    actor_type: ActorType = ActorType.system,
    actor_id: uuid.UUID | None = None,
    from_status: FindingStatus | None = None,
    to_status: FindingStatus | None = None,
    reason: str | None = None,
    reason_tag: str | None = None,
    payload: dict[str, Any] | None = None,
) -> FindingEvent:
    event = FindingEvent(
        finding_id=finding_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        reason_tag=reason_tag,
        payload=payload or {},
    )
    db.add(event)
    return event
