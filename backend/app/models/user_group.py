import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class GroupSource(str, enum.Enum):
    manual = "manual"  # состав правится вручную в UI
    ldap = "ldap"      # состав — зеркало LDAP-группы, перезаписывается при синке


# Many-to-many: пользователь ↔ группа
user_group_members = Table(
    "user_group_members",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey("user_groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)



class UserGroup(Base, UUIDPKMixin, TimestampMixin):
    """Группа пользователей. Ручная (состав в UI) или LDAP (зеркало LDAP-группы).

    Роли на проекты выдаются привязками (`role_bindings`) — здесь только «кто».
    """

    __tablename__ = "user_groups"

    name: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[GroupSource] = mapped_column(
        Enum(GroupSource, name="group_source"),
        default=GroupSource.manual,
        nullable=False,
    )
    # CN LDAP-группы, из которой тянем состав (для source=ldap). По умолчанию = name.
    ldap_group: Mapped[str | None] = mapped_column(String(512), index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    members = relationship(
        "User",
        secondary=user_group_members,
        backref="groups",
        lazy="selectin",
    )
