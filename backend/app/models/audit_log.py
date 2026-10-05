import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPKMixin
from app.models.finding_event import ActorType


class AuditLog(Base, UUIDPKMixin):
    """Журнал аудита административных действий. Только вставка."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_entity_created", "entity_id", "created_at"),
        Index("ix_audit_log_actor_created", "actor_id", "created_at"),
    )

    # clock_timestamp(), а не now(): записи одной транзакции упорядочены
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type", create_type=False), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_label: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_label: Mapped[str | None] = mapped_column(String(1024))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL")
    )
    entity_path: Mapped[str | None] = mapped_column(String(1024))
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
