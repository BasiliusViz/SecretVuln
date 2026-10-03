import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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
    in_progress = "in_progress"
    false_positive = "false_positive"
    risk_accepted = "risk_accepted"
    fixed = "fixed"


# Открытые статусы: участвуют в автозакрытии и переназначении владельца.
# Решения людей (ложное/риск) и fixed не трогаем.
OPEN_STATUSES: tuple[FindingStatus, ...] = (
    FindingStatus.new,
    FindingStatus.triaged,
    FindingStatus.confirmed,
    FindingStatus.in_progress,
)
CLOSED_STATUSES: tuple[FindingStatus, ...] = (
    FindingStatus.fixed,
    FindingStatus.false_positive,
    FindingStatus.risk_accepted,
)


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
    # Короткий номер для ссылок (отображается как SV-<number>)
    number: Mapped[int] = mapped_column(
        BigInteger,
        server_default=text("nextval('finding_number_seq')"),
        unique=True,
        nullable=False,
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

    # Объём скана (например, имя образа) — определяет, какие находки закрывает автозакрытие
    scan_scope: Mapped[str | None] = mapped_column(String(255))
    # Коммит последнего импорта, в котором находку видели (для ссылки на строку кода)
    commit_sha: Mapped[str | None] = mapped_column(String(64))

    # Владелец: команда (по правилам/владельцу проекта или вручную) и, необязательно, человек
    assignee_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="SET NULL"), index=True
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Назначено вручную — повторные импорты не переназначают по правилам
    assigned_manually: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # «Нужна помощь AppSec»: момент запроса, снимается ответом AppSec
    help_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Рекомендация сканера (SARIF rule.help)
    help_text: Mapped[str | None] = mapped_column(Text)

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

    # SLA: начало отсчёта (создание или переоткрытие), срок исправления, момент закрытия
    sla_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entity = relationship("Entity", back_populates="findings")
    import_ = relationship("Import", back_populates="findings")
    assignee_group = relationship("UserGroup", lazy="selectin")
    assignee_user = relationship("User", lazy="selectin")
