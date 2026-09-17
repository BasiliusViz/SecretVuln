import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class ImportStatus(str, enum.Enum):
    pending = "pending"        # file stored in S3, ARQ job enqueued
    processing = "processing"  # worker picked it up
    done = "done"
    failed = "failed"


class Import(Base, UUIDPKMixin, TimestampMixin):
    """One SARIF file upload into an entity. Processed asynchronously by the ARQ worker."""

    __tablename__ = "imports"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Detected by the worker from SARIF tool.driver.name (semgrep, trivy, gitleaks, checkov, ...)
    scanner: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status"),
        default=ImportStatus.pending,
        index=True,
        nullable=False,
    )
    # e.g. {"created": 10, "updated": 3, "duplicates": 5, "total_results": 18}
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entity = relationship("Entity", back_populates="imports")
    uploaded_by = relationship("User")
    findings = relationship("Finding", back_populates="import_")
