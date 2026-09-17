import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Severity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class FindingStatus(str, enum.Enum):
    new = "new"
    triaged = "triaged"
    confirmed = "confirmed"
    false_positive = "false_positive"
    risk_accepted = "risk_accepted"
    fixed = "fixed"


class Finding(Base, UUIDPKMixin, TimestampMixin):
    """A normalized security finding parsed from a SARIF result.

    Attached to the entity (tree node) the SARIF file was imported into.
    Deduplication: `fingerprint` is derived from SARIF partialFingerprints
    (fallback: hash of rule_id + file_path + normalized snippet). Unique per
    entity — the same vulnerability in two sibling entities is two findings.

    Future extension point: an `ai_analyses` table will reference `findings.id`
    (one-to-many) — do not embed AI output here.
    """

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("entity_id", "fingerprint", name="uq_findings_entity_fingerprint"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The import that last touched this finding (first import if never re-seen)
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity"), index=True, nullable=False
    )
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status"),
        default=FindingStatus.new,
        index=True,
        nullable=False,
    )

    # Normalized scanner metadata
    scanner: Mapped[str] = mapped_column(String(100), index=True, nullable=False)  # semgrep, trivy, ...
    rule_id: Mapped[str | None] = mapped_column(String(512), index=True)
    cwe: Mapped[str | None] = mapped_column(String(50))

    # Location
    file_path: Mapped[str | None] = mapped_column(String(1024))
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)

    # Dedup key (from SARIF partialFingerprints or computed fallback)
    fingerprint: Mapped[str] = mapped_column(String(512), nullable=False)

    # Original SARIF result object, untouched — source of truth for re-normalization
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entity = relationship("Entity", back_populates="findings")
    import_ = relationship("Import", back_populates="findings")
