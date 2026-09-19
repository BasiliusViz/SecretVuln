import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPKMixin
from app.models.finding import FindingStatus


class FindingEventType(str, enum.Enum):
    imported = "imported"
    status_changed = "status_changed"
    reopened = "reopened"
    auto_fixed = "auto_fixed"
    request_created = "request_created"
    request_decided = "request_decided"


class ActorType(str, enum.Enum):
    user = "user"
    agent = "agent"
    system = "system"


class FindingEvent(Base, UUIDPKMixin):
    """Запись истории находки. Только добавление — не редактируется и не удаляется."""

    __tablename__ = "finding_events"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[FindingEventType] = mapped_column(
        Enum(FindingEventType, name="finding_event_type"), nullable=False
    )
    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    from_status: Mapped[FindingStatus | None] = mapped_column(
        Enum(FindingStatus, name="finding_status", create_type=False)
    )
    to_status: Mapped[FindingStatus | None] = mapped_column(
        Enum(FindingStatus, name="finding_status", create_type=False)
    )
    reason: Mapped[str | None] = mapped_column(Text)
    reason_tag: Mapped[str | None] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
