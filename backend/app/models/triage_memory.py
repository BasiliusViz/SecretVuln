import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.decision_request import DecisionType, ReasonTag


class MemoryStatus(str, enum.Enum):
    suggested = "suggested"
    approved = "approved"
    disabled = "disabled"


class MemorySource(str, enum.Enum):
    manual = "manual"
    suggested = "suggested"


class TriageMemory(Base, UUIDPKMixin, TimestampMixin):
    """Правило команды: «такие находки в этом поддереве мы считаем ложными / принимаем риск».

    Правило только подсказывает (findings.memory_id) — статус находки меняет человек
    через обычный запрос решения. Условие: все заданные поля должны совпасть,
    хотя бы одно обязательно."""

    __tablename__ = "triage_memories"
    __table_args__ = (
        CheckConstraint(
            "scanner IS NOT NULL OR rule_id IS NOT NULL OR cwe IS NOT NULL "
            "OR path_glob IS NOT NULL",
            name="ck_triage_memories_condition",
        ),
    )

    # Область: проект и всё его поддерево
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scanner: Mapped[str | None] = mapped_column(String(100))
    rule_id: Mapped[str | None] = mapped_column(String(512))
    cwe: Mapped[str | None] = mapped_column(String(50))
    path_glob: Mapped[str | None] = mapped_column(String(1024))

    decision: Mapped[DecisionType] = mapped_column(
        Enum(DecisionType, name="decision_type", create_type=False), nullable=False
    )
    reason_tag: Mapped[ReasonTag | None] = mapped_column(
        Enum(ReasonTag, name="reason_tag", create_type=False)
    )
    reason: Mapped[str | None] = mapped_column(Text)

    status: Mapped[MemoryStatus] = mapped_column(
        Enum(MemoryStatus, name="memory_status"),
        default=MemoryStatus.approved,
        index=True,
        nullable=False,
    )
    source: Mapped[MemorySource] = mapped_column(
        Enum(MemorySource, name="memory_source"), default=MemorySource.manual, nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
