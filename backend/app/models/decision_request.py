import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class DecisionType(str, enum.Enum):
    false_positive = "false_positive"
    risk_accepted = "risk_accepted"


class DecisionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"  # истёк срок принятия риска


class ReasonTag(str, enum.Enum):
    data_not_user_controlled = "data_not_user_controlled"  # Данные не приходят от пользователя
    test_code = "test_code"                                # Тестовый или демо-код
    sanitized = "sanitized"                                # Уже есть проверка или экранирование
    dead_code = "dead_code"                                # Код не используется
    other = "other"                                        # Другое (текст обязателен)


class DecisionRequest(Base, UUIDPKMixin, TimestampMixin):
    """Запрос «ложное срабатывание» / «риск принят». Правило двух ключей:
    разработчик запрашивает, AppSec (finding:approve) одобряет."""

    __tablename__ = "decision_requests"
    __table_args__ = (
        Index(
            "uq_decision_requests_pending",
            "finding_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    decision_type: Mapped[DecisionType] = mapped_column(
        Enum(DecisionType, name="decision_type"), nullable=False
    )
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, name="decision_status"),
        default=DecisionStatus.pending,
        index=True,
        nullable=False,
    )
    reason_tag: Mapped[ReasonTag | None] = mapped_column(Enum(ReasonTag, name="reason_tag"))
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decision_comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
