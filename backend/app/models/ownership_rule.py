import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class RuleSource(str, enum.Enum):
    file = "file"      # пришло из .secretvuln.yml
    manual = "manual"  # задано в админке (список закреплён)


class OwnershipRule(Base, UUIDPKMixin, TimestampMixin):
    """Маска пути → команда. Действует на проект и его поддерево."""

    __tablename__ = "ownership_rules"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pattern: Mapped[str] = mapped_column(String(512), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[RuleSource] = mapped_column(Enum(RuleSource, name="rule_source"), nullable=False)

    group = relationship("UserGroup", lazy="selectin")
