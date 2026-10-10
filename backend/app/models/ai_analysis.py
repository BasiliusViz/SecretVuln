import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class AiAnalysisKind(str, enum.Enum):
    summary = "summary"  # «простыми словами»
    triage = "triage"  # вердикт


class AiVerdict(str, enum.Enum):
    true_positive = "true_positive"
    false_positive = "false_positive"
    uncertain = "uncertain"


class AiReviewStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class AiAnalysis(Base, UUIDPKMixin, TimestampMixin):
    """Вывод ИИ по находке. Статус находки не меняет — решает человек."""

    __tablename__ = "ai_analyses"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                        name="ck_ai_analyses_confidence"),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[AiAnalysisKind] = mapped_column(
        Enum(AiAnalysisKind, name="ai_analysis_kind"), nullable=False
    )
    verdict: Mapped[AiVerdict | None] = mapped_column(
        Enum(AiVerdict, name="ai_verdict", create_type=False)
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    title_plain: Mapped[str | None] = mapped_column(String(500))
    explanation: Mapped[str | None] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    review_status: Mapped[AiReviewStatus] = mapped_column(
        Enum(AiReviewStatus, name="ai_review_status"),
        default=AiReviewStatus.pending,
        nullable=False,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)

    author = relationship("User", foreign_keys=[created_by], lazy="selectin")
    reviewer = relationship("User", foreign_keys=[reviewed_by], lazy="selectin")
