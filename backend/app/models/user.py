import enum

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class AuthSource(str, enum.Enum):
    local = "local"
    ldap = "ldap"


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    # Null for LDAP-provisioned users (they authenticate via LDAP bind)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    auth_source: Mapped[AuthSource] = mapped_column(
        Enum(AuthSource, name="auth_source"), default=AuthSource.local, nullable=False
    )
    ldap_dn: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
