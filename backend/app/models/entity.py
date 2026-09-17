import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Entity(Base, UUIDPKMixin, TimestampMixin):
    """A node in a free-form user-built tree (like a folder).

    No fixed semantics: an entity can contain child entities and/or receive
    scan results (imports/findings) — both at once. How to structure the tree
    (org -> product -> repo, flat list of repos, ...) is entirely up to the user.
    Name is unique among siblings (per parent), not globally.
    Deleting an entity cascades to its whole subtree, imports and findings.
    """

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint(
            "parent_id", "name", name="uq_entities_parent_name", postgresql_nulls_not_distinct=True
        ),
    )

    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    # Arbitrary user-defined fields (team, criticality, repo URL, ...)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    findings = relationship("Finding", back_populates="entity", cascade="all, delete-orphan")
    imports = relationship("Import", back_populates="entity", cascade="all, delete-orphan")
