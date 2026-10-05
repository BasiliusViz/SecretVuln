import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin


class RoleBinding(Base, UUIDPKMixin):
    """Привязка: группа получает роль на проект и всё его поддерево.

    `entity_id = NULL` — на всё дерево (глобально). Ссылка по id, а не по пути:
    переименование и перенос узла доступ не ломают.
    """

    __tablename__ = "role_bindings"
    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "role_id",
            "entity_id",
            name="uq_role_bindings_group_role_entity",
            postgresql_nulls_not_distinct=True,
        ),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    group = relationship("UserGroup", lazy="selectin")
    role = relationship("Role", lazy="selectin")
    entity = relationship("Entity", lazy="selectin")
